"""PyInstaller 入口：把"运行时才用到"的模块显式导入，确保依赖被分析到。

为什么需要它：
  直接拿 `starforge/__main__.py` 当入口时，Flask / numpy 这些只在函数里延迟导入的依赖
  会被 PyInstaller 漏掉（v0.9.0-beta 实测：打包体积少 3 MB，运行到网页/渲染才崩）。
  这里在模块层显式 import，让分析器把它们全部收进包。
"""
from __future__ import annotations

# 关键第三方依赖（显式导入，防止被漏）。
# 这里用 try 包住：若用户机器上的 numpy DLL 被拦/损坏，至少让主程序进入
# 诊断/降级界面，而不是在 PyInstaller 引导阶段直接崩掉。
try:
    import numpy  # noqa: F401
except Exception as _e:                                      # noqa: BLE001
    print(f"[starforge] numpy 导入失败：{_e}", file=__import__("sys").stderr)
import flask  # noqa: F401
import lz4.block  # noqa: F401
import hgpaktool  # noqa: F401
try:                         # 旧桌面壳（可选回退）
    import webview  # noqa: F401
except Exception:            # noqa: BLE001
    pass
try:                         # 原生界面（默认）
    import PySide6  # noqa: F401
except Exception:            # noqa: BLE001
    pass
try:                         # 可选：解码游戏内 BC7 符文图标
    import texture2ddecoder  # noqa: F401
except Exception:            # noqa: BLE001
    pass

# 本项目里"延迟导入"的模块（网页、渲染、系统生成、实时通道、置顶窗口）。
# 包一层 try：如果用户机器上的 numpy DLL 被拦/损坏，主程序仍能进入诊断界面，
# 而不是在 PyInstaller 引导阶段直接退出。PyInstaller 的 --collect-submodules 仍会收集这些模块。
try:
    import starforge.web.app  # noqa: F401
    import starforge.web.routes  # noqa: F401
    import starforge.services  # noqa: F401
    import starforge.render  # noqa: F401
    import starforge.preview  # noqa: F401
    import starforge.system  # noqa: F401
    import starforge.search  # noqa: F401
    import starforge.jobs  # noqa: F401
    import starforge.glyphs  # noqa: F401
    import starforge.gltf  # noqa: F401
    import starforge.galaxy  # noqa: F401
    import starforge.creature  # noqa: F401
    import starforge.overlay  # noqa: F401
    import starforge.desktop  # noqa: F401
    import starforge.zh  # noqa: F401
    import starforge.tex  # noqa: F401
    import starforge.paint  # noqa: F401
    import starforge.parts  # noqa: F401
    import starforge.export  # noqa: F401
    import starforge.warm  # noqa: F401
    import starforge.selfcheck  # noqa: F401
    import starforge.locate_game  # noqa: F401
    import starforge.save.library  # noqa: F401
    import starforge.save.writer  # noqa: F401
    import starforge.live.scan  # noqa: F401
    import starforge.live.mem  # noqa: F401
    import starforge.live.writer  # noqa: F401
    import starforge.live.compat  # noqa: F401
    import starforge.live.exml  # noqa: F401
    import starforge.live.build  # noqa: F401
    import starforge.live.agent_client  # noqa: F401
    import starforge.live.agent_install  # noqa: F401
    import starforge.data.catalog  # noqa: F401
    import starforge.data.icons  # noqa: F401
    import starforge.data.shipref  # noqa: F401
    try:
        import starforge.app.main  # noqa: F401
    except Exception as _e:                                  # noqa: BLE001
        print(f"[starforge] 原生界面导入失败：{_e}", file=__import__("sys").stderr)
except Exception as _e:                                      # noqa: BLE001
    print(f"[starforge] 模块预导入失败（可能 numpy/上游依赖不可用）：{_e}",
          file=__import__("sys").stderr)

from starforge.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
