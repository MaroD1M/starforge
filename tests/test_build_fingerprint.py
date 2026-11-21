"""build 指纹的回归测试：PE 版本资源解析 + 内存区域枚举上限。

这些用例离线可跑（不碰正在运行的游戏进程）：
  · 版本资源用假 pefile 结构覆盖三种形态（字符串 / 只有 VS_FIXEDFILEINFO / 无资源）；
  · 真实 NMS.exe 存在时额外验证一次（只读文件，不读游戏内存）。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from starforge.live import build, mem


# ---------------------------------------------------------------- 假 pefile 结构


def _fake_pe(string_entries=None, fixed=()) -> SimpleNamespace:
    """拼一个和 pefile 解析结果同形的对象：FileInfo[group][entry].StringTable。"""
    groups = []
    if string_entries is not None:
        table = SimpleNamespace(LangID=b"080904B0", entries=string_entries)
        groups.append([SimpleNamespace(StringTable=[table])])
    groups.append([SimpleNamespace(VarFileInfo=[])])
    return SimpleNamespace(FileInfo=groups, VS_FIXEDFILEINFO=list(fixed))


def _fixed(ms: int, ls: int) -> SimpleNamespace:
    return SimpleNamespace(FileVersionMS=ms, FileVersionLS=ls)


# ---------------------------------------------------------------- 版本资源解析


def test_string_file_version_prefers_file_version():
    pe = _fake_pe({b"FileVersion": b"185034", b"ProductVersion": b"999"})
    assert build._string_file_version(pe) == "185034"


def test_string_file_version_falls_back_to_product_version():
    pe = _fake_pe({b"ProductVersion": b"123456"})
    assert build._string_file_version(pe) == "123456"


def test_string_file_version_decodes_utf16_values():
    pe = _fake_pe({b"FileVersion": "185034".encode("utf-16-le")})
    assert build._string_file_version(pe) == "185034"


def test_fixed_file_version_uses_pefile_field_names():
    """pefile 字段是 FileVersionMS/LS（没有 dw 前缀），旧实现写错导致永远取不到。"""
    pe = _fake_pe({b"FileVersion": b"185034"}, fixed=[_fixed(0x00010002, 0x00030004)])
    assert build._fixed_file_version(pe) == "1.2.3.4"


def test_fixed_file_version_accepts_legacy_dw_prefix():
    item = SimpleNamespace(dwFileVersionMS=0x00050006, dwFileVersionLS=0x00070008)
    pe = _fake_pe(None, fixed=[item])
    assert build._fixed_file_version(pe) == "5.6.7.8"


def test_string_file_info_wins_over_fixed():
    """NMS 的 VS_FIXEDFILEINFO 是 0.53962.0.0，真实 build 号在字符串里。"""
    pe = _fake_pe({b"FileVersion": b"185034"}, fixed=[_fixed(0, 53962 << 16)])
    assert (build._string_file_version(pe) or build._fixed_file_version(pe)) == "185034"


def test_empty_fixed_version_is_ignored():
    pe = _fake_pe(None, fixed=[_fixed(0, 0)])
    assert build._fixed_file_version(pe) == ""


def test_file_version_survives_garbage_file(tmp_path):
    """不是 PE / 资源损坏时必须安静返回空串，绝不能让 build 识别抛异常。"""
    bad = tmp_path / "not_a_pe.exe"
    bad.write_bytes(b"MZ" + b"\x00" * 64)
    assert build._file_version(bad) == ""
    assert build._file_version(tmp_path / "missing.exe") == ""


# ---------------------------------------------------------------- summary 契约


def test_summary_includes_version_and_legacy_keys(monkeypatch):
    """summary() 要直接带 version，UI/CLI 不必再读 fingerprint。"""
    fp = {"path": "NMS.exe", "size": 123, "sha256": "AB" * 32,
          "version": "185034", "platform": "test"}
    monkeypatch.setattr(build, "lookup", lambda _fp=None: None)
    s = build.summary(fp)
    assert s["version"] == "185034"
    # 旧键必须保留（其它调用方/测试只读这些字段）
    for key in ("fingerprint", "build_id", "known", "status", "verified",
                "write_allowed", "reason"):
        assert key in s, key
    assert s["fingerprint"] is fp
    assert s["build_id"].startswith("185034-")
    assert s["write_allowed"] is False


def test_fingerprint_error_branch_has_version_key(tmp_path):
    fp = build.fingerprint(tmp_path / "missing.exe")
    assert fp["version"] == ""
    assert fp["error"]


def test_summary_error_branch_has_empty_version(monkeypatch):
    fp = {"error": "文件不存在", "version": ""}
    monkeypatch.setattr(build, "lookup", lambda _fp=None: None)
    s = build.summary(fp)
    assert s["version"] == ""
    assert "无法确认游戏 build" in s["reason"]


# ---------------------------------------------------------------- 真实 NMS.exe


def _nms_exe() -> Path | None:
    try:
        from starforge.core import settings

        game = settings.current().game_dir
    except Exception:                                    # noqa: BLE001
        game = None
    if not game:
        try:
            from starforge import locate_game

            game = locate_game.find()
        except Exception:                                # noqa: BLE001
            game = None
    if not game:
        return None
    p = Path(game) / "Binaries" / "NMS.exe"
    return p if p.exists() else None


_NMS = _nms_exe()


@pytest.mark.skipif(_NMS is None, reason="本机没有 NMS.exe（CI/离线环境）")
def test_real_nms_exe_has_string_build_version():
    ver = build._file_version(_NMS)
    assert ver, "NMS.exe 的 StringFileInfo 里应当有 FileVersion"
    assert all(ch.isdigit() or ch == "." for ch in ver), ver
    fp = build.fingerprint(_NMS)
    assert fp["version"] == ver
    assert build.build_id(fp).startswith(f"{ver}-")


@pytest.mark.skipif(_NMS is None, reason="本机没有 NMS.exe（CI/离线环境）")
def test_real_nms_build_id_matches_steam_build():
    """这台机器的 NMS.exe（sha 09223696...）build 号必须是 185034，不是 size-<sha>。"""
    fp = build.fingerprint(_NMS)
    if not (fp.get("sha256") or "").upper().startswith("092236962EE0"):
        pytest.skip("本机 NMS.exe 不是 185034 这版")
    assert build.build_id(fp).startswith("185034-")
    assert "size-" not in build.build_id(fp)


# ---------------------------------------------------------------- 区域枚举上限


def _many_images(n: int, size: int = 0x1000, base: int = 0x10000000):
    return [(base + i * size, bytearray(size)) for i in range(n)]


def test_regions_default_does_not_truncate_large_process():
    """旧默认 4096 会漏掉 NMS 实测的 4224 个区域；新默认必须一个不少。"""
    proc = mem.FakeProcess(_many_images(4224))
    rs = proc.regions()
    assert isinstance(rs, list) and len(rs) == 4224
    assert rs.truncated is False and rs.max_regions == mem.DEFAULT_MAX_REGIONS
    assert rs.scan_info() == {"regions_seen": 4224, "truncated": False,
                              "max_regions": mem.DEFAULT_MAX_REGIONS}
    assert proc._sf_region_scan == rs.scan_info()


def test_regions_marks_truncated_when_over_limit():
    proc = mem.FakeProcess(_many_images(12))
    rs = proc.regions(max_regions=5)
    assert len(rs) == 5 and rs.truncated is True
    assert rs.regions_seen == 5 and rs.max_regions == 5
    assert rs.scan_info()["truncated"] is True


def test_regions_filters_min_size():
    proc = mem.FakeProcess([(0x10000000, bytearray(0x800)),
                            (0x20000000, bytearray(0x1000))])
    rs = proc.regions(min_size=0x1000)
    assert [r.base for r in rs] == [0x20000000]


class _Mbi:
    """模拟 MEMORY_BASIC_INFORMATION，供 _collect_regions 的假 query 填写。"""

    def __init__(self):
        self.BaseAddress = 0
        self.RegionSize = 0x1000
        self.State = mem._MEM_COMMIT
        self.Protect = 0x04


def test_collect_regions_stops_at_limit_and_flags_truncation():
    """WinProcess 的收集逻辑：撞上限就停（不多查），并标记 truncated。"""
    calls: list[int] = []

    def query(addr: int, out: _Mbi) -> bool:
        calls.append(addr)
        i = len(calls) - 1
        if i >= 10:
            return False
        out.BaseAddress = 0x10000000 + i * 0x1000
        out.RegionSize = 0x1000
        out.State = mem._MEM_COMMIT
        out.Protect = 0x04
        return True

    regions, truncated = mem._collect_regions(query, _Mbi, min_size=0x1000, max_regions=4)
    assert len(regions) == 4 and truncated is True
    assert len(calls) == 5                    # 第 5 个匹配区域只用来判断"确实被截断"


def test_collect_regions_skips_unreadable_and_small():
    rows = [
        (0x10000000, 0x1000, mem._MEM_COMMIT, 0x01),     # PAGE_NOACCESS
        (0x20000000, 0x800, mem._MEM_COMMIT, 0x04),      # 太小
        (0x30000000, 0x2000, 0x10000, 0x04),             # 未提交（MEM_FREE）
        (0x40000000, 0x2000, mem._MEM_COMMIT, 0x04),     # 唯一有效
    ]

    def query(addr: int, out: _Mbi) -> bool:
        i = len(getattr(query, "calls", []))
        query.calls = getattr(query, "calls", []) + [addr]
        if i >= len(rows):
            return False
        out.BaseAddress, out.RegionSize, out.State, out.Protect = rows[i]
        return True

    regions, truncated = mem._collect_regions(query, _Mbi, min_size=0x1000,
                                              max_regions=mem.DEFAULT_MAX_REGIONS)
    assert [r.base for r in regions] == [0x40000000]
    assert truncated is False
