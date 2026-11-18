"""应用级上下文：原生壳、页面与服务之间的统一交互通道。

页面只依赖这个上下文，不直接互相引用；壳层负责把信号接到实际控件上。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..services import Services, get_services


class AppContext(QObject):
    """持有服务实例，并提供一组稳定的跨页面信号。"""

    healthChanged = Signal(dict)
    jobChanged = Signal(dict)
    agentChanged = Signal(dict)
    navigateRequested = Signal(str)
    toastRequested = Signal(str)

    def __init__(self, services: Services | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self.services = services or get_services()

    @property
    def svc(self) -> Services:
        """兼容壳层现有的 ``self.svc`` 命名。"""
        return self.services

    def publish_health(self, health: dict | None) -> None:
        self.healthChanged.emit(dict(health or {}))

    def publish_job(self, job: dict | None) -> None:
        self.jobChanged.emit(dict(job or {}))

    def publish_agent(self, agent: dict | None) -> None:
        self.agentChanged.emit(dict(agent or {}))

    def toast(self, text: str) -> None:
        text = str(text or "").strip()
        if text:
            self.toastRequested.emit(text)

    def navigate(self, page: str) -> None:
        page = str(page or "").strip()
        if page:
            self.navigateRequested.emit(page)
