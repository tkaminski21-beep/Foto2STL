"""Wiersz poleceń. Wszystkie opcje potoku są dostępne jako flagi (--nazwa-opcji)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import log, safe_stem
from .pipeline import DEFAULTS, MODES, options, run

HELP = {
    "engine": "silnik 3D: local (TripoSR) | hunyuan3d | hunyuan3d-color",
    "formats": "dodatkowe formaty, np. 3mf,glb,ply",
    "color": "kolor: 3MF z malowaniem pod AMS/MMU + GLB",
    "n_colors": "liczba filamentów przy kolorze",
    "width_mm": "szerokość (płaskie tryby) / obwód (cylinder) [mm]",
    "height_mm": "wysokość modelu 3D [mm]",
    "relief_mm": "głębokość reliefu ponad podstawą [mm]",
    "base_mm": "grubość podstawy [mm]",
    "res": "rozdzielczość siatki trybów płaskich (dłuższy bok, px)",
    "shape": "rect | rounded | circle | oval | hexagon | heart | contour",
    "frame_mm": "szerokość ramki [mm]",
    "keychain": "dodaj oczko breloka",
    "back_text": "napis grawerowany na spodzie",
    "litho": "litofan: flat | curved | cylinder | color",
    "arc_deg": "kąt wygięcia litofanu curved",
    "base_cut_mm": "ścięcie spodu modelu 3D na płasko [mm]",
    "pedestal": "podstawka pod model 3D", "pedestal_text": "napis na podstawce",
    "hollow_mm": "wydrążenie: grubość ścianki [mm] (0 = pełny)",
    "drain_mm": "średnica otworu odpływowego [mm]",
    "auto_orient": "automatyczna orientacja (mniej podpór)",
    "split": "podziel na części mieszczące się na stole (bed_x/y/z)",
    "slice": "pokrój do G-code", "slicer_config": ".ini (Prusa) lub 'maszyna.json;proces.json' (Orca)",
    "printer_url": "adres OctoPrint/Moonraker", "printer_kind": "octoprint | moonraker",
    "mqtt": "host brokera MQTT do powiadomień", "hf_token": "token Hugging Face (większy limit GPU)",
    "space": "własny Space HF (owner/nazwa) dla trybu chmurowego",
    "depth_model": "model głębi (id z Hugging Face albo lokalny katalog)",
    "rembg_model": "model usuwania tła: u2net | u2netp (najlżejszy, Pi/uConsole) | isnet-general-use | birefnet-general",
}


def build_parser():
    p = argparse.ArgumentParser(prog="foto2stl", description="Zdjęcie / opis → model 3D do druku",
                                formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("images", nargs="*", help="zdjęcia wejściowe")
    p.add_argument("-m", "--mode", choices=MODES, default="relief")
    p.add_argument("-o", "--output", help="plik bazowy (1 wejście) lub katalog (wiele)")
    p.add_argument("--prompt", help="opis obiektu (tryb text3d)")
    for v in ("front", "back", "left", "right"):
        p.add_argument(f"--{v}", help=f"zdjęcie: {v} (tryb multiview)")
    g = p.add_argument_group("uruchamianie")
    g.add_argument("--gui", action="store_true", help="interfejs w przeglądarce")
    g.add_argument("--server", action="store_true", help="serwer w sieci (GUI + REST), np. na Raspberry Pi")
    g.add_argument("--host", default=None)
    g.add_argument("--port", type=int, default=7860)
    g.add_argument("--share", action="store_true", help="publiczny link Gradio")
    g.add_argument("--watch", help="katalog obserwowany (z --server albo samodzielnie)")
    g.add_argument("--watch-out", help="katalog wyników dla --watch")
    g.add_argument("--cloud-api", metavar="SPACE", help="pokaż API Space'a HF i zakończ")
    g.add_argument("--history", action="store_true", help="wypisz historię i zakończ")
    g.add_argument("--no-history", action="store_true", help="nie zapisuj w historii")
    o = p.add_argument_group("opcje modelu")
    for k, v in DEFAULTS.items():
        if k == "save_history":
            continue
        flag = "--" + k.replace("_", "-")
        h = HELP.get(k, " ")
        if isinstance(v, bool):
            o.add_argument(flag, action="store_true", default=None, help=h)
        elif isinstance(v, (int, float)):
            o.add_argument(flag, type=type(v), default=None, help=f"{h} (domyślnie {v})")
        else:
            o.add_argument(flag, default=None, help=f"{h}" + (f" (domyślnie {v})" if v else ""))
    return p


def main(argv=None):
    p = build_parser()
    if argv is None and getattr(sys, "frozen", False) and len(sys.argv) == 1:
        argv = ["--gui"]  # wersja .exe uruchomiona dwuklikiem → od razu GUI
    a = p.parse_args(argv)
    opts = {k: getattr(a, k) for k in DEFAULTS if k != "save_history" and getattr(a, k, None) is not None}
    if a.no_history:
        opts["save_history"] = False

    if a.cloud_api:
        from .cloud import describe_api
        try:
            print(describe_api(a.cloud_api, opts.get("hf_token")))
        except Exception as e:  # noqa: BLE001
            log(f"BŁĄD: {e}")
            sys.exit(1)
        return
    if a.history:
        from .history import entries
        for e in entries():
            print(f"{e['time']}  {e['mode']:<10} {e['dir']}\n    {e['report'].splitlines()[0] if e['report'] else ''}")
        return
    if a.server:
        from .server import serve
        return serve(a.host or "0.0.0.0", a.port, opts, a.watch, a.watch_out, a.mode)
    if a.gui:
        from .gui import run_gui
        return run_gui(a.host or "127.0.0.1", a.port, a.share, opts)
    if a.watch:
        from .server import watch_folder
        return watch_folder(a.watch, a.watch_out, a.mode, opts)

    jobs = []
    if a.mode == "text3d" or (a.prompt and not a.images):
        jobs.append(("text3d", {"prompt": a.prompt or ""}, safe_stem(a.prompt or "model")))
    elif a.mode == "multiview":
        views = {v: getattr(a, v) for v in ("front", "back", "left", "right")}
        views["front"] = views["front"] or (a.images[0] if a.images else None)
        jobs.append(("multiview", views, safe_stem(views["front"] or "multiview")))
    else:
        if not a.images:
            p.error("podaj zdjęcie (albo --prompt, --gui, --server)")
        jobs += [(a.mode, {"image": i}, safe_stem(i)) for i in a.images]

    out = Path(a.output) if a.output else None
    many = len(jobs) > 1
    for mode, inputs, stem in jobs:
        if out and not many:
            base = out.with_suffix("") if out.suffix else out
        else:
            src_dir = Path(inputs["image"]).parent if inputs.get("image") else Path.cwd()
            base = (out or src_dir) / f"{stem}_{mode}"
        log(f"{stem}: tryb {mode}")
        try:
            r = run(mode, inputs, options(**opts), base)
            print("\n".join("  → " + f for f in r["files"]))
        except Exception as e:  # noqa: BLE001
            log(f"BŁĄD: {e}")
            if not many:
                sys.exit(1)


if __name__ == "__main__":
    main()
