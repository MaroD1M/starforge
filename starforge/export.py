"""批量导出：把若干艘船导出成 zip（glb + png + 清单）。

用途：晒图/分享/备份自己搜到的设计。全部本地生成，不联网。
"""
from __future__ import annotations

import io
import json
import zipfile

from .core import log
from .data.shipref import ShipRef

log = log.get("export")


def export_zip(items: list[dict], include_glb: bool = True, include_png: bool = True,
               png_size: int = 640) -> tuple[bytes, dict]:
    """items: [{type, seed, parts?, name?}] → (zip 字节, 统计)。"""
    from . import paint as paint_mod, preview, render

    buf = io.BytesIO()
    manifest, ok, failed = [], 0, []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for raw in items:
            try:
                ref = ShipRef(**{k: raw.get(k) for k in ("type", "seed", "parts", "name")
                                 if k in raw}).normalized()
            except Exception as e:                      # noqa: BLE001
                failed.append({"input": raw, "error": str(e)})
                continue
            base = f"{ref.type}_{ref.seed}"
            if ref.name:
                safe = "".join(c for c in ref.name if c not in r'\\/:*?"<>|')[:24]
                base = f"{base}_{safe}" if safe else base
            entry = {"type": ref.type, "type_label": ref.type_label, "seed": ref.seed,
                     "parts": ref.parts, "name": ref.name,
                     "colours": {k: paint_mod.hexcol(v) for k, v in paint_mod.look(ref.seed, ref.type).items()},
                     "files": []}
            if not ref.can_preview:
                entry["note"] = "固定模型：外观不由种子决定，未导出 3D"
                manifest.append(entry)
                continue
            try:
                if include_glb:
                    path = preview.glb_for(ref)
                    z.write(path, arcname=f"{base}.glb")
                    entry["files"].append(f"{base}.glb")
                if include_png:
                    png = render.ship_png(ref.type, ref.seed, ref.parts, ("iso", "side"),
                                          (png_size, png_size),
                                          colours=paint_mod.look(ref.seed, ref.type))
                    z.writestr(f"{base}.png", png)
                    entry["files"].append(f"{base}.png")
                ok += 1
            except Exception as e:                      # noqa: BLE001
                entry["error"] = f"{type(e).__name__}: {e}"
                failed.append({"input": raw, "error": entry["error"]})
            manifest.append(entry)

        z.writestr("manifest.json", json.dumps(
            {"count": len(manifest), "exported": ok, "failed": failed, "items": manifest},
            ensure_ascii=False, indent=1))
    data = buf.getvalue()
    log.info("批量导出 %d 艘（成功 %d，失败 %d），%d KB", len(manifest), ok, len(failed), len(data) // 1024)
    return data, {"count": len(manifest), "exported": ok, "failed": len(failed)}
