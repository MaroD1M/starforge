"""进程选择回归：同名 NMS.exe 里跳过无路径的僵尸，优先真实 Binaries\\NMS.exe。

不启动游戏，也不调用真实的 Toolhelp/OpenProcess：只替换 iter_pids 与路径查询。
"""
from __future__ import annotations

from starforge.live import mem


def _patch_processes(monkeypatch, paths: dict[int, str]):
    monkeypatch.setattr(mem, "IS_WINDOWS", True)
    monkeypatch.setattr(mem, "iter_pids", lambda name="NMS.exe": iter(paths))
    monkeypatch.setattr(mem, "_process_image_path", lambda pid: paths.get(int(pid), ""))


def test_find_pid_skips_process_without_executable_path(monkeypatch):
    # 111 是游戏崩溃后留下的僵尸（ExecutablePath 为空），222 才是真实游戏。
    _patch_processes(monkeypatch, {
        111: "",
        222: r"D:\Steam\steamapps\common\No Man's Sky\Binaries\NMS.exe",
        333: r"C:\Tools\NMS.exe",
    })
    assert mem.find_pid("NMS.exe") == 222


def test_find_pid_prefers_binaries_exe_over_other_same_name(monkeypatch):
    _patch_processes(monkeypatch, {
        111: r"C:\Other\NMS.exe",
        222: r"D:\Steam\No Man's Sky\Binaries\NMS.exe",
    })
    assert mem.find_pid("NMS.exe") == 222
    assert mem.find_pid("NMS.exe", require_exe=True) == 222


def test_find_pid_require_exe_rejects_non_game_path(monkeypatch):
    _patch_processes(monkeypatch, {111: r"C:\Other\NMS.exe"})
    assert mem.find_pid("NMS.exe") == 111
    assert mem.find_pid("NMS.exe", require_exe=True) is None


def test_find_pid_returns_none_when_all_are_zombies(monkeypatch):
    _patch_processes(monkeypatch, {111: "", 222: ""})
    assert mem.find_pid("NMS.exe") is None


def test_find_pid_require_window_skips_windowless_child(monkeypatch):
    from starforge.live import mem

    monkeypatch.setattr(mem, "iter_pids", lambda _name="NMS.exe": iter([1, 2]))
    monkeypatch.setattr(
        mem, "_process_image_path",
        lambda pid: "C:/Games/No Man's Sky/Binaries/NMS.exe")
    monkeypatch.setattr(mem, "_has_main_window", lambda pid: pid == 2)
    assert mem.find_pid(require_exe=True, require_window=True) == 2
    monkeypatch.setattr(mem, "_has_main_window", lambda pid: False)
    assert mem.find_pid(require_exe=True, require_window=True) is None
