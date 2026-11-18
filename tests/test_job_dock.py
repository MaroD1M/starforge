"""JobDock 纯逻辑 + 离屏冒烟测试（不依赖真实游戏/服务）。"""
from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

from starforge.app.widgets.job_dock import (
    JobDock,
    error_summary,
    format_eta,
    format_job_row,
    format_rate,
    status_label,
    summarize_jobs,
)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def _job(job_id: str, status: str = "running", **progress) -> dict:
    return {
        "id": job_id,
        "kind": "search",
        "status": status,
        "created": 0,
        "finished": None,
        "progress": progress,
        "error": "",
    }


class FakeServices:
    def __init__(self, jobs: list[dict]):
        self._jobs = [dict(job) for job in jobs]
        self.cancelled: list[str] = []

    def jobs(self) -> dict:
        return {"ok": True, "jobs": self._jobs}

    def cancel_job(self, job_id: str) -> dict:
        self.cancelled.append(job_id)
        for job in self._jobs:
            if job["id"] == job_id:
                job["status"] = "cancelled"
        return {"ok": True}


def _dock(qapp, svc) -> JobDock:
    dock = JobDock(svc=svc)
    dock._timer.stop()
    return dock


# ---------------------------------------------------------------- 纯逻辑


def test_status_and_formats_are_chinese():
    assert status_label("running") == "进行中"
    assert status_label("done") == "完成"
    assert status_label("failed") == "失败"
    assert status_label("cancelled") == "取消"
    assert format_rate(1_500_000) == "1.5 百万/秒"
    assert format_rate(2_000) == "2.0 千/秒"
    assert format_rate(500) == "500 个/秒"
    assert format_eta(12) == "剩余 12 秒"
    assert format_eta(65) == "剩余 1 分 05 秒"
    assert format_eta(3665) == "剩余 1 小时 01 分"


def test_format_job_row_shows_progress_and_error_summary():
    running = _job("r1", "running", tested=1500, max_seeds=10000, rate=500,
                   eta=17, found=2)
    text = format_job_row(running)
    assert "进行中" in text
    assert "已测 1,500/10,000 个种子" in text
    assert "500 个/秒" in text
    assert "命中 2" in text
    assert "剩余 17 秒" in text

    failed = _job("f1", "failed")
    failed["error"] = "RuntimeError: kaboom"
    text = format_job_row(failed)
    assert "失败" in text
    assert "错误：RuntimeError: kaboom" in text
    assert error_summary("x" * 200).endswith("…")


def test_summarize_jobs_uses_chinese():
    assert summarize_jobs([]) == "空闲"
    assert summarize_jobs([_job("d1", "done")]) == "1 个已结束"
    summary = summarize_jobs([_job("r1"), _job("d1", "done")])
    assert "1 个进行中" in summary and "1 个已结束" in summary
    assert "1 个失败" in summarize_jobs([_job("f1", "failed")])


# ---------------------------------------------------------------- 离屏冒烟


def test_dock_auto_collapses_when_idle_and_expands_when_running(qapp):
    dock = _dock(qapp, FakeServices([]))
    try:
        dock._apply_jobs([])
        assert dock.list.isHidden()
        assert dock.summary.text() == "空闲"

        dock._apply_jobs([_job("r1", "running", tested=3, rate=10, eta=30)])
        assert not dock.list.isHidden()
        assert dock.list.count() == 1
        assert "进行中" in dock.list.item(0).text()

        dock._apply_jobs([_job("d1", "done")])
        assert not dock.list.isHidden()      # 已结束任务保留到清空为止
        assert "完成" in dock.list.item(0).text()
        dock.clear_finished()
        assert dock.list.isHidden()
    finally:
        dock.close()


def test_manual_toggle_survives_refresh_until_activity_changes(qapp):
    running = _job("r1", "running")
    dock = _dock(qapp, FakeServices([running]))
    try:
        dock._apply_jobs([running])
        assert not dock.list.isHidden()

        dock.toggle_body()
        assert dock.list.isHidden()
        dock._apply_jobs([running])
        assert dock.list.isHidden()

        dock._apply_jobs([])
        dock._apply_jobs([running])
        assert not dock.list.isHidden()
    finally:
        dock.close()


def test_clear_finished_only_hides_terminal_jobs(qapp):
    svc = FakeServices([
        _job("r1", "running"),
        _job("d1", "done"),
        _job("f1", "failed"),
        _job("c1", "cancelled"),
    ])
    dock = _dock(qapp, svc)
    try:
        dock._apply_jobs(svc.jobs()["jobs"])
        assert dock.list.count() == 4

        assert dock.clear_finished() == 3
        assert dock.list.count() == 1
        assert dock.list.item(0).data(Qt.UserRole) == "r1"
        assert len(svc._jobs) == 4          # 服务端记录原样保留
        assert dock._hidden == {"d1", "f1", "c1"}
        assert dock.clear_finished() == 0   # 已隐藏的不重复计数
    finally:
        dock.close()


def test_cancel_selected_calls_services(qapp, monkeypatch):
    svc = FakeServices([_job("r1", "running")])
    dock = _dock(qapp, svc)
    monkeypatch.setattr(dock, "refresh", lambda: None)
    try:
        dock._apply_jobs(svc.jobs()["jobs"])
        dock.list.setCurrentRow(0)
        assert dock.cancel_btn.isEnabled()
        assert dock.cancel_selected() is True
        assert svc.cancelled == ["r1"]
        assert "已请求取消" in dock.summary.text()
    finally:
        dock.close()


def test_cancel_failure_shows_chinese_message(qapp):
    class BadServices(FakeServices):
        def cancel_job(self, job_id: str) -> dict:
            raise RuntimeError("服务不可用")

    dock = _dock(qapp, BadServices([_job("r1", "running")]))
    try:
        dock._apply_jobs(dock.svc.jobs()["jobs"])
        dock.list.setCurrentRow(0)
        assert dock.cancel_selected() is False
        assert "取消失败" in dock.summary.text()
        assert "服务不可用" in dock.summary.text()
    finally:
        dock.close()


def test_refresh_runs_in_background_and_applies_jobs(qapp):
    svc = FakeServices([_job("r1", "running", tested=1, rate=2, eta=3)])
    dock = _dock(qapp, svc)
    try:
        dock.refresh()
        deadline = time.time() + 2
        while time.time() < deadline and dock.list.count() == 0:
            qapp.processEvents()
            time.sleep(0.01)
        assert dock.list.count() == 1
        assert "进行中" in dock.list.item(0).text()
        assert not dock._refresh_busy
    finally:
        dock.close()


def test_refresh_error_is_reported_in_chinese(qapp):
    dock = _dock(qapp, FakeServices([]))
    try:
        dock._on_refresh_error("RuntimeError: boom")
        assert "任务读取失败" in dock.summary.text()
    finally:
        dock.close()
