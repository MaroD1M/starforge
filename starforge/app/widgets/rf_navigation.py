"""重构后的工作区导航：4 个工作区 + 当前工作区的二级子导航。

设计目标（对应本轮信息架构调整）：

* 第一级只保留 4 个工作区，每个工作区只有一个“主张”，不再把 7 个页面平铺；
* 第二级只显示当前工作区里的入口，切换工作区时整体替换，避免同级控件过多；
* 所有按钮都有 accessibleName / tooltip，键盘 Tab 只经过可见的导航项；
* 旧导航按钮仍由壳层隐藏保留（兼容快捷键与测试），不在这里生成。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..theme import NAV_ITEM_HEIGHT, NAV_SUB_HEIGHT, SPACE_S, SPACE_XS


class RfWorkspaceNav(QFrame):
    """两级导航：工作区（互斥）+ 子入口（互斥，仅当前工作区可见）。"""

    workspaceSelected = Signal(str)
    viewSelected = Signal(str)

    def __init__(self, workspaces: list[dict], parent=None):
        super().__init__(parent)
        self.setObjectName("workspaceNav")
        self.setAccessibleName("工作区导航")
        self.setToolTip("先选工作区，再选具体入口；每个工作区只回答一个问题")
        self.workspace_buttons: dict[str, QPushButton] = {}
        self.view_buttons: dict[str, QPushButton] = {}
        self._view_hosts: dict[str, QWidget] = {}
        self._workspaces = list(workspaces or [])
        self._workspace = ""
        self._view = ""

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(SPACE_XS)

        # 不用 QButtonGroup：它会把互斥组里未选中的按钮改成 ClickFocus，
        # 导致 Tab 进不去其它工作区。这里手动维护选中态，所有导航项都能 Tab。
        for workspace in self._workspaces:
            key = str(workspace.get("key") or "")
            title = str(workspace.get("title") or key)
            claim = str(workspace.get("claim") or "")
            button = QPushButton(title)
            button.setObjectName("workspaceButton")
            button.setCheckable(True)
            button.setAccessibleName(f"{title}工作区")
            button.setToolTip(f"{title}：{claim}" if claim else title)
            button.setStatusTip(claim)
            button.setFocusPolicy(Qt.StrongFocus)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setMinimumHeight(NAV_ITEM_HEIGHT)
            button.clicked.connect(
                lambda _checked=False, k=key: self.workspaceSelected.emit(k))
            self.workspace_buttons[key] = button
            v.addWidget(button)

            host = QWidget()
            host.setObjectName("subNav")
            host.setAccessibleName(f"{title}子导航")
            hv = QVBoxLayout(host)
            hv.setContentsMargins(SPACE_S, 0, 0, SPACE_XS)
            hv.setSpacing(1)
            for view in workspace.get("views") or []:
                view_key = str(view.get("key") or "")
                view_title = str(view.get("title") or view_key)
                sub = QPushButton(view_title)
                sub.setObjectName("subNavButton")
                sub.setCheckable(True)
                sub.setAccessibleName(f"{title}工作区：{view_title}")
                hint = str(view.get("hint") or "")
                sub.setToolTip(hint or f"{title} · {view_title}")
                sub.setStatusTip(hint)
                sub.setFocusPolicy(Qt.StrongFocus)
                sub.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                sub.setMinimumHeight(NAV_SUB_HEIGHT)
                sub.clicked.connect(
                    lambda _checked=False, k=view_key: self.viewSelected.emit(k))
                self.view_buttons[view_key] = sub
                hv.addWidget(sub)
            host.hide()
            self._view_hosts[key] = host
            v.addWidget(host)

    # ------------------------------------------------------------ 状态

    @property
    def workspace(self) -> str:
        return self._workspace

    @property
    def view(self) -> str:
        return self._view

    def set_workspace(self, key: str) -> None:
        """同步选中状态与可见子导航（不触发信号）。"""
        self._workspace = str(key or "")
        for workspace_key, button in self.workspace_buttons.items():
            button.setChecked(workspace_key == self._workspace)
        for workspace_key, host in self._view_hosts.items():
            host.setVisible(workspace_key == self._workspace)

    def set_view(self, key: str) -> None:
        self._view = str(key or "")
        for view_key, button in self.view_buttons.items():
            button.setChecked(view_key == self._view)

    def clear_view_selection(self) -> None:
        """旧页面（兼容入口）不在工作区里时，取消子入口的选中态。"""
        for button in self.view_buttons.values():
            button.setChecked(False)
        self._view = ""

    def focus_chain(self) -> list[QWidget]:
        """按视觉顺序返回导航控件；隐藏项由 Qt 的 Tab 逻辑自动跳过。"""
        chain: list[QWidget] = []
        for workspace in self._workspaces:
            key = str(workspace.get("key") or "")
            button = self.workspace_buttons.get(key)
            if button is not None:
                chain.append(button)
            for view in workspace.get("views") or []:
                sub = self.view_buttons.get(str(view.get("key") or ""))
                if sub is not None:
                    chain.append(sub)
        return chain
