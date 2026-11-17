"""符文置顶窗口：把 12 个传送门符文贴在游戏窗口上面，玩家照着点。

**不注入游戏**：这是一个普通的置顶窗口（Windows 上额外加"点击穿透"与"不抢焦点"扩展样式），
游戏用「无边框窗口」模式即可看到。

在 Windows 上额外做的事：
  WS_EX_TOPMOST | WS_EX_TOOLWINDOW | (可选) WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
"""
from __future__ import annotations

import base64
import sys

IS_WINDOWS = sys.platform.startswith("win")


class OverlayUnsupported(RuntimeError):
    pass


def panel_spec(glyphs: str, tile: int = 64, gap: int = 8) -> dict:
    """窗口尺寸与布局（纯函数，便于测试）。"""
    digits = [c for c in str(glyphs).upper() if c.strip()]
    if not digits:
        raise ValueError("空符文串")
    width = len(digits) * tile + (len(digits) - 1) * gap + 24
    height = tile + 56
    return {"digits": digits, "width": width, "height": height, "tile": tile, "gap": gap}


def _set_click_through(win_id: int) -> None:
    if not IS_WINDOWS:
        return
    import ctypes
    GWL_EXSTYLE = -20
    WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = 0x80000, 0x20, 0x8000000, 0x80
    u = ctypes.windll.user32
    style = u.GetWindowLongW(win_id, GWL_EXSTYLE)
    u.SetWindowLongW(win_id, GWL_EXSTYLE,
                     style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)


def show(glyphs: str, png: bytes, *, alpha: float = 0.94, click_through: bool = False,
         scale: float = 1.0) -> None:
    """阻塞显示置顶窗口（Esc 或关闭按钮退出）。没有图形环境时抛 OverlayUnsupported。"""
    try:
        import tkinter as tk
    except Exception as e:                                  # noqa: BLE001
        raise OverlayUnsupported(f"当前 Python 没带 tkinter：{e}") from e
    try:
        root = tk.Tk()
    except Exception as e:                                  # noqa: BLE001  TclError: 无 DISPLAY
        raise OverlayUnsupported(f"没有可用的图形界面：{e}") from e

    spec = panel_spec(glyphs)
    root.overrideredirect(True)                             # 无边框
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", max(0.3, min(1.0, alpha)))
    except Exception:                                       # noqa: BLE001
        pass
    root.configure(bg="#05070c")

    img = tk.PhotoImage(data=base64.b64encode(png).decode())
    if scale != 1.0:
        img = img.zoom(max(1, int(scale)))                  # 整数倍放大，保像素锐利
    tk.Label(root, image=img, bg="#05070c", bd=0).pack(padx=12, pady=(10, 2))
    tk.Label(root, text=f"{glyphs}    Esc 关闭 · 拖动可移动", fg="#7f8b9e", bg="#05070c",
             font=("Consolas", 10)).pack(pady=(0, 8))
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    root.geometry(f"{w}x{h}+{max(0, (root.winfo_screenwidth() - w) // 2)}+40")
    root.bind("<Escape>", lambda e: root.destroy())

    if click_through:
        _set_click_through(root.winfo_id())

    # 拖动（点击穿透时不会触发，属预期）
    state = {"x": 0, "y": 0}

    def down(e):
        state["x"], state["y"] = e.x, e.y

    def move(e):
        root.geometry(f"+{root.winfo_x() + e.x - state['x']}+{root.winfo_y() + e.y - state['y']}")

    for w_ in root.winfo_children():
        w_.bind("<Button-1>", down)
        w_.bind("<B1-Motion>", move)

    root.mainloop()
