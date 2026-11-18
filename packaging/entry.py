"""PyInstaller 入口：把"运行时才用到"的模块显式导入，确保依赖被分析到。

为什么需要它：
  直接拿 `starforge/__main__.py` 当入口时，Flask / numpy 这些只在函数里延迟导入的依赖
  会被 PyInstaller 漏掉（v0.9.0-beta 实测：打包体积少 3 MB，运行到网页/渲染才崩）。
  这里在模块层显式 import，让分析器把它们全部收进包。
"""
from __future__ import annotations

# 关键第三方依赖（显式导入，防止被漏）
import numpy  # noqa: F401
import flask  # noqa: F401
import lz4.block  # noqa: F401
import hgpaktool  # noqa: F401
try:                         # 桌面窗口
    import webview  # noqa: F401
except Exception:            # noqa: BLE001
    pass
try:                         # 可选：解码游戏内 BC7 符文图标
    import texture2ddecoder  # noqa: F401
except Exception:            # noqa: BLE001
    pass

# 本项目里"延迟导入"的模块（网页、渲染、系统生成、实时通道、置顶窗口）
import starforge.web.app  # noqa: F401
import starforge.web.routes  # noqa: F401
import starforge.render  # noqa: F401
import starforge.preview  # noqa: F401
import starforge.system  # noqa: F401
import starforge.search  # noqa: F401
import starforge.jobs  # noqa: F401
import starforge.glyphs  # noqa: F401
import starforge.gltf  # noqa: F401
import starforge.galaxy  # noqa: F401  （M3 银河索引：SQLite 落库/查询/CSV）
import starforge.creature  # noqa: F401  （M8-lite 同伴 + T8 角色表）
import starforge.overlay  # noqa: F401
import starforge.desktop  # noqa: F401

# 显式导入，保证这些模块一定进 PYZ（v0.12.0 曾无法确认 zh/tex 是否被打进去）
import starforge.zh  # noqa: F401
import starforge.tex  # noqa: F401
import starforge.paint  # noqa: F401
import starforge.parts  # noqa: F401
import starforge.export  # noqa: F401
import starforge.warm  # noqa: F401
import starforge.render  # noqa: F401
import starforge.preview  # noqa: F401
import starforge.gltf  # noqa: F401
import starforge.search  # noqa: F401
import starforge.jobs  # noqa: F401
import starforge.system  # noqa: F401
import starforge.glyphs  # noqa: F401
import starforge.selfcheck  # noqa: F401
import starforge.locate_game  # noqa: F401
import starforge.save.library  # noqa: F401
import starforge.save.writer  # noqa: F401
import starforge.live.scan  # noqa: F401
import starforge.live.mem  # noqa: F401
import starforge.live.writer  # noqa: F401
import starforge.live.compat  # noqa: F401
import starforge.live.exml  # noqa: F401
import starforge.data.catalog  # noqa: F401
import starforge.data.icons  # noqa: F401
import starforge.data.shipref  # noqa: F401

from starforge.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
