"""任务模型：一切长任务（搜索 / 扇扫 / 建模）都是 Job，可查进度、可取消。

设计要点（手册 §2.2）：
  · UI 立刻拿到 job_id，不被长任务阻塞；
  · progress 里同时给"已测种子数 / 用时 / ETA"，ETA 用实测速率算，不猜；
  · 取消是协作式的（should_stop 回调），worker 每批检查一次。
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Job:
    kind: str
    status: str = "running"                    # running | done | cancelled | failed
    created: float = field(default_factory=time.time)
    finished: float | None = None
    progress: dict = field(default_factory=dict)
    error: str = ""
    result: Any = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # --- 控制 ---
    def cancel(self) -> None:
        self._cancel.set()

    def should_stop(self) -> bool:
        return self._cancel.is_set()

    # --- 进度 ---
    def update(self, **kw) -> None:
        with self._lock:
            self.progress.update(kw)
            tested = self.progress.get("tested") or 0
            seconds = self.progress.get("seconds") or 0
            if tested and seconds > 1:
                rate = tested / seconds
                limit = self.progress.get("max_seeds") or 0
                if limit and rate > 0:
                    self.progress["eta"] = max(0.0, (limit - tested) / rate)
                self.progress["rate"] = rate

    def finish(self, result=None, error: str = "") -> None:
        self.status = "failed" if error else ("cancelled" if self.should_stop() else "done")
        self.error = error
        self.result = result
        self.finished = time.time()

    def to_dict(self, include_result: bool = True) -> dict:
        d = {"id": self.id, "kind": self.kind, "status": self.status,
             "created": self.created, "finished": self.finished,
             "progress": dict(self.progress), "error": self.error}
        if include_result:
            d["result"] = self.result
        return d


class JobRegistry:
    """进程内任务表。上限保护：只保留最近 64 个，避免长跑占内存。"""

    def __init__(self, keep: int = 64):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._keep = keep

    def create(self, kind: str) -> Job:
        job = Job(kind=kind)
        with self._lock:
            self._jobs[job.id] = job
            if len(self._jobs) > self._keep:
                for old in sorted(self._jobs.values(), key=lambda j: j.created)[: len(self._jobs) - self._keep]:
                    if old.status != "running":
                        self._jobs.pop(old.id, None)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: -j.created)


def run_in_thread(job: Job, fn: Callable[[Job], Any]) -> Job:
    """把 fn(job) 丢到后台线程；异常写进 job.error，不让线程静默死掉。"""
    def _run() -> None:
        try:
            result = fn(job)
            job.finish(result=result)
        except Exception as e:                      # noqa: BLE001 - 要兜住所有，否则线程静默
            job.finish(error=f"{type(e).__name__}: {e}")
    threading.Thread(target=_run, daemon=True, name=f"job-{job.kind}-{job.id}").start()
    return job


REGISTRY = JobRegistry()
