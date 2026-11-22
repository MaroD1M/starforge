"""底部任务/日志 Dock：显示 services.jobs() 里的任务，可折叠、可取消。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from ...services import get_services
from ..theme import DOCK_BUTTON_HEIGHT, SPACE_M, SPACE_S
from .ui import ElidedLabel
from .worker import run as run_worker

STATUS_LABELS = {
    "running": "进行中",
    "done": "完成",
    "failed": "失败",
    "cancelled": "取消",
}
TERMINAL_STATUSES = frozenset({"done", "failed", "cancelled"})


def status_label(status) -> str:
    """把任务状态转成用户能直接读懂的中文。"""
    return STATUS_LABELS.get(str(status or ""), "未知")


def is_running(job: dict | None) -> bool:
    return bool(job) and job.get("status") == "running"


def format_rate(rate) -> str:
    """速率统一按“个数/秒”换算，避免中文界面里夹 M/s。"""
    try:
        value = float(rate)
    except (TypeError, ValueError):
        return f"{rate} 个/秒"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f} 百万/秒"
    if value >= 1_000:
        return f"{value / 1_000:.1f} 千/秒"
    return f"{value:.0f} 个/秒"


def format_eta(seconds) -> str:
    """把秒数格式化成中文剩余时间。"""
    try:
        value = max(0, round(float(seconds)))
    except (TypeError, ValueError):
        return f"剩余 {seconds}"
    if value < 60:
        return f"剩余 {value} 秒"
    minutes, sec = divmod(value, 60)
    if minutes < 60:
        return f"剩余 {minutes} 分 {sec:02d} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"剩余 {hours} 小时 {minutes:02d} 分"


def error_summary(error, limit: int = 80) -> str:
    """错误可能很长；Dock 只展示第一行摘要，完整内容放在 tooltip。"""
    text = " ".join(str(error or "").split())
    if not text:
        return "未知错误"
    if len(text) > limit:
        return text[: max(0, limit - 1)] + "…"
    return text


def format_job_row(job: dict) -> str:
    """一行任务摘要：类型 · 状态 · 计数 · 速率 · 命中 · 剩余 · 错误。"""
    kind = str(job.get("kind") or "任务")
    status = job.get("status")
    progress = job.get("progress") or {}
    bits = [kind, status_label(status)]

    tested = progress.get("tested")
    if tested is not None:
        try:
            count = int(tested)
            limit = progress.get("max_seeds")
            if limit:
                bits.append(f"已测 {count:,}/{int(limit):,} 个种子")
            else:
                bits.append(f"已测 {count:,} 个种子")
        except (TypeError, ValueError):
            bits.append(f"已测 {tested} 个种子")

    if progress.get("rate"):
        bits.append(format_rate(progress["rate"]))

    if progress.get("found") is not None:
        bits.append(f"命中 {progress['found']}")

    if status == "running" and progress.get("eta"):
        bits.append(format_eta(progress["eta"]))

    if status == "failed":
        bits.append(f"错误：{error_summary(job.get('error'))}")

    return "  ·  ".join(bits)


def summarize_jobs(jobs: list[dict]) -> str:
    running = sum(1 for job in jobs if is_running(job))
    finished = sum(1 for job in jobs if job.get("status") in TERMINAL_STATUSES)
    failed = sum(1 for job in jobs if job.get("status") == "failed")
    if running:
        text = f"{running} 个进行中"
        if finished:
            text += f" · {finished} 个已结束"
        return text
    if jobs:
        text = f"{len(jobs)} 个已结束"
        if failed:
            text += f" · {failed} 个失败"
        return text
    return "空闲"


class JobDock(QFrame):
    MAX_ROWS = 8

    def __init__(self, parent=None, svc=None):
        super().__init__(parent)
        self.svc = svc or get_services()
        self._jobs: list[dict] = []
        self._hidden: set[str] = set()
        self._refresh_busy = False
        self._auto_active: bool | None = None
        self.setObjectName("jobDock")
        self._build_ui()
        self._set_list_visible(False)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(SPACE_M, SPACE_S, SPACE_M, SPACE_S)
        v.setSpacing(SPACE_S)
        head = QHBoxLayout()
        head.setSpacing(SPACE_S)
        title = QLabel("任务")
        title.setObjectName("muted")
        head.addWidget(title)
        # 摘要可能因错误信息变长：用省略号，保证右侧按钮始终可见。
        self.summary = ElidedLabel("空闲")
        self.summary.setObjectName("muted")
        self.summary.setMinimumWidth(80)
        self.summary.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        head.addWidget(self.summary, 1)

        self.cancel_btn = QPushButton("取消进行中")
        self.cancel_btn.setObjectName("dockButton")
        self.cancel_btn.setMinimumHeight(DOCK_BUTTON_HEIGHT)
        self.cancel_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.cancel_btn.setToolTip("取消当前选中的进行中任务")
        self.cancel_btn.clicked.connect(self.cancel_selected)
        head.addWidget(self.cancel_btn)

        self.clear_btn = QPushButton("清空已完成")
        self.clear_btn.setObjectName("dockButton")
        self.clear_btn.setMinimumHeight(DOCK_BUTTON_HEIGHT)
        self.clear_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.clear_btn.setToolTip("只从任务栏隐藏已结束任务，不删除服务端记录")
        self.clear_btn.clicked.connect(self.clear_finished)
        head.addWidget(self.clear_btn)

        self.toggle = QPushButton("展开")
        self.toggle.setObjectName("dockButton")
        self.toggle.setMinimumHeight(DOCK_BUTTON_HEIGHT)
        self.toggle.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.toggle.clicked.connect(self.toggle_body)
        head.addWidget(self.toggle)
        v.addLayout(head)

        self.list = QListWidget()
        self.list.setMaximumHeight(110)
        self.list.setMinimumHeight(70)
        self.list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.list.setTextElideMode(Qt.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.itemSelectionChanged.connect(self._update_actions)
        v.addWidget(self.list)
        self._update_actions()

    # ------------------------------------------------------------ 展开/收起

    def _set_list_visible(self, visible: bool) -> None:
        self.list.setVisible(bool(visible))
        self.toggle.setText("收起" if visible else "展开")

    def toggle_body(self) -> None:
        """保留用户手动展开/收起；直到任务列表有无发生变化再交还自动逻辑。"""
        self._set_list_visible(self.list.isHidden())

    def _apply_auto_visibility(self, active: bool) -> None:
        if self._auto_active is None or active != self._auto_active:
            self._auto_active = active
            self._set_list_visible(active)

    # ------------------------------------------------------------ 取消/清空

    def _selected_job(self) -> dict | None:
        item = self.list.currentItem()
        if item is None:
            return None
        job_id = item.data(Qt.UserRole)
        for job in self._jobs:
            if str(job.get("id")) == str(job_id):
                return job
        return None

    def selected_job_id(self) -> str | None:
        job = self._selected_job()
        return str(job.get("id")) if job else None

    def _update_actions(self) -> None:
        job = self._selected_job()
        self.cancel_btn.setEnabled(bool(job) and is_running(job))
        visible_ids = {str(j.get("id")) for j in self._jobs if str(j.get("id")) not in self._hidden}
        self.clear_btn.setEnabled(any(
            j.get("status") in TERMINAL_STATUSES and str(j.get("id")) in visible_ids
            for j in self._jobs
        ))

    def cancel_selected(self) -> bool:
        job = self._selected_job()
        if job is None:
            self.summary.setText("请先选择一个任务")
            return False
        if not is_running(job):
            self.summary.setText("只能取消进行中的任务")
            return False
        try:
            self.svc.cancel_job(str(job.get("id")))
        except Exception as e:                              # noqa: BLE001 - UI 必须给出中文提示
            self.summary.setText(f"取消失败：{type(e).__name__}: {e}")
            return False
        self.summary.setText("已请求取消任务")
        self.refresh()
        return True

    def clear_finished(self) -> int:
        """只隐藏 Dock 中的已结束任务；不动 REGISTRY / 服务端记录。"""
        finished = [
            j for j in self._jobs
            if j.get("status") in TERMINAL_STATUSES and str(j.get("id")) not in self._hidden
        ]
        if not finished:
            self.summary.setText("没有可清空的已完成任务")
            return 0
        self._hidden.update(str(j.get("id")) for j in finished)
        self._apply_jobs(self._jobs)
        self.summary.setText(f"已隐藏 {len(finished)} 个已结束任务")
        return len(finished)

    # ------------------------------------------------------------ 刷新

    def refresh(self) -> None:
        """后台读取任务，UI 线程只负责应用结果。"""
        if self._refresh_busy:
            return
        self._refresh_busy = True
        run_worker(self._fetch_jobs, self._on_jobs_ready, self._on_refresh_error)

    def _fetch_jobs(self) -> list[dict]:
        return self.svc.jobs().get("jobs") or []

    def _on_jobs_ready(self, jobs) -> None:
        self._refresh_busy = False
        self._apply_jobs(jobs or [])

    def _on_refresh_error(self, message: str) -> None:
        self._refresh_busy = False
        self.summary.setText(f"任务读取失败：{message}")

    def _apply_jobs(self, jobs) -> None:
        self._jobs = [j for j in (jobs or []) if isinstance(j, dict)]
        live_ids = {str(j.get("id")) for j in self._jobs if j.get("id") is not None}
        self._hidden.intersection_update(live_ids)
        visible = [j for j in self._jobs if str(j.get("id")) not in self._hidden]
        shown = visible[: self.MAX_ROWS]

        selected = self.selected_job_id()
        self.list.blockSignals(True)
        self.list.clear()
        for job in shown:
            item = QListWidgetItem(format_job_row(job))
            item.setData(Qt.UserRole, job.get("id"))
            tip = format_job_row(job)
            if job.get("error"):
                tip += f"\n{job['error']}"
            item.setToolTip(tip)
            self.list.addItem(item)
            if selected is not None and str(job.get("id")) == selected:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)

        self.summary.setText(summarize_jobs(visible))
        self._update_actions()
        self._apply_auto_visibility(bool(visible))
