"""进程内存读写（平台层）。

设计原则：
  · **只做"找模板槽 + 写 8 字节种子"这一件事**，不提供任何"改玩家/坐标/物品"的接口；
  · 通过 `Process` 抽象隔离平台，测试用 FakeProcess 注入合成内存，不需要真游戏；
  · 任何平台不支持或权限不足，都抛 `LiveUnsupported` 并给中文原因，绝不静默。

Windows 实现：ctypes + kernel32（OpenProcess / ReadProcessMemory / WriteProcessMemory /
VirtualQueryEx / CreateToolhelp32Snapshot / GetModuleInformation）。
"""
from __future__ import annotations

import os
import struct
import sys
from dataclasses import dataclass

from ..core import log

IS_WINDOWS = sys.platform.startswith("win")
log = log.get("live.mem")

# 单次内存枚举最多收集多少个可读区域。
# 实测 NMS.exe（游戏运行中）有 4224 个 ≥4KiB 的可读区域，旧的 4096 会静默漏掉末尾
# 约 30 MiB（首个漏掉的是 0x7FFA583E1000）。这里放大到 65536，常见游戏都不会被截断；
# 仍然保留上限，避免异常进程（区域数量失控）把内存吃光。真的撞到上限时，
# ``regions()`` 返回的 RegionList.truncated 会变成 True 并写一条 warning 日志。
DEFAULT_MAX_REGIONS = 65536

# 并行扫描的默认线程数上限。瓶颈是 ReadProcessMemory 的拷贝带宽，
# 超过 CPU 核数只会增加调度开销；显式传参会覆盖，但默认永远有上限。
MAX_SCAN_WORKERS = 8

_MEM_COMMIT = 0x1000
# READONLY / READWRITE / WRITECOPY / EXECUTE_READ / EXECUTE_READWRITE / EXECUTE_WRITECOPY
_PAGE_READABLE = (0x02, 0x04, 0x20, 0x40, 0x80)


def default_workers(limit: int = MAX_SCAN_WORKERS) -> int:
    """单次内存扫描的默认线程数：``min(limit, CPU 核数)``，至少 1。

    不按区域数量无上限建线程：扫描是读取带宽瓶颈，线程数超过核数只会增加切换开销。
    """
    return max(1, min(int(limit), os.cpu_count() or 1))


class LiveUnsupported(RuntimeError):
    """当前平台/环境不支持实时通道（例如 Linux、无权限、游戏未运行）。"""


@dataclass
class Region:
    base: int
    size: int
    protect: int

    def __contains__(self, addr: int) -> bool:
        return self.base <= addr < self.base + self.size


class RegionList(list):
    """``regions()`` 的返回列表。

    仍然是 ``list``（旧调用方直接迭代即可，无需改动），额外带上本次枚举的统计，
    让调用方 / probe 报告能看出"扫描是否完整"：

    · ``truncated``：撞到 ``max_regions`` 上限，后面还有可读区域没收集；
    · ``max_regions``：本次使用的上限；
    · ``regions_seen``：实际收集到的区域数（截断时等于上限）。
    """

    def __init__(self, regions=(), *, max_regions: int = 0, truncated: bool = False):
        super().__init__(regions)
        self.max_regions = int(max_regions)
        self.truncated = bool(truncated)

    @property
    def regions_seen(self) -> int:
        return len(self)

    def scan_info(self) -> dict:
        """可 JSON 序列化的扫描统计，便于塞进 probe/诊断输出。"""
        return {"regions_seen": len(self), "truncated": self.truncated,
                "max_regions": self.max_regions}


class Process:
    """一个目标进程的只读/限写句柄。写只用 write_at，且调用方负责校验。

    ``read`` 必须是纯只读且能被多个线程并发调用（Windows 的 ReadProcessMemory
    本身线程安全）；扫描产生的缓存回写由调用方在主线程完成，不在 worker 里改状态。
    """

    name: str = ""

    def read(self, addr: int, size: int) -> bytes:
        raise NotImplementedError

    def write_at(self, addr: int, data: bytes) -> bool:
        raise NotImplementedError

    def regions(self, min_size: int = 0x1000,
                max_regions: int = DEFAULT_MAX_REGIONS) -> RegionList:
        raise NotImplementedError

    def _wrap_regions(self, regions: list[Region], max_regions: int,
                      truncated: bool) -> RegionList:
        """统一封装：返回 RegionList，并把统计挂到进程对象 + 截断时告警。"""
        out = RegionList(regions, max_regions=max_regions, truncated=truncated)
        info = out.scan_info()
        try:
            setattr(self, "_sf_region_scan", info)        # 供 probe/诊断读取
        except Exception:                                 # noqa: BLE001
            pass
        if truncated:
            log.warning("内存区域枚举达到上限 %d，扫描不完整（truncated=True，"
                        "可能有模板槽落在未收集的区域里）", max_regions)
        return out

    def read_u64(self, addr: int) -> int:
        return struct.unpack("<Q", self.read(addr, 8))[0]

    def write_u64(self, addr: int, value: int) -> bool:
        return self.write_at(addr, struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF))

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


# ---------------------------------------------------------------- Windows


def _collect_regions(query, make_mbi, *, min_size: int,
                     max_regions: int) -> tuple[list[Region], bool]:
    """按 VirtualQueryEx 的语义收集可读区域（纯逻辑，便于用假 query 覆盖上限行为）。

    ``query(addr, mbi)`` 填好 ``mbi`` 并返回 True；返回 False 表示枚举结束。
    ``make_mbi()`` 造一个带 ``BaseAddress``/``RegionSize``/``State``/``Protect`` 字段的
    可写对象（真实实现传 ctypes 结构体，测试里可以传简单的假对象）。

    返回 ``(regions, truncated)``：撞到 ``max_regions`` 时立刻停止收集并把
    ``truncated`` 置 True——宁可显式报告"扫描不完整"，也不无限增长列表。
    """
    out: list[Region] = []
    limit = max(0, int(max_regions))
    truncated = False
    addr = 0
    mbi = make_mbi()
    while True:
        if not query(addr, mbi):
            break
        base = int(mbi.BaseAddress or 0)
        size = int(mbi.RegionSize or 0)
        if size <= 0:                                    # 防御异常返回：避免原地打转
            break
        if mbi.State == _MEM_COMMIT and mbi.Protect in _PAGE_READABLE and size >= min_size:
            if len(out) >= limit:
                truncated = True
                break
            out.append(Region(base, size, int(mbi.Protect)))
        addr = base + size
        if addr <= 0:
            break
    return out, truncated


def _win():
    if not IS_WINDOWS:
        raise LiveUnsupported("实时通道目前只支持 Windows（Linux/Proton 下无法读写进程内存）")
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    return ctypes, wintypes, k32


class WinProcess(Process):
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010
    PROCESS_VM_WRITE = 0x0020
    PROCESS_VM_OPERATION = 0x0008
    MEM_COMMIT = _MEM_COMMIT
    PAGE_READABLE = _PAGE_READABLE                    # READONLY/READWRITE/WRITECOPY/EXECUTE_*

    def __init__(self, pid: int, name: str = "NMS.exe"):
        ctypes, wintypes, k32 = _win()
        self._c, self._w, self._k = ctypes, wintypes, k32
        self.pid, self.name = pid, name
        access = (self.PROCESS_QUERY_INFORMATION | self.PROCESS_VM_READ |
                  self.PROCESS_VM_WRITE | self.PROCESS_VM_OPERATION)
        self.h = k32.OpenProcess(access, False, pid)
        if not self.h:
            raise LiveUnsupported(
                f"打不开进程 {name}（PID {pid}）：请以管理员身份运行 starforge，或确认游戏已启动")
        self._k.ReadProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.LPVOID,
                                              ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        self._k.WriteProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCVOID,
                                               ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]

    def read(self, addr: int, size: int) -> bytes:
        buf = (self._c.c_ubyte * size)()
        got = self._c.c_size_t()
        if not self._k.ReadProcessMemory(self.h, self._c.c_void_p(addr), buf, size, self._c.byref(got)) \
                or got.value != size:
            raise LiveUnsupported(f"读取 0x{addr:X} 失败（{self._c.get_last_error()}）")
        return bytes(buf)

    def write_at(self, addr: int, data: bytes) -> bool:
        buf = (self._c.c_ubyte * len(data)).from_buffer_copy(data)
        put = self._c.c_size_t()
        ok = self._k.WriteProcessMemory(self.h, self._c.c_void_p(addr), buf, len(data), self._c.byref(put))
        return bool(ok) and put.value == len(data)

    def regions(self, min_size: int = 0x1000,
                max_regions: int = DEFAULT_MAX_REGIONS) -> RegionList:
        ctypes, wintypes, k32 = self._c, self._w, self._k

        class MBI(ctypes.Structure):
            _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                        ("AllocationProtect", wintypes.DWORD), ("RegionSize", ctypes.c_size_t),
                        ("State", wintypes.DWORD), ("Protect", wintypes.DWORD),
                        ("Type", wintypes.DWORD)]

        def _query(addr: int, mbi) -> bool:
            return bool(k32.VirtualQueryEx(self.h, ctypes.c_void_p(addr),
                                           ctypes.byref(mbi), ctypes.sizeof(mbi)))

        out, truncated = _collect_regions(_query, MBI, min_size=min_size,
                                          max_regions=max_regions)
        return self._wrap_regions(out, max_regions, truncated)

    def close(self) -> None:
        if getattr(self, "h", None):
            self._k.CloseHandle(self.h)
            self.h = None


def find_pid(name: str = "NMS.exe", *, require_exe: bool = False,
             require_window: bool = False) -> int | None:
    """按进程名找 PID（Windows），跳过已死/无路径的僵尸进程。

    同名进程可能不止一个：实测游戏崩溃后会留下 ``NMS.exe`` 子进程，但它的
    ``ExecutablePath`` 为空、打不开；旧的 find_pid 直接返回第一个匹配 PID，
    导致 agent 注入到僵尸进程并一直显示「未连接」。这里用
    ``OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`` + ``QueryFullProcessImageNameW``
    校验真实路径：无路径的跳过；优先返回 ``...\\Binaries\\NMS.exe``。

    ``require_exe=True`` 时只接受以 ``\\Binaries\\NMS.exe`` 结尾的进程（附加注入用）；
    ``require_window=True`` 时还要求有可见主窗口——Steam 启动瞬间会出现没有窗口的
    同名子进程，注入到它只会得到「0 hooks、代理不可达」。
    """
    if not IS_WINDOWS:
        return None
    fallback: int | None = None
    exe_pid: int | None = None
    for pid in iter_pids(name):
        path = _process_image_path(pid)
        if not path:
            continue                                   # 已死/无权限/僵尸：跳过
        is_game = path.replace("/", "\\").lower().endswith("\\binaries\\nms.exe")
        if is_game:
            if require_window and not _has_main_window(pid):
                if exe_pid is None:
                    exe_pid = pid
                continue
            return pid
        if fallback is None:
            fallback = pid
    if exe_pid is not None and not require_window:
        return exe_pid
    return None if (require_exe or require_window) else fallback


def _has_main_window(pid: int) -> bool:
    """进程是否有可见、带标题、无 owner 的主窗口（用于区分真正的游戏进程）。"""
    if not IS_WINDOWS:
        return False
    try:
        ctypes, wintypes, _k32 = _win()
        user32 = ctypes.windll.user32
        found: list[int] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                           wintypes.LPARAM)

        def _callback(hwnd, _lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                if user32.GetWindow(hwnd, 4):          # GW_OWNER：tooltip/子窗跳过
                    return True
                owner = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
                if owner.value != int(pid):
                    return True
                if user32.GetWindowTextLengthW(hwnd) > 0:
                    found.append(int(hwnd))
                    return False
            except Exception:                          # noqa: BLE001
                pass
            return True

        user32.EnumWindows(callback_type(_callback), 0)
        return bool(found)
    except Exception:                                  # noqa: BLE001 - 查询失败按“没有窗口”处理
        return False


def iter_pids(name: str = "NMS.exe"):
    """遍历所有同名进程 PID（Windows）；平台不支持时返回空迭代器。"""
    if not IS_WINDOWS:
        return
    ctypes, wintypes, k32 = _win()
    TH32CS_SNAPPROCESS = 0x00000002

    class PE32(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]

    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (0, -1):
        return
    try:
        e = PE32()
        e.dwSize = ctypes.sizeof(PE32)
        ok = k32.Process32First(snap, ctypes.byref(e))
        while ok:
            if e.szExeFile.decode("mbcs", "replace").lower() == name.lower():
                yield int(e.th32ProcessID)
            ok = k32.Process32Next(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)


def _process_image_path(pid: int) -> str:
    """取进程映像路径；打不开/没有路径（僵尸）返回空串。"""
    if not IS_WINDOWS:
        return ""
    try:
        ctypes, wintypes, k32 = _win()
        access = 0x1000                              # PROCESS_QUERY_LIMITED_INFORMATION
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        k32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD)]
        h = k32.OpenProcess(access, False, int(pid))
        if not h:
            return ""
        try:
            size = wintypes.DWORD(32768)
            buf = ctypes.create_unicode_buffer(size.value)
            if not k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return ""
            return str(buf.value or "")
        finally:
            k32.CloseHandle(h)
    except Exception:                                  # noqa: BLE001 - 任何异常都按僵尸/不可读处理
        return ""


def attach(name: str = "NMS.exe") -> Process:
    """连上游戏进程；不支持/未运行就抛 LiveUnsupported（带中文原因）。"""
    pid = find_pid(name, require_exe=name.lower() == "nms.exe")
    if not pid:
        raise LiveUnsupported(f"没有找到 {name}：请先启动游戏并载入存档")
    return WinProcess(pid, name)


# ---------------------------------------------------------------- 测试替身


class FakeProcess(Process):
    """合成内存：测试用。`Image` 是 {基址: bytearray} 的列表。"""

    def __init__(self, images: list[tuple[int, bytearray]] | None = None, name: str = "fake"):
        self.images = images or []
        self.name = name
        self.writes: list[tuple[int, bytes]] = []

    def _locate(self, addr: int, size: int):
        for base, buf in self.images:
            if base <= addr and addr + size <= base + len(buf):
                return buf, addr - base
        return None, None

    def read(self, addr: int, size: int) -> bytes:
        buf, off = self._locate(addr, size)
        if buf is None:
            raise LiveUnsupported(f"读取越界 0x{addr:X}+{size}")
        return bytes(buf[off:off + size])

    def write_at(self, addr: int, data: bytes) -> bool:
        buf, off = self._locate(addr, len(data))
        if buf is None:
            return False
        buf[off:off + len(data)] = data
        self.writes.append((addr, bytes(data)))
        return True

    def regions(self, min_size: int = 0x1000,
                max_regions: int = DEFAULT_MAX_REGIONS) -> RegionList:
        """和真实进程保持同一语义：按 min_size 过滤、按 max_regions 截断并标记。"""
        out: list[Region] = []
        truncated = False
        limit = max(0, int(max_regions))
        for base, buf in self.images:
            size = len(buf)
            if size < min_size:
                continue
            if len(out) >= limit:
                truncated = True
                break
            out.append(Region(base, size, 0x04))
        return self._wrap_regions(out, max_regions, truncated)
