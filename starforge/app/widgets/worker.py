"""把同步服务调用丢到线程池，UI 只收信号。

约束：worker 里**不能**碰 QWidget；返回值必须是纯数据（dict/list/bytes/str）。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ...core import log

_log = log.get("ui.worker")


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(object)


class Worker(QRunnable):
    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        # autoDelete=True 时 C++ 对象会在 run() 返回后立刻销毁，信号源可能先于
        # emit 被删（Qt 报 "Signal source has been deleted"）。这里自己管生命周期。
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as e:                              # noqa: BLE001 - 统一转成 UI 可读文本
            msg = f"{type(e).__name__}: {e}"
            _log.warning("后台任务失败：%s", msg)
            try:
                self.signals.failed.emit(msg)
            except RuntimeError:
                pass
            return
        try:
            self.signals.finished.emit(result)
        except RuntimeError:
            pass


_ACTIVE: set[Worker] = set()


def run(fn: Callable[..., Any], on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        *args: Any, **kwargs: Any) -> Worker:
    """提交后台任务；返回 Worker（调用方可选持有，防止被回收）。"""
    w = Worker(fn, *args, **kwargs)
    _ACTIVE.add(w)

    def _cleanup(*_args: Any) -> None:
        _ACTIVE.discard(w)

    w.signals.finished.connect(_cleanup)
    w.signals.failed.connect(_cleanup)
    if on_done is not None:
        w.signals.finished.connect(on_done)
    if on_error is not None:
        w.signals.failed.connect(on_error)
    QThreadPool.globalInstance().start(w)
    return w
