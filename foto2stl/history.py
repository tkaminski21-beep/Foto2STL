"""Historia generowań: ~/.foto2stl/history/<data>_<tryb>/ (miniatura, pliki, parametry, raport)."""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from PIL import Image

HIST = Path(os.environ.get("FOTO2STL_HOME", Path.home() / ".foto2stl")) / "history"


def save(mode, files, params, report, image=None, label=""):
    HIST.mkdir(parents=True, exist_ok=True)
    d = HIST / f"{time.strftime('%Y%m%d-%H%M%S')}_{mode}"
    d.mkdir(exist_ok=True)
    if image is not None:
        try:
            im = image if isinstance(image, Image.Image) else Image.open(image)
            im = im.convert("RGB")
            im.thumbnail((384, 384))
            im.save(d / "thumb.jpg", quality=85)
        except Exception:  # noqa: BLE001
            pass
    saved = []
    for f in files:
        dst = d / Path(f).name
        if Path(f).resolve() != dst.resolve():
            shutil.copy2(f, dst)
        saved.append(str(dst))
    safe = {k: v for k, v in params.items() if isinstance(v, (str, int, float, bool, type(None)))}
    (d / "info.json").write_text(json.dumps(
        dict(mode=mode, label=label, time=time.strftime("%Y-%m-%d %H:%M"), files=[Path(s).name for s in saved],
             params=safe, report=report), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(d)


def entries(limit=200):
    if not HIST.exists():
        return []
    out = []
    for d in sorted(HIST.iterdir(), reverse=True)[:limit]:
        try:
            info = json.loads((d / "info.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        info["dir"] = str(d)
        info["thumb"] = str(d / "thumb.jpg") if (d / "thumb.jpg").exists() else None
        info["preview"] = next((str(d / f) for f in info["files"] if f.endswith((".glb", ".stl"))), None)
        out.append(info)
    return out
