"""错误体系：每种错误自带 HTTP 码与中文提示。

约定（S0 验收项）：
  · 业务错误一律继承 NmsHunterError，不向上抛裸异常；
  · web 层捕获后转成 {"ok": false, "error": {"kind","message","hint"}}；
  · 写入类错误统一 403（写开关未开）或 409（状态冲突）。
"""
from __future__ import annotations


class NmsHunterError(Exception):
    status = 500
    kind = "internal"
    hint = ""

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        if hint:
            self.hint = hint

    def as_dict(self) -> dict:
        return {"kind": self.kind, "message": self.message, "hint": self.hint}


class BadRequest(NmsHunterError):
    status = 400
    kind = "bad_request"
    hint = "检查参数名与取值"


class NotFound(NmsHunterError):
    status = 404
    kind = "not_found"
    hint = "确认路径/名称是否存在"


class SaveNotFound(NotFound):
    kind = "save_not_found"
    hint = "在设置里指定存档目录，或把 save.hg 放到默认位置"


class SaveFormatError(NmsHunterError):
    status = 422
    kind = "save_format"
    hint = "该文件不是可解析的玩家存档（accountdata/mf_ 清单不在此列），或游戏版本已变更"


class GameFilesMissing(NmsHunterError):
    status = 503
    kind = "game_files_missing"
    hint = "缺少游戏安装目录（pak/exe）。3D 会降级为缩略图（L0），搜索与存档功能不受影响"


class WriteDisabled(NmsHunterError):
    status = 403
    kind = "write_disabled"
    hint = "到设置页打开“允许写入”，或在 CLI 加 --yes-write"


class WriteRefused(NmsHunterError):
    status = 409
    kind = "write_refused"
    hint = "游戏正在运行、目标不可写、或类型/模型不匹配"
