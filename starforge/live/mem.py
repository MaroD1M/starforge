"""进程内存读写（平台层）。

设计原则：
  · **只做"找模板槽 + 写 8 字节种子"这一件事**，不提供任何"改玩家/坐标/物品"的接口；
  · 通过 `Process` 抽象隔离平台，测试用 FakeProcess 注入合成内存，不需要真游戏；
  · 任何平台不支持或权限不足，都抛 `LiveUnsupported` 并给中文原因，绝不静默。

Windows 实现：ctypes + kernel32（OpenProcess / ReadProcessMemory / WriteProcessMemory /
VirtualQueryEx / CreateToolhelp32Snapshot / GetModuleInformation）。
"""
from __future__ import annotations

import struct
import sys
from dataclasses import dataclass

IS_WINDOWS = sys.platform.startswith("win")


class LiveUnsupported(RuntimeError):
    """当前平台/环境不支持实时通道（例如 Linux、无权限、游戏未运行）。"""


@dataclass
class Region:
    base: int
    size: int
    protect: int

    def __contains__(self, addr: int) -> bool:
        return self.base <= addr < self.base + self.size


class Process:
    """一个目标进程的只读/限写句柄。写只用 write_at，且调用方负责校验。"""

    name: str = ""

    def read(self, addr: int, size: int) -> bytes:
        raise NotImplementedError

    def write_at(self, addr: int, data: bytes) -> bool:
        raise NotImplementedError

    def regions(self, min_size: int = 0x1000, max_regions: int = 4096) -> list[Region]:
        raise NotImplementedError

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
    MEM_COMMIT = 0x1000
    PAGE_READABLE = (0x02, 0x04, 0x20, 0x40, 0x80)     # READONLY/READWRITE/WRITECOPY/EXECUTE_*

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

    def regions(self, min_size: int = 0x1000, max_regions: int = 4096) -> list[Region]:
        ctypes, wintypes, k32 = self._c, self._w, self._k

        class MBI(ctypes.Structure):
            _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                        ("AllocationProtect", wintypes.DWORD), ("RegionSize", ctypes.c_size_t),
                        ("State", wintypes.DWORD), ("Protect", wintypes.DWORD),
                        ("Type", wintypes.DWORD)]

        out, addr, mbi = [], 0, MBI()
        while len(out) < max_regions:
            if not k32.VirtualQueryEx(self.h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                break
            if mbi.State == self.MEM_COMMIT and mbi.Protect in self.PAGE_READABLE and mbi.RegionSize >= min_size:
                out.append(Region(mbi.BaseAddress or 0, int(mbi.RegionSize), int(mbi.Protect)))
            addr = (mbi.BaseAddress or 0) + int(mbi.RegionSize)
            if addr <= 0:
                break
        return out

    def close(self) -> None:
        if getattr(self, "h", None):
            self._k.CloseHandle(self.h)
            self.h = None


def find_pid(name: str = "NMS.exe") -> int | None:
    """按进程名找 PID（Windows）。"""
    if not IS_WINDOWS:
        return None
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
        return None
    try:
        e = PE32()
        e.dwSize = ctypes.sizeof(PE32)
        ok = k32.Process32First(snap, ctypes.byref(e))
        while ok:
            if e.szExeFile.decode("mbcs", "replace").lower() == name.lower():
                return int(e.th32ProcessID)
            ok = k32.Process32Next(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return None


def attach(name: str = "NMS.exe") -> Process:
    """连上游戏进程；不支持/未运行就抛 LiveUnsupported（带中文原因）。"""
    pid = find_pid(name)
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

    def regions(self, min_size: int = 0x1000, max_regions: int = 4096) -> list[Region]:
        return [Region(base, len(buf), 0x04) for base, buf in self.images]
