"""「送进游戏」共用按钮：选中一条 ShipRef → 写进游戏模板槽 → 去表情菜单领取。

`ship_lab`（搜索结果）和 `fleet`（我的船队）结构不同，但动作完全一样：
  · 只在当前船型有模板槽时可用；
  · 点击先弹二次确认（只写 8 字节种子，不改存档），确认后把字典连同
    `confirm=True` 交给 `services.live_push_ship`，在后台线程里完成；
  · 成功提示"已写入「星铸 · X」模板，去游戏表情菜单选它领取"；
  · 失败原样显示服务返回的错误（游戏未运行 / 模板缺失 / 定位或回读失败）。
后台调用照抄页面里已有的 ``run_worker`` 用法，worker 里不碰 QWidget。
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMessageBox, QPushButton

from ...live import exml
from ...services import Services, get_services
from .. import notify
from .worker import run as run_worker


def template_label(type_: str) -> str:
    """该船型对应的表情中文标题；没有模板槽时返回空串。"""
    return (exml.TITLE_TEXT.get(str(type_ or "")) or ("",))[0]


def has_template(type_: str) -> bool:
    """这个船型是否在模板 Mod 的清单里（只影响按钮可用性，不代表 Mod 已装）。"""
    return bool(template_label(type_))


def success_text(res: dict) -> str:
    """成功提示：明确告诉玩家去表情菜单选哪个表情。"""
    emote = str(res.get("emote") or "")
    if emote:
        return f"已写入「{emote}」模板，去游戏表情菜单选它领取"
    return "已写入游戏模板，去表情菜单选对应表情领取"


class GamePushButton(QPushButton):
    """把当前选中飞船的种子写进模板槽。

    ``set_ship(ref)`` 由页面在选中变化时调用；传 ``None`` 表示没有选中。
    成功结果通过 ``pushed`` 信号广播给页面（可选，用于状态栏文案）。
    """

    pushed = Signal(dict)

    def __init__(self, svc: Services | None = None, parent=None):
        super().__init__("送进游戏", parent)
        self.svc = svc or get_services()
        self._ref: dict | None = None
        self._busy = False
        self.setAccessibleName("送进游戏")
        self.clicked.connect(self._start)
        self._sync()

    # ---------------------------------------------------------------- 状态

    def set_ship(self, ref: dict | None) -> None:
        self._ref = dict(ref) if isinstance(ref, dict) else None
        self._sync()

    def _sync(self) -> None:
        ref = self._ref or {}
        type_ = str(ref.get("type") or "")
        label = template_label(type_)
        self.setEnabled(bool(ref) and bool(label) and not self._busy)
        self.setText("写入中…" if self._busy else "送进游戏")
        if not ref:
            tip = "先在结果或船队里选中一艘飞船"
        elif not label:
            tip = "该船型没有模板槽：先在游戏内页安装模板 Mod 并重启游戏"
        else:
            tip = (f"把当前种子写进「{label}」模板槽；只改模板种子，不动你的存档。"
                   "写入后去游戏表情菜单选它领取")
        self.setToolTip(tip)
        self.setAccessibleDescription(tip)

    # ---------------------------------------------------------------- 动作

    def _start(self) -> None:
        ref = dict(self._ref or {})
        if not ref:
            notify.warn("先选中一艘飞船")
            return
        label = template_label(str(ref.get("type") or ""))
        if not label:
            notify.warn("先在游戏内页安装模板 Mod 并重启游戏")
            return
        answer = QMessageBox.question(
            self, "送进游戏",
            f"把当前种子写进「{label}」模板槽？\n\n"
            "只写 8 字节种子，不改存档；游戏必须正在运行。\n"
            "写入后去表情菜单选对应模板领取。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._busy = True
        self._sync()

        def done(res: dict) -> None:
            self._busy = False
            self._sync()
            if not res.get("ok", True):
                notify.error(str(res.get("error") or "送进游戏失败"))
                return
            notify.success(success_text(res))
            self.pushed.emit(res)

        def fail(msg: str) -> None:
            self._busy = False
            self._sync()
            notify.error(f"送进游戏失败：{msg}")

        run_worker(self.svc.live_push_ship, done, fail, ref, confirm=True)
