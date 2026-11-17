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
import starforge.overlay  # noqa: F401
import starforge.live.scan  # noqa: F401
import starforge.live.exml  # noqa: F401
import starforge.live.mem  # noqa: F401
import starforge.live.writer  # noqa: F401

from starforge.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
