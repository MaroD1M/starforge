"""首次启动向导（3 步）：找游戏 → 找存档 → 可选装模板 Mod。

* 不阻塞主界面启动：由壳层用 QTimer 打开，可跳过，也可从顶部「上手」重新打开；
* 只负责引导与状态展示，真正的检测/跳转由壳层执行（向导不碰服务与页面）；
* 第三步是可选步骤，不安装也能完成向导。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..theme import SPACE_L, SPACE_M, SPACE_S, SPACE_XS
from .ui import fit_label, muted

STEPS = (
    {
        "title": "1  找游戏",
        "heading": "先找到游戏目录",
        "body": "Starforge 需要游戏目录来读取数据层、build 指纹与预览资源。"
                "通常自动检测就能找到。",
        "action": "自动检测",
        "manual": "手动选择游戏目录",
        "note": "常见位置：Steam\\steamapps\\common\\No Man's Sky（含 Binaries/NMS.exe）。",
    },
    {
        "title": "2  找存档",
        "heading": "再找到存档目录",
        "body": "存档目录用于查看船队、备份与写回；只扫描 .hg，不会自动修改存档。",
        "action": "重新检测",
        "manual": "手动选择存档目录",
        "note": "常见位置：%APPDATA%\\HelloGames\\NMS\\st_<账号id>。",
    },
    {
        "title": "3  可选：模板 Mod",
        "heading": "可选：安装模板 Mod",
        "body": "装好后游戏表情菜单会出现 8 个可领取模板，才能把搜到的种子「送进游戏」。"
                "只写游戏 MODS 目录，不动存档；可以以后再做。",
        "action": "打开安装位置",
        "manual": "",
        "note": "装完需要重启游戏；不装也能正常搜船，只是不能「送种子」。",
    },
)


class RfOnboardingWizard(QDialog):
    detectRequested = Signal()
    navigateRequested = Signal(str)
    completed = Signal()
    skipped = Signal()

    def __init__(self, health: dict | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("onboardingDialog")
        self.setWindowTitle("三步上手 · Starforge")
        self.setAccessibleName("上手向导")
        self.setToolTip("三步完成设置；随时可跳过，之后从顶部「上手」重新打开")
        self.setModal(True)
        self.setSizeGripEnabled(True)
        self.resize(720, 470)
        self.setMinimumSize(640, 420)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self._health: dict = dict(health or {})
        self._step = 0
        self._busy = False

        v = QVBoxLayout(self)
        v.setContentsMargins(SPACE_L, SPACE_L, SPACE_L, SPACE_L)
        v.setSpacing(SPACE_M)

        title = QLabel("三步把 Starforge 用起来")
        title.setObjectName("onboardingTitle")
        title.setAccessibleName("上手向导标题")
        v.addWidget(title)
        hint = fit_label(QLabel(
            "只做三件事：找到游戏、找到存档、可选装模板 Mod。"
            "每一步都可以跳过；设置之后从顶部「上手」随时回来。"))
        hint.setObjectName("onboardingHint")
        hint.setAccessibleName("上手向导说明")
        v.addWidget(hint)

        body = QHBoxLayout()
        body.setSpacing(SPACE_L)
        left = QVBoxLayout()
        left.setSpacing(SPACE_XS)
        self.step_labels: list[QLabel] = []
        for index, step in enumerate(STEPS):
            label = QLabel(step["title"])
            label.setObjectName("onboardingStep")
            label.setAccessibleName(f"第 {index + 1} 步：{step['title'].split('  ', 1)[-1]}")
            label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            left.addWidget(label)
            self.step_labels.append(label)
        left.addStretch(1)
        foot_hint = muted("提示：这些设置之后都能在「设置」工作区修改。")
        foot_hint.setMinimumWidth(150)
        left.addWidget(foot_hint)
        body.addLayout(left)

        self.stack = QStackedWidget()
        self.stack.setObjectName("onboardingPages")
        self.stack.setAccessibleName("向导步骤内容")
        self._pages: list[QWidget] = []
        self._status_labels: list[QLabel] = []
        self._path_labels: list[QLabel] = []
        self._action_buttons: list[QPushButton] = []
        for index, step in enumerate(STEPS):
            page = QWidget()
            pv = QVBoxLayout(page)
            pv.setContentsMargins(SPACE_L, SPACE_M, SPACE_L, SPACE_M)
            pv.setSpacing(SPACE_S)
            heading = QLabel(step["heading"])
            heading.setObjectName("sectionTitle")
            heading.setAccessibleName(f"步骤标题：{step['heading']}")
            pv.addWidget(heading)
            status = QLabel("检查中…")
            status.setObjectName("onboardingStatus")
            status.setAccessibleName("步骤状态")
            status.setWordWrap(True)
            status.setMinimumWidth(0)
            status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            pv.addWidget(status)
            self._status_labels.append(status)

            path = fit_label(QLabel(""))
            path.setObjectName("muted")
            path.setAccessibleName("当前路径")
            path.setVisible(False)
            pv.addWidget(path)
            self._path_labels.append(path)

            body_label = fit_label(QLabel(step["body"]))
            body_label.setObjectName("muted")
            body_label.setAccessibleName("步骤说明")
            pv.addWidget(body_label)
            note = fit_label(QLabel(str(step.get("note") or "")))
            note.setObjectName("muted")
            note.setAccessibleName("步骤提示")
            note.setVisible(bool(step.get("note")))
            pv.addWidget(note)
            pv.addStretch(1)

            actions = QHBoxLayout()
            actions.setSpacing(SPACE_S)
            action = QPushButton(step["action"])
            action.setObjectName("primaryButton")
            action.setAccessibleName(f"{step['action']}（第 {index + 1} 步）")
            if index == 2:
                action.clicked.connect(lambda: self._navigate("link:mod"))
            else:
                action.clicked.connect(self._detect)
            actions.addWidget(action)
            self._action_buttons.append(action)

            manual_text = step.get("manual") or ""
            manual = QPushButton(manual_text)
            manual.setObjectName("ghostButton")
            manual.setAccessibleName(f"{manual_text}（第 {index + 1} 步）")
            target = "settings:game" if index == 0 else "settings:saves"
            manual.clicked.connect(lambda _=False, t=target: self._navigate(t))
            manual.setVisible(bool(manual_text))
            actions.addWidget(manual)
            actions.addStretch(1)
            pv.addLayout(actions)

            self.stack.addWidget(page)
            self._pages.append(page)
        body.addWidget(self.stack, 1)
        v.addLayout(body, 1)

        footer = QHBoxLayout()
        footer.setSpacing(SPACE_S)
        self.step_counter = QLabel("第 1 / 3 步")
        self.step_counter.setObjectName("muted")
        self.step_counter.setAccessibleName("向导进度")
        footer.addWidget(self.step_counter)
        footer.addStretch(1)
        self.skip_btn = QPushButton("跳过")
        self.skip_btn.setObjectName("ghostButton")
        self.skip_btn.setAccessibleName("跳过上手向导")
        self.skip_btn.setToolTip("关闭向导；之后可从顶部「上手」重新打开")
        self.skip_btn.clicked.connect(self._skip)
        footer.addWidget(self.skip_btn)
        self.back_btn = QPushButton("上一步")
        self.back_btn.setObjectName("ghostButton")
        self.back_btn.setAccessibleName("返回上一步")
        self.back_btn.clicked.connect(lambda: self.set_step(self._step - 1))
        footer.addWidget(self.back_btn)
        self.next_btn = QPushButton("下一步")
        # 每一步的上下文动作（自动检测/打开安装位置）才是主操作；
        # 底部的“下一步”用强调边框，避免同一屏出现两个主按钮。
        self.next_btn.setObjectName("nextStepButton")
        self.next_btn.setAccessibleName("进入下一步")
        self.next_btn.clicked.connect(self._next)
        footer.addWidget(self.next_btn)
        v.addLayout(footer)
        QWidget.setTabOrder(self.stack, self.skip_btn)
        QWidget.setTabOrder(self.skip_btn, self.back_btn)
        QWidget.setTabOrder(self.back_btn, self.next_btn)

        self.update_health(self._health)
        self.set_step(0)

    # ------------------------------------------------------------ 状态

    def update_health(self, health: dict | None) -> None:
        self._health = dict(health or {})
        game = str(self._health.get("game_dir") or "")
        saves = str(self._health.get("saves_dir") or "")
        statuses = (
            (bool(game), "✓ 已找到游戏目录", "× 还没找到游戏目录"),
            (bool(saves), "✓ 已找到存档目录", "× 还没找到存档目录"),
            (True, "可选：安装后游戏表情菜单会出现模板；不装也不影响搜船。",
             "可选：安装后游戏表情菜单会出现模板；不装也不影响搜船。"),
        )
        for index, (ok, good, bad) in enumerate(statuses):
            label = self._status_labels[index]
            label.setText(good if ok else bad)
            label.setProperty("state", "ok" if ok else ("bad" if index < 2 else ""))
            self._repolish(label)
        self._set_path(0, game)
        self._set_path(1, saves)
        self._set_path(2, "")
        self._refresh_step_states()

    def _set_path(self, index: int, path: str) -> None:
        label = self._path_labels[index]
        label.setText(path)
        label.setToolTip(path)
        label.setVisible(bool(path))

    def _refresh_step_states(self) -> None:
        game = bool(self._health.get("game_dir"))
        saves = bool(self._health.get("saves_dir"))
        done = (game, saves, False)
        for index, label in enumerate(self.step_labels):
            if index == self._step:
                state = "active"
            elif done[index]:
                state = "done"
            else:
                state = ""
            label.setProperty("state", state)
            self._repolish(label)

    def set_step(self, index: int) -> None:
        index = max(0, min(len(STEPS) - 1, int(index)))
        self._step = index
        self.stack.setCurrentIndex(index)
        self.step_counter.setText(f"第 {index + 1} / {len(STEPS)} 步")
        self.back_btn.setEnabled(index > 0)
        self.next_btn.setText("完成" if index == len(STEPS) - 1 else "下一步")
        self.next_btn.setAccessibleName("完成上手向导" if index == len(STEPS) - 1
                                        else "进入下一步")
        self._pages[index].setAccessibleName(f"第 {index + 1} 步：{STEPS[index]['heading']}")
        self._refresh_step_states()
        # 把焦点放在当前步骤的主操作上，键盘用户不用猜从哪里开始。
        self._action_buttons[index].setFocus(Qt.OtherFocusReason)

    def set_busy(self, busy: bool, text: str = "") -> None:
        self._busy = bool(busy)
        for button in self._action_buttons:
            button.setEnabled(not self._busy)
        if text:
            self._status_labels[self._step].setText(text)

    # ------------------------------------------------------------ 动作

    def _detect(self) -> None:
        if self._busy:
            return
        self.set_busy(True, "正在自动检测游戏与存档目录…")
        self.detectRequested.emit()

    def _navigate(self, target: str) -> None:
        self.navigateRequested.emit(str(target))
        self.accept()

    def _next(self) -> None:
        if self._step < len(STEPS) - 1:
            self.set_step(self._step + 1)
            return
        self.completed.emit()
        self.accept()

    def _skip(self) -> None:
        self.skipped.emit()
        self.accept()

    def reject(self) -> None:
        super().reject()
        self.skipped.emit()

    @staticmethod
    def _repolish(widget) -> None:
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)
        widget.update()


__all__ = ["STEPS", "RfOnboardingWizard"]
