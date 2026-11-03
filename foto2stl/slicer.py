"""Cięcie do G-code (PrusaSlicer / OrcaSlicer CLI) i wysyłka do drukarki (OctoPrint / Moonraker)."""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import time
from pathlib import Path

from .core import log

CANDIDATES = {
    "prusa": ["prusa-slicer-console", "prusa-slicer", "PrusaSlicer",
              r"C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe",
              "/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer"],
    "orca": ["orca-slicer", "OrcaSlicer", r"C:\Program Files\OrcaSlicer\orca-slicer.exe",
             "/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"],
}


def find_slicer(kind="auto", path=None):
    if path:
        return ("orca" if "orca" in path.lower() else "prusa"), path
    kinds = ["prusa", "orca"] if kind == "auto" else [kind]
    for k in kinds:
        for c in CANDIDATES[k]:
            p = shutil.which(c) or (c if os.path.isfile(c) else None)
            if p:
                return k, p
    # AppImage w katalogu domowym
    for k in kinds:
        hits = glob.glob(os.path.expanduser(f"~/*{'Prusa' if k == 'prusa' else 'Orca'}*.AppImage"))
        if hits:
            return k, hits[0]
    raise FileNotFoundError("Nie znaleziono slicera. Zainstaluj PrusaSlicer lub OrcaSlicer albo podaj --slicer-path.")


def slice_model(model_path, config, out_dir=None, kind="auto", slicer_path=None, filament=None):
    """
    PrusaSlicer: config = plik .ini (Plik → Eksportuj konfigurację).
    OrcaSlicer: config = "maszyna.json;proces.json", filament = "filament.json"
                (pliki z ~/.config/OrcaSlicer/user/… lub %APPDATA%\\OrcaSlicer\\user\\…).
    """
    kind, exe = find_slicer(kind, slicer_path)
    model_path = Path(model_path)
    out_dir = Path(out_dir or model_path.parent)
    out_dir.mkdir(parents=True, exist_ok=True)
    if kind == "prusa":
        out = out_dir / (model_path.stem + ".gcode")
        cmd = [exe, "--export-gcode", "--output", str(out), str(model_path)]
        if config:
            cmd[1:1] = ["--load", str(config)]
    else:
        out = None
        cmd = [exe, "--slice", "0", "--arrange", "1", "--orient", "0", "--outputdir", str(out_dir)]
        if config:
            cmd += ["--load-settings", str(config)]
        if filament:
            cmd += ["--load-filaments", str(filament)]
        cmd.append(str(model_path))
    log(f"Tnę w {kind}: {' '.join(cmd)}")
    t = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f"Slicer zwrócił błąd {r.returncode}:\n{(r.stderr or r.stdout)[-1500:]}")
    if out is None:
        gc = sorted(out_dir.glob("*.gcode"), key=os.path.getmtime)
        if not gc or os.path.getmtime(gc[-1]) < t - 5:
            raise RuntimeError("OrcaSlicer nie utworzył G-code — sprawdź pliki ustawień.")
        out = out_dir / (model_path.stem + ".gcode")
        if gc[-1] != out:
            shutil.move(str(gc[-1]), out)
    log(f"G-code gotowy: {out} ({time.time() - t:.0f} s)")
    return str(out)


def upload(gcode, url, kind="octoprint", api_key=None, start=False):
    import requests
    url = url.rstrip("/")
    name = Path(gcode).name
    with open(gcode, "rb") as f:
        if kind == "octoprint":
            r = requests.post(f"{url}/api/files/local", headers={"X-Api-Key": api_key or ""},
                              files={"file": (name, f)}, data={"print": str(bool(start)).lower()}, timeout=600)
        else:  # moonraker (Klipper: Mainsail/Fluidd)
            h = {"X-Api-Key": api_key} if api_key else {}
            r = requests.post(f"{url}/server/files/upload", headers=h, files={"file": (name, f)},
                              data={"print": "true" if start else "false"}, timeout=600)
    r.raise_for_status()
    log(f"Wysłano do drukarki ({kind}): {name}" + (" — druk rozpoczęty" if start else ""))
    return True
