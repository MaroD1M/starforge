"""船队页右栏的同伴详情：来源行星 + 符文 + 该行星动物联查。

同伴列表仍在 ``PetsView`` 里；这里只展示选中项，并把「复制符文 / 传送到来源
星球」两个动作放在详情区，避免列表行内堆按钮。联查走
``Services.companion_planet``，加载中 / 空 / 失败三态都有明确中文说明。
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ...services import Services, get_services
from .. import notify
from .fleet_flow import FleetFlowBar
from .pets_view import (
    fauna_state_text,
    pet_detail_text,
    pet_glyphs,
    pet_source,
    pet_warp_target,
)
from .ui import ghost_button, muted, primary_button
from .worker import run as run_worker


def companion_facts_text(creature: dict) -> str:
    """右栏补充字段：UA、物种、部件；来源与符文由独立标签展示，避免重复。"""
    lines = pet_detail_text(creature).splitlines()
    return "\n".join(line for line in lines
                     if not line.startswith(("来源：", "符文：")))


class FleetCompanionPanel(QWidget):
    """选中同伴后的详情区；不伪造 3D，也不在列表行内放按钮。"""

    def __init__(self, svc: Services | None = None, parent=None):
        super().__init__(parent)
        self.svc = svc or get_services()
        self._pets = None
        self._path = ""
        self._creature: dict = {}
        self._token = 0
        self._fauna_state = "idle"
        self._last_fauna: dict | None = None
        self._build_ui()
        self.set_creature({})

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.source_label = QLabel("来源行星：—")
        self.source_label.setWordWrap(True)
        self.source_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.source_label)

        self.glyph_label = QLabel("符文：—")
        self.glyph_label.setWordWrap(True)
        self.glyph_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.glyph_label)

        self.detail_label = muted("选中一只同伴后查看来源、UA 与符文。")
        self.detail_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.detail_label)

        self.fauna_label = QLabel("该行星动物：选中同伴后联查。")
        self.fauna_label.setWordWrap(True)
        self.fauna_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.fauna_label)

        self.retry_btn = ghost_button(
            "重试联查", "重新读取该行星的动物发现记录（只读，不写存档）")
        self.retry_btn.setVisible(False)
        self.retry_btn.clicked.connect(self.load_fauna)
        root.addWidget(self.retry_btn, 0, Qt.AlignLeft)

        actions = FleetFlowBar()
        self.copy_btn = ghost_button(
            "复制符文", "复制选中同伴来源行星的 12 位门地址")
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(self._copy_glyph)
        actions.addWidget(self.copy_btn)
        self.warp_btn = primary_button(
            "传送到来源星球",
            "调用游戏内传送门机制，传送到选中同伴的来源星球；高危写操作")
        self.warp_btn.setEnabled(False)
        self.warp_btn.clicked.connect(self._warp)
        actions.addWidget(self.warp_btn)
        root.addWidget(actions)

        self.status_label = muted("")
        root.addWidget(self.status_label)
        root.addStretch(1)

    # ---------------------------------------------------------------- 绑定

    def bind_pets(self, pets) -> None:
        """绑定列表视图：动作复用它的确认/风险文案与后台任务。"""
        self._pets = pets
        if pets is not None and hasattr(pets, "statusChanged"):
            pets.statusChanged.connect(self.set_status)

    def set_path(self, path: str) -> None:
        path = str(path or "").strip()
        if path == self._path:
            return
        self._path = path
        if self._creature:
            self.load_fauna()

    def set_status(self, text: str) -> None:
        self.status_label.setText(str(text or ""))

    # ---------------------------------------------------------------- 选中

    def set_creature(self, creature: dict | None) -> None:
        self._creature = dict(creature) if isinstance(creature, dict) else {}
        if not self._creature:
            self._token += 1
            self._last_fauna = None
            self._fauna_state = "idle"
            self.source_label.setText("来源行星：—")
            self.glyph_label.setText("符文：—")
            self.detail_label.setText("选中一只同伴后查看来源、UA 与符文。")
            self.fauna_label.setText("该行星动物：选中同伴后联查。")
            self.copy_btn.setEnabled(False)
            self.warp_btn.setEnabled(False)
            self.retry_btn.setVisible(False)
            self.status_label.setText("")
            return

        target = pet_warp_target(self._creature)
        self.source_label.setText(f"来源行星：{pet_source(self._creature)}")
        glyphs = pet_glyphs(self._creature)
        if glyphs:
            self.glyph_label.setText(f"符文：{glyphs}")
        elif self._creature.get("origin"):
            self.glyph_label.setText("符文：—（行星位为 0 或地址不合法）")
        else:
            self.glyph_label.setText("符文：—（没有可用的 UA）")
        self.detail_label.setText(companion_facts_text(self._creature))
        self.copy_btn.setEnabled(target is not None)
        self.warp_btn.setEnabled(target is not None)
        if target is None:
            self.fauna_label.setText(
                "该行星动物：无法联查——这只同伴没有可定位的来源行星。")
            self._fauna_state = "empty"
            self.retry_btn.setVisible(False)
            return
        self.load_fauna()

    # ---------------------------------------------------------------- 联查

    def load_fauna(self) -> None:
        self._token += 1
        token = self._token
        if not self._creature:
            return
        if pet_warp_target(self._creature) is None:
            self._fauna_state = "empty"
            self.fauna_label.setText(
                "该行星动物：无法联查——这只同伴没有可定位的来源行星。")
            self.retry_btn.setVisible(False)
            return
        self._fauna_state = "loading"
        self._last_fauna = None
        self.fauna_label.setText("正在联查该行星的动物发现记录…")
        self.retry_btn.setVisible(False)

        def done(res: Any) -> None:
            if token != self._token:
                return
            self._last_fauna = res if isinstance(res, dict) else None
            kind, text = fauna_state_text(res)
            self._set_fauna(kind, text)

        def fail(msg: str) -> None:
            if token != self._token:
                return
            self._set_fauna("error", f"该行星动物联查失败：{msg}。")

        run_worker(self.svc.companion_planet, done, fail,
                   self._creature, self._path or None)

    def _set_fauna(self, kind: str, text: str) -> None:
        self._fauna_state = str(kind or "error")
        self.fauna_label.setText(text)
        self.fauna_label.setToolTip(text)
        self.fauna_label.setAccessibleName(f"行星动物联查：{text.splitlines()[0]}")
        # 空态也允许重试：玩家可能刚在游戏里发现新动物。
        self.retry_btn.setVisible(self._fauna_state in ("empty", "error"))

    @property
    def fauna_state(self) -> str:
        return self._fauna_state

    # ---------------------------------------------------------------- 动作

    def _copy_glyph(self) -> None:
        if self._pets is None:
            notify.warn("复制符文失败：同伴列表尚未就绪")
            return
        self._pets.copy_glyph()

    def _warp(self) -> None:
        if self._pets is None:
            notify.warn("传送失败：同伴列表尚未就绪")
            return
        self._pets.warp_selected()


__all__ = ["FleetCompanionPanel", "companion_facts_text"]
