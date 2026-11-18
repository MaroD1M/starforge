"""原生 3D 飞船视口（P0 spike）。

输入与 ``preview.preview_mesh`` 完全一致：
    groups = {(class, tex): (pos f32[n,3], nrm f32[n,3], uv f32[n,2], idx u32[m])}
    colours = {"paint": (r,g,b), ...}

渲染逻辑移植自原 ``viewer.js``：三点光 + Blinn 高光 + sRGB→线性 + gamma。
不依赖 QWebEngine；无 OpenGL 时由上层退回服务端 PNG。
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMatrix4x4, QOpenGLFunctions, QSurfaceFormat, QVector3D
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLVertexArrayObject,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from ...core import log

log = log.get("ui.viewer")

try:
    import numpy as np
    _NUMPY_ERROR = ""
except Exception as _e:                                      # noqa: BLE001
    np = None                                                # type: ignore[assignment]
    _NUMPY_ERROR = f"{type(_e).__name__}: {_e}"

VERT = """
#version 120
attribute vec3 aPos;
attribute vec3 aNrm;
uniform mat4 uMvp;
uniform mat3 uNormal;
varying vec3 vN;
varying vec3 vP;
void main() {
    vN = normalize(uNormal * aNrm);
    vP = aPos;
    gl_Position = uMvp * vec4(aPos, 1.0);
}
"""

FRAG = """
#version 120
varying vec3 vN;
varying vec3 vP;
uniform vec3 uColor;
uniform vec3 uLight;
uniform float uEmissive;
vec3 srgb2lin(vec3 c) { return pow(c, vec3(2.2)); }
vec3 lin2srgb(vec3 c) { return pow(c, vec3(1.0 / 2.2)); }
void main() {
    vec3 n = normalize(vN);
    vec3 base = srgb2lin(uColor);
    vec3 key  = normalize(uLight);
    vec3 fill = normalize(vec3(-0.6, 0.25, -0.5));
    vec3 rim  = normalize(vec3(0.2, -0.8, 0.6));
    float dk = max(dot(n, key), 0.0);
    float df = max(dot(n, fill), 0.0) * 0.35;
    float dr = max(dot(n, rim), 0.0) * 0.22;
    vec3 viewDir = normalize(-vP);
    vec3 h = normalize(key + viewDir);
    float spec = pow(max(dot(n, h), 0.0), 28.0) * 0.35;
    vec3 c = base * (0.30 + 0.75 * dk + df + dr) + vec3(spec) + base * uEmissive;
    if (uEmissive > 0.5) { c = base * 1.25; }
    gl_FragColor = vec4(lin2srgb(clamp(c, 0.0, 1.0)), 1.0);
}
"""

# PySide6 的 QOpenGLFunctions 不暴露 GL_* 常量（与 PyOpenGL 不同），这里用标准值。
GL_DEPTH_TEST = 0x0B71
GL_CULL_FACE = 0x0B44
GL_BACK = 0x0405
GL_MULTISAMPLE = 0x809D
GL_COLOR_BUFFER_BIT = 0x00004000
GL_DEPTH_BUFFER_BIT = 0x00000100
GL_TRIANGLES = 0x0004
GL_UNSIGNED_INT = 0x1405
GL_FLOAT = 0x1406

_GROUP_COLOR = {
    "paint": (0.55, 0.62, 0.78),
    "secondary": (0.30, 0.33, 0.40),
    "metal": (0.45, 0.47, 0.50),
    "dark": (0.13, 0.14, 0.17),
    "glow": (1.00, 0.62, 0.22),
    "glass": (0.55, 0.78, 0.90),
}


class _Prim:
    __slots__ = ("color", "count", "emissive", "ibo", "vbo_nrm", "vbo_pos")

    def __init__(self) -> None:
        self.vbo_pos: QOpenGLBuffer | None = None
        self.vbo_nrm: QOpenGLBuffer | None = None
        self.ibo: QOpenGLBuffer | None = None
        self.count = 0
        self.color = (0.6, 0.6, 0.65)
        self.emissive = 0.0

    def destroy(self) -> None:
        for b in (self.vbo_pos, self.vbo_nrm, self.ibo):
            if b is not None:
                b.destroy()


class ShipViewer(QOpenGLWidget):
    """可旋转/缩放的飞船视口。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        fmt = QSurfaceFormat()
        fmt.setDepthBufferSize(24)
        fmt.setSamples(4)
        fmt.setVersion(2, 1)
        fmt.setProfile(QSurfaceFormat.CompatibilityProfile)
        self.setFormat(fmt)
        self.setMinimumSize(220, 220)
        self.setFocusPolicy(Qt.StrongFocus)
        self._groups: dict = {}
        self._colours: dict = {}
        self._prims: list[_Prim] = []
        self._pending = False
        self._gl: QOpenGLFunctions | None = None
        self._program: QOpenGLShaderProgram | None = None
        self._vao: QOpenGLVertexArrayObject | None = None
        self._center = QVector3D(0, 0, 0)
        self._radius = 3.0
        self._yaw = 35.0
        self._pitch = 16.0
        self._dist = 1.0
        self._last = QPoint()
        self._error = ""
        self._failed = False
        self._u_mvp = self._u_normal = self._u_light = self._u_color = self._u_emissive = -1

    # ---------------------------------------------------------------- 数据

    def set_mesh(self, groups: dict, colours: dict | None = None) -> None:
        if np is None:
            self._failed = True
            self._error = f"NumPy 不可用：{_NUMPY_ERROR}"
            return
        self._groups = groups or {}
        self._colours = colours or {}
        self._compute_bounds()
        self._pending = True
        self.update()

    def clear(self) -> None:
        self._groups = {}
        self._colours = {}
        self._pending = True
        self._error = ""
        self.update()

    def set_demo(self) -> None:
        """无游戏数据时的 3D spike：一个可辨认的飞船占位几何。"""
        if np is None:
            self._error = f"NumPy 不可用：{_NUMPY_ERROR}"
            return
        def tri(p0, p1, p2):
            p = np.array([p0, p1, p2], np.float32)
            n = np.cross(p[1] - p[0], p[2] - p[0])
            ln = float(np.linalg.norm(n)) or 1.0
            n = np.tile(n / ln, (3, 1)).astype(np.float32)
            return p, n, np.zeros((3, 2), np.float32), np.array([0, 1, 2], np.uint32)

        pos, nrm, uv, idx, base = [], [], [], [], 0
        for p, n, u, i in [
            tri((0, 0.25, 2.6), (-0.35, -0.2, -1.8), (0.35, -0.2, -1.8)),      # 机身
            tri((0, 0.25, 1.4), (-3.2, 0.05, -0.8), (-0.2, 0.0, -1.2)),        # 左翼
            tri((0, 0.25, 1.4), (0.2, 0.0, -1.2), (3.2, 0.05, -0.8)),          # 右翼
            tri((0, 0.25, 1.4), (0, 0.9, -0.5), (0, 0.0, -1.2)),               # 垂尾
        ]:
            pos.append(p); nrm.append(n); uv.append(u); idx.append(i + base); base += 3
        self.set_mesh({("paint", ""): (np.concatenate(pos), np.concatenate(nrm),
                                       np.concatenate(uv), np.concatenate(idx))},
                      {"paint": (0.95, 0.78, 0.42), "glow": (1.0, 0.62, 0.22)})

    def _compute_bounds(self) -> None:
        if not self._groups:
            self._center, self._radius = QVector3D(0, 0, 0), 3.0
            return
        pts = np.concatenate([np.asarray(g[0], np.float32) for g in self._groups.values()])
        lo, hi = pts.min(0), pts.max(0)
        c = (lo + hi) / 2
        self._center = QVector3D(float(c[0]), float(c[1]), float(c[2]))
        self._radius = max(float(np.linalg.norm(hi - lo)) / 2, 0.5)
        self._dist = 1.0

    # ---------------------------------------------------------------- GL

    def initializeGL(self) -> None:
        try:
            self._initialize_gl()
        except Exception as e:                              # noqa: BLE001
            self._failed = True
            self._error = f"{type(e).__name__}: {e}"
            log.exception("3D 初始化失败：%s", self._error)

    def _initialize_gl(self) -> None:
        f = QOpenGLFunctions()
        f.initializeOpenGLFunctions()
        self._gl = f
        f.glClearColor(0.043, 0.055, 0.075, 1.0)
        f.glEnable(GL_DEPTH_TEST)
        f.glEnable(GL_CULL_FACE)
        f.glCullFace(GL_BACK)
        f.glEnable(GL_MULTISAMPLE)
        self._vao = QOpenGLVertexArrayObject()
        self._vao.create()
        self._program = QOpenGLShaderProgram()
        ok = (self._program.addShaderFromSourceCode(QOpenGLShader.Vertex, VERT)
              and self._program.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAG))
        if ok:
            self._program.bindAttributeLocation("aPos", 0)
            self._program.bindAttributeLocation("aNrm", 1)
            ok = self._program.link()
        if not ok:
            self._error = self._program.log() or "着色器编译失败"
            self._program = None
            return
        self._u_mvp = self._program.uniformLocation("uMvp")
        self._u_normal = self._program.uniformLocation("uNormal")
        self._u_light = self._program.uniformLocation("uLight")
        self._u_color = self._program.uniformLocation("uColor")
        self._u_emissive = self._program.uniformLocation("uEmissive")
        self._upload()

    def _upload(self) -> None:
        for p in self._prims:
            p.destroy()
        self._prims.clear()
        if not self._groups or self._gl is None:
            return
        for key, geo in self._groups.items():
            if len(geo) < 4:
                continue
            pos, nrm, uv, idx = geo
            pos = np.ascontiguousarray(pos, np.float32)
            nrm = np.ascontiguousarray(nrm, np.float32)
            idx = np.ascontiguousarray(idx, np.uint32)
            if len(pos) == 0 or len(idx) == 0:
                continue
            cls = key[0] if isinstance(key, tuple) else str(key)
            col = (self._colours or {}).get(cls) or _GROUP_COLOR.get(cls, (0.6, 0.6, 0.65))
            prim = _Prim()
            prim.color = tuple(float(x) for x in list(col)[:3])
            prim.emissive = 1.0 if cls == "glow" else 0.0
            prim.count = len(idx)
            prim.vbo_pos = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
            prim.vbo_nrm = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
            prim.ibo = QOpenGLBuffer(QOpenGLBuffer.IndexBuffer)
            for buf in (prim.vbo_pos, prim.vbo_nrm, prim.ibo):
                buf.create()
            prim.vbo_pos.bind()
            prim.vbo_pos.allocate(pos.tobytes(), pos.nbytes)
            prim.vbo_nrm.bind()
            prim.vbo_nrm.allocate(nrm.tobytes(), nrm.nbytes)
            prim.ibo.bind()
            prim.ibo.allocate(idx.tobytes(), idx.nbytes)
            self._prims.append(prim)
        self._pending = False

    def resizeGL(self, w: int, h: int) -> None:
        if self._gl is not None:
            self._gl.glViewport(0, 0, max(1, w), max(1, h))

    def paintGL(self) -> None:
        if self._failed:
            return
        try:
            self._paint_gl()
        except Exception as e:                              # noqa: BLE001
            # 不让异常逃出 paintGL，否则 Qt 会再次进入 excepthook/QMessageBox，
            # 最终可能变成 access violation。
            self._failed = True
            self._error = f"{type(e).__name__}: {e}"
            log.exception("3D 绘制失败：%s", self._error)
            self._prims.clear()

    def _paint_gl(self) -> None:
        f = self._gl
        if f is None or not self.isValid():
            return
        f.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        if self._pending:
            self._upload()
        if not self._prims or self._program is None:
            return

        eye = QVector3D(
            self._center.x() + self._radius * 2.8 * self._dist * math.cos(math.radians(self._pitch)) * math.sin(math.radians(self._yaw)),
            self._center.y() + self._radius * 2.8 * self._dist * math.sin(math.radians(self._pitch)),
            self._center.z() + self._radius * 2.8 * self._dist * math.cos(math.radians(self._pitch)) * math.cos(math.radians(self._yaw)),
        )
        view = QMatrix4x4()
        view.lookAt(eye, self._center, QVector3D(0, 1, 0))
        aspect = max(1, self.width()) / max(1, self.height())
        proj = QMatrix4x4()
        proj.perspective(42.0, aspect, self._radius * 0.01, self._radius * 100.0)
        mvp = proj * view

        self._program.bind()
        # PySide6 没有 setUniformValue(str, float) 重载；float 必须传 location(int)
        self._program.setUniformValue(self._u_mvp, mvp)
        self._program.setUniformValue(self._u_normal, view.normalMatrix())
        light = QVector3D(0.45, 0.75, 0.5).normalized()
        self._program.setUniformValue(self._u_light, light)
        self._vao.bind()
        for prim in self._prims:
            self._program.setUniformValue(self._u_color, QVector3D(*prim.color))
            self._program.setUniformValue(self._u_emissive, float(prim.emissive))
            prim.vbo_pos.bind()
            self._program.enableAttributeArray(0)
            self._program.setAttributeBuffer(0, GL_FLOAT, 0, 3, 0)
            prim.vbo_nrm.bind()
            self._program.enableAttributeArray(1)
            self._program.setAttributeBuffer(1, GL_FLOAT, 0, 3, 0)
            prim.ibo.bind()
            f.glDrawElements(GL_TRIANGLES, prim.count, GL_UNSIGNED_INT, 0)
        self._vao.release()
        self._program.release()

    # ---------------------------------------------------------------- 交互

    def mousePressEvent(self, e) -> None:
        self._last = e.position().toPoint()

    def mouseMoveEvent(self, e) -> None:
        p = e.position().toPoint()
        dx, dy = p.x() - self._last.x(), p.y() - self._last.y()
        self._last = p
        if e.buttons() & Qt.LeftButton:
            self._yaw += dx * 0.4
            self._pitch = max(-85.0, min(85.0, self._pitch + dy * 0.35))
            self.update()

    def wheelEvent(self, e) -> None:
        self._dist = max(0.35, min(6.0, self._dist * (0.9 if e.angleDelta().y() > 0 else 1.1)))
        self.update()

    def mouseDoubleClickEvent(self, e) -> None:
        self._yaw, self._pitch, self._dist = 35.0, 16.0, 1.0
        self.update()
