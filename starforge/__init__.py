"""starforge —— 无人深空飞船/星球搜寻与预览工具（原生桌面 + Python 内核）。

分层：
  core/   基础设施（路径、设置、日志、错误、单实例锁、中文文案）
  data/   只读数据（Gagarin catalog/icons、ShipRef 数据模型）
  save/   存档访问（包 Shipwright 的 nms_save）
  app/    PySide6 原生界面（Windows 默认）
  services/  UI/HTTP 共用的用例层
  web/    可选：本地 Flask 服务与 JSON API（调试/兼容）

设计约束见 analysis/07-需求确认单.md：
  · 写入默认关闭（write_enabled=false），任何写接口未开启时返回 403
  · 3D 预览走三级降级：L0 缩略图 / L1 真 3D（需 pak）/ L2 交给游戏
  · 不修改上游 Shipwright 源码，只做薄封装
"""

__version__ = "0.15.0"
