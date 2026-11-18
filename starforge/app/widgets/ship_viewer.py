"""原生 3D 飞船视口（P0 spike）。

输入与 ``preview.preview_mesh`` 完全一致：
    groups = {(class, tex): (pos f32[n,3], nrm f32[n,3], uv f32[n,2], idx u32[m])}
    colours = {"paint": (r,g,b), ...}

渲染逻辑移植自原 ``viewer.js``：三点光 + Blinn 高光 + sRGB→线性 + gamma。
不依赖 QWebEngine；无 OpenGL 时由上层退回服务端 PNG。
"""
from __future__ import annotations

import math

from PySide6.QtCore import QBuffer, QIODevice, QPoint, Qt, QTimer
from PySide6.QtGui import (
    QImage,
    QMatrix4x4,
    QOpenGLFunctions,
    QSurfaceFormat,
    QVector3D,
)
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QOpenGLVertexArrayObject,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from ...core import log

log = log.get("ui.viewer")

try:                                    # 让 Linux 上带反斜杠的材质名也能找到贴图
    from ... import preview as _preview
    _preview.ensure_texture_paths()
except Exception as e:                  # noqa: BLE001 - 没有上游时继续平涂
    log.debug("贴图路径兼容处理跳过：%s", e)

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
attribute vec2 aUv;
uniform mat4 uMvp;
uniform mat3 uNormal;
varying vec3 vN;
varying vec3 vP;
varying vec2 vUv;
void main() {
    vN = normalize(uNormal * aNrm);
    vP = aPos;
    vUv = aUv;
    gl_Position = uMvp * vec4(aPos, 1.0);
}
"""

FRAG = """
#version 120
varying vec3 vN;
varying vec3 vP;
varying vec2 vUv;
uniform vec3 uColor;
uniform vec3 uLight;
uniform float uEmissive;
uniform sampler2D uTex;
uniform float uHasTex;
vec3 srgb2lin(vec3 c) { return pow(c, vec3(2.2)); }
vec3 lin2srgb(vec3 c) { return pow(c, vec3(1.0 / 2.2)); }
void main() {
    vec3 n = normalize(vN);
    vec3 base = uHasTex > 0.5 ? srgb2lin(texture2D(uTex, vUv).rgb) : srgb2lin(uColor);
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
GL_TEXTURE_2D = 0x0DE1
GL_RGBA = 0x1908
GL_UNSIGNED_BYTE = 0x1401
GL_TEXTURE_MIN_FILTER = 0x2801
GL_TEXTURE_MAG_FILTER = 0x2800
GL_LINEAR = 0x2601
GL_TEXTURE_WRAP_S = 0x2802
GL_TEXTURE_WRAP_T = 0x2803
GL_REPEAT = 0x2901
GL_TEXTURE0 = 0x84C0

_GROUP_COLOR = {
    "paint": (0.55, 0.62, 0.78),
    "secondary": (0.30, 0.33, 0.40),
    "metal": (0.45, 0.47, 0.50),
    "dark": (0.13, 0.14, 0.17),
    "glow": (1.00, 0.62, 0.22),
    "glass": (0.55, 0.78, 0.90),
}


class _Prim:
    __slots__ = ("color", "count", "emissive", "ibo", "texture", "vbo_nrm", "vbo_pos", "vbo_uv")

    def __init__(self) -> None:
        self.vbo_pos: QOpenGLBuffer | None = None
        self.vbo_nrm: QOpenGLBuffer | None = None
        self.vbo_uv: QOpenGLBuffer | None = None
        self.ibo: QOpenGLBuffer | None = None
        self.texture: QOpenGLTexture | None = None
        self.count = 0
        self.color = (0.6, 0.6, 0.65)
        self.emissive = 0.0

    def destroy(self) -> None:
        for b in (self.vbo_pos, self.vbo_nrm, self.vbo_uv, self.ibo):
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
        self._texture_inputs: dict = {}
        self._textures_gl: dict[str, QOpenGLTexture] = {}
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
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(33)
        self._spin_timer.timeout.connect(self._spin_step)
        self._u_mvp = self._u_normal = self._u_light = self._u_color = self._u_emissive = -1
        self._u_tex = self._u_has_tex = -1

    # ---------------------------------------------------------------- 数据

    def set_mesh(self, groups: dict, colours: dict | None = None,
                 textures: dict | None = None) -> None:
        """绘制几何组；textures 为空时按 tex 字段自动从游戏 pak 找贴图。

        textures 的值可以是 RGBA ndarray、QImage 或 PNG 字节。找不到/解不开贴图的组
        继续使用 colours 平涂，所以旧的 set_mesh(groups, colours) 调用完全不受影响。
        """
        if np is None:
            self._failed = True
            self._error = f"NumPy 不可用：{_NUMPY_ERROR}"
            return
        self._groups = groups or {}
        self._colours = colours or {}
        self._texture_inputs = (self._auto_textures(self._groups) if textures is None
                                else dict(textures or {}))
        self._compute_bounds()
        self._pending = True
        self.update()

    def set_textures(self, textures: dict | None) -> None:
        self._texture_inputs = dict(textures or {})
        self._pending = True
        self.update()

    @staticmethod
    def _auto_textures(groups: dict) -> dict:
        out = {}
        if np is None:
            return out
        try:
            from ... import tex as tex_mod
        except Exception:                                  # noqa: BLE001
            return out
        for key in groups:
            tex = key[1] if isinstance(key, tuple) and len(key) > 1 else ""
            if not tex or tex in out:
                continue
            try:
                out[tex] = tex_mod.rgba(tex)
            except Exception as e:                         # noqa: BLE001 - 这一组退回平涂
                log.debug("视口贴图跳过 %s：%s", tex, e)
        return out

    @staticmethod
    def _to_qimage(value) -> QImage | None:
        if isinstance(value, QImage):
            img = value
        elif isinstance(value, (bytes, bytearray, memoryview)):
            img = QImage.fromData(bytes(value))
        else:
            if isinstance(value, dict):
                value = value.get("rgba", value.get("data", value.get("pixels")))
            try:
                arr = np.asarray(value)
            except Exception:                              # noqa: BLE001
                return None
            if arr.ndim != 3 or arr.shape[2] not in (3, 4):
                return None
            if arr.dtype != np.uint8:
                arr = np.nan_to_num(arr.astype(np.float32))
                if arr.max() <= 1.0:
                    arr = arr * 255.0
                arr = np.clip(arr, 0, 255).astype(np.uint8)
            if arr.shape[2] == 3:
                arr = np.concatenate([arr, np.full(arr.shape[:2] + (1,), 255, np.uint8)], axis=2)
            arr = np.ascontiguousarray(arr)
            h, w = arr.shape[:2]
            img = QImage(arr.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
        if img.isNull():
            return None
        return img.convertToFormat(QImage.Format_RGBA8888)

    def clear(self) -> None:
        self._groups = {}
        self._colours = {}
        self._texture_inputs = {}
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
        # 不清楚上游三角面的绕序，先双面渲染；稳定优先，避免“有顶点但看不到模型”
        f.glDisable(GL_CULL_FACE)
        f.glEnable(GL_MULTISAMPLE)
        self._vao = QOpenGLVertexArrayObject()
        self._vao.create()
        self._program = QOpenGLShaderProgram()
        ok = (self._program.addShaderFromSourceCode(QOpenGLShader.Vertex, VERT)
              and self._program.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAG))
        if ok:
            self._program.bindAttributeLocation("aPos", 0)
            self._program.bindAttributeLocation("aNrm", 1)
            self._program.bindAttributeLocation("aUv", 2)
            ok = self._program.link()
        if not ok:
            self._error = self._program.log() or "着色器编译失败"
            log.error("3D 着色器编译失败：%s", self._error)
            self._program = None
            return
        self._u_mvp = self._program.uniformLocation("uMvp")
        self._u_normal = self._program.uniformLocation("uNormal")
        self._u_light = self._program.uniformLocation("uLight")
        self._u_color = self._program.uniformLocation("uColor")
        self._u_emissive = self._program.uniformLocation("uEmissive")
        self._u_tex = self._program.uniformLocation("uTex")
        self._u_has_tex = self._program.uniformLocation("uHasTex")
        self._upload()

    def _upload(self) -> None:
        for p in self._prims:
            p.destroy()
        self._prims.clear()
        for tex in self._textures_gl.values():
            try:
                tex.destroy()
            except Exception as e:                         # noqa: BLE001
                log.debug("释放贴图失败：%s", e)
        self._textures_gl.clear()
        if not self._groups or self._gl is None:
            return
        for tex, value in self._texture_inputs.items():
            img = self._to_qimage(value)
            if img is None:
                continue
            try:
                obj = QOpenGLTexture(img)
                obj.setWrapMode(QOpenGLTexture.Repeat)
                obj.setMinificationFilter(QOpenGLTexture.Linear)
                obj.setMagnificationFilter(QOpenGLTexture.Linear)
                self._textures_gl[tex] = obj
            except Exception as e:                         # noqa: BLE001 - 这张退回平涂
                log.debug("贴图上传失败 %s：%s", tex, e)
        for key, geo in self._groups.items():
            if len(geo) < 4:
                continue
            pos, nrm, uv, idx = geo
            pos = np.ascontiguousarray(pos, np.float32)
            nrm = np.ascontiguousarray(nrm, np.float32)
            idx = np.ascontiguousarray(idx, np.uint32).reshape(-1)
            if len(pos) == 0 or len(idx) == 0:
                continue
            if len(uv) != len(pos):
                uv = np.zeros((len(pos), 2), np.float32)
            uv = np.ascontiguousarray(uv, np.float32).reshape(-1, 2)
            # PySide6 的 glDrawElements 最后一个指针参数在不同版本上行为不一致；
            # 直接展开索引，用 glDrawArrays，彻底绕开这个坑。
            pos = np.ascontiguousarray(pos[idx], np.float32)
            nrm = np.ascontiguousarray(nrm[idx], np.float32)
            uv = np.ascontiguousarray(uv[idx], np.float32)
            cls = key[0] if isinstance(key, tuple) else str(key)
            tex = key[1] if isinstance(key, tuple) and len(key) > 1 else ""
            col = (self._colours or {}).get(cls) or _GROUP_COLOR.get(cls, (0.6, 0.6, 0.65))
            prim = _Prim()
            prim.color = tuple(float(x) for x in list(col)[:3])
            prim.emissive = 1.0 if cls == "glow" else 0.0
            prim.texture = self._textures_gl.get(tex)
            prim.count = len(pos)
            prim.vbo_pos = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
            prim.vbo_nrm = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
            prim.vbo_uv = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
            for buf in (prim.vbo_pos, prim.vbo_nrm, prim.vbo_uv):
                buf.create()
            prim.vbo_pos.bind()
            prim.vbo_pos.allocate(pos.tobytes(), pos.nbytes)
            prim.vbo_nrm.bind()
            prim.vbo_nrm.allocate(nrm.tobytes(), nrm.nbytes)
            prim.vbo_uv.bind()
            prim.vbo_uv.allocate(uv.tobytes(), uv.nbytes)
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
        self._program.setUniformValue(self._u_tex, 0)
        # 2.1 兼容上下文里 VAO 可能是扩展；不依赖 VAO，直接绑定 buffer + 属性
        for prim in self._prims:
            self._program.setUniformValue(self._u_color, QVector3D(*prim.color))
            self._program.setUniformValue(self._u_emissive, float(prim.emissive))
            has_tex = prim.texture is not None
            self._program.setUniformValue(self._u_has_tex, 1.0 if has_tex else 0.0)
            if has_tex:
                prim.texture.bind(0)
            prim.vbo_pos.bind()
            self._program.enableAttributeArray(0)
            self._program.setAttributeBuffer(0, GL_FLOAT, 0, 3, 0)
            prim.vbo_nrm.bind()
            self._program.enableAttributeArray(1)
            self._program.setAttributeBuffer(1, GL_FLOAT, 0, 3, 0)
            prim.vbo_uv.bind()
            self._program.enableAttributeArray(2)
            self._program.setAttributeBuffer(2, GL_FLOAT, 0, 2, 0)
            f.glDrawArrays(GL_TRIANGLES, 0, prim.count)
            if has_tex:
                prim.texture.release(0)
        self._program.release()

    # ---------------------------------------------------------------- 视图

    def set_view(self, name: str) -> None:
        self._yaw, self._pitch, self._dist = {
            "iso": (35.0, 16.0, 1.0),
            "side": (90.0, 6.0, 1.0),
            "front": (0.0, 6.0, 1.0),
            "top": (0.0, 85.0, 1.0),
            "back": (180.0, 10.0, 1.0),
        }.get(name, (35.0, 16.0, 1.0))
        self.update()

    def set_spin(self, on: bool) -> None:
        if on and not self._spin_timer.isActive():
            self._spin_timer.start()
        elif not on:
            self._spin_timer.stop()

    def _spin_step(self) -> None:
        self._yaw = (self._yaw + 0.8) % 360
        self.update()

    def snapshot_png(self) -> bytes:
        img = self.grabFramebuffer()
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        return bytes(buf.data())

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
