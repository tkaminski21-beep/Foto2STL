"""
Tryb serwera (np. Raspberry Pi w sieci domowej):
  • GUI pod http://<adres>:7860
  • REST:  curl -F image=@zdjecie.jpg -F mode=relief http://pi.local:7860/api/convert -o model.zip
           curl -F prompt="cute robot owl" -F mode=text3d -F options='{"engine":"hunyuan3d"}' …
  • katalog obserwowany: wrzucasz zdjęcie (scp / Syncthing / SMB) → po chwili obok leży STL
  • powiadomienie MQTT po każdym modelu
"""


import json
from typing import Optional
import shutil
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from .core import IMG_EXT, log
from .pipeline import MODES, options, run

LOCK = threading.Lock()


def make_app(base_opts: dict):
    import gradio as gr
    from fastapi import FastAPI, File, Form, HTTPException, UploadFile
    from fastapi.responses import FileResponse, JSONResponse

    from . import history
    from .gui import CSS, _gr_major, build_ui

    app = FastAPI(title="Foto2STL")

    @app.post("/api/convert")
    def convert(mode: str = Form("relief"), image: Optional[UploadFile] = File(None),
                prompt: str = Form(""), options_json: str = Form("{}", alias="options")):
        if mode not in MODES:
            raise HTTPException(400, f"mode musi być jednym z: {', '.join(MODES)}")
        try:
            extra = json.loads(options_json or "{}")
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"options to nie JSON: {e}") from e
        tmp = Path(tempfile.mkdtemp(prefix="f2s_api_"))
        inputs = {"prompt": prompt}
        if image is not None:
            p = tmp / Path(image.filename or "upload.jpg").name
            with open(p, "wb") as f:
                shutil.copyfileobj(image.file, f)
            inputs["image"] = str(p)
        with LOCK:
            try:
                r = run(mode, inputs, options(**{**base_opts, **extra}), tmp / f"{Path(p).stem if image else 'model'}_{mode}")
            except Exception as e:  # noqa: BLE001
                raise HTTPException(500, str(e)) from e
        files = [f for f in r["files"] if not f.endswith(".zip")]
        if len(files) == 1:
            return FileResponse(files[0], filename=Path(files[0]).name)
        zp = tmp / "wynik.zip"
        with zipfile.ZipFile(zp, "w") as z:
            for f in files:
                z.write(f, Path(f).name)
            z.writestr("raport.txt", r["report"])
        return FileResponse(zp, filename=Path(r["out_base"]).name + ".zip")

    @app.get("/api/history")
    def hist():
        return JSONResponse([{k: e[k] for k in ("time", "mode", "label", "files", "report", "dir")}
                             for e in history.entries(50)])

    @app.get("/api/health")
    def health():
        return {"ok": True, "busy": LOCK.locked()}

    ui = build_ui(base_opts)
    kw = dict(css=CSS, theme=gr.themes.Soft()) if _gr_major() >= 6 else {}
    try:
        app = gr.mount_gradio_app(app, ui.queue(), path="/", **kw)
    except TypeError:
        app = gr.mount_gradio_app(app, ui.queue(), path="/")
    return app


def watch_folder(folder, out_dir, mode, base_opts, interval=3.0, stop: Optional[threading.Event] = None):
    folder, out_dir = Path(folder), Path(out_dir or Path(folder) / "wyniki")
    done_dir = folder / "przetworzone"
    for d in (out_dir, done_dir):
        d.mkdir(parents=True, exist_ok=True)
    log(f"Obserwuję {folder} → {out_dir} (tryb {mode}). Prompt: wrzuć plik .txt z opisem → text3d.")
    sizes = {}
    while not (stop and stop.is_set()):
        for f in sorted(folder.iterdir()):
            if not f.is_file() or f.suffix.lower() not in IMG_EXT | {".txt"}:
                continue
            sz = f.stat().st_size
            if sizes.get(f) != sz:  # czekamy, aż plik się dogra
                sizes[f] = sz
                continue
            sizes.pop(f, None)
            m, inputs = (("text3d", {"prompt": f.read_text(encoding="utf-8").strip()}) if f.suffix == ".txt"
                         else (mode, {"image": str(f)}))
            try:
                with LOCK:
                    run(m, inputs, options(**base_opts), out_dir / f"{f.stem}_{m}")
            except Exception as e:  # noqa: BLE001
                log(f"BŁĄD przy {f.name}: {e}")
            shutil.move(str(f), done_dir / f.name)
        time.sleep(interval)


def serve(host="0.0.0.0", port=7860, base_opts=None, watch=None, watch_out=None, watch_mode="relief"):
    import uvicorn
    base_opts = base_opts or {}
    if watch:
        threading.Thread(target=watch_folder, args=(watch, watch_out, watch_mode, base_opts),
                         daemon=True).start()
    log(f"Serwer: http://{host}:{port}  (REST: /api/convert, /api/history, /api/health)")
    uvicorn.run(make_app(base_opts), host=host, port=port)
