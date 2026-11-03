"""Jeden potok dla CLI, GUI i serwera: wejście → siatka → przygotowanie do druku → eksport."""
from __future__ import annotations

import tempfile
import time
import zipfile
from pathlib import Path

import numpy as np
import trimesh

from . import history, printprep as pp
from .core import has_colors, log, pick_device, safe_stem, transfer_colors

MODES = ("full3d", "multiview", "text3d", "relief", "heightmap", "lithophane")
PLA = 1.24

DEFAULTS = dict(
    # wspólne
    device="auto", engine="local", seed=None, hf_token=None, space=None, space_api=None,
    space_image_param="image", formats="stl", n_colors=4, color=False, target_faces=0,
    rotate_x=0.0, rotate_y=0.0, rotate_z=0.0, save_history=True,
    # płaskie
    width_mm=100.0, base_mm=2.0, relief_mm=6.0, res=400, smooth=0.8, gamma=1.0, invert=False,
    remove_bg=False, depth_model="depth-anything/Depth-Anything-V2-Small-hf", shape="rect",
    contour_margin_mm=2.0, frame_mm=0.0, keychain=False, ring_mm=5.0, hole_mm=4.0, back_text="",
    text_mm=6.0, engrave_mm=0.6,
    # litofan
    litho="flat", min_mm=0.8, max_mm=3.0, arc_deg=120.0, litho_base_mm=2.0, litho_rim_mm=3.0,
    # 3D
    height_mm=80.0, mc_res=256, mc_threshold=25.0, fg_ratio=0.85, triposr_dir=None, debug_dir=None,
    smooth_iters=5, base_cut_mm=0.0, pedestal=False, pedestal_text="", pedestal_mm=5.0,
    hollow_mm=0.0, drain_mm=0.0, auto_orient=False, overhang_deg=45.0,
    split=False, bed_x=220.0, bed_y=220.0, bed_z=250.0, pin_d=4.0, pin_len=10.0,
    text_generator="flux",
    # po eksporcie
    slice=False, slicer="auto", slicer_path=None, slicer_config=None, slicer_filament=None,
    printer_url=None, printer_kind="octoprint", printer_key=None, start_print=False,
    mqtt=None, mqtt_topic=None,
)


def options(**over):
    o = dict(DEFAULTS)
    o.update({k: v for k, v in over.items() if v is not None})
    o["device"] = pick_device(o["device"])
    return o


def report(mesh: trimesh.Trimesh, name="") -> str:
    x, y, z = mesh.extents
    faces = f"{len(mesh.faces):,}".replace(",", " ")
    s = f"{name + ': ' if name else ''}{x:.1f} × {y:.1f} × {z:.1f} mm, {faces} trójkątów"
    if mesh.is_watertight:
        v = abs(mesh.volume) / 1000
        s += f", szczelna ✔, {v:.1f} cm³ ≈ {v * PLA:.0f} g PLA (100% wypełn.)"
    else:
        s += ", uwaga: nieszczelna (slicer zwykle naprawia)"
    return s


# ─────────────────────────── etapy ───────────────────────────

def acquire_3d(mode, inputs, o, workdir):
    """Zwraca surową siatkę 3D (full3d / multiview / text3d)."""
    from . import cloud
    image = inputs.get("image")
    if mode == "text3d":
        prompt = inputs.get("prompt") or ""
        if not prompt.strip():
            raise ValueError("Podaj opis obiektu (prompt).")
        image = cloud.text_to_image(prompt, str(Path(workdir) / "prompt_image.png"),
                                    o["text_generator"], o["hf_token"], o["seed"])
        inputs["image"] = image
    if mode == "multiview":
        views = {k: inputs.get(k) for k in ("front", "back", "left", "right")}
        views["front"] = views["front"] or image
        return cloud.image_to_3d(views, "hunyuan3d-mv", o["hf_token"], seed=o["seed"])
    if not image:
        raise ValueError("Brak zdjęcia wejściowego.")
    if o["engine"] == "local":
        from .ai_local import triposr
        return triposr(image, **o)
    engine = o["engine"]
    if o["color"] and engine == "hunyuan3d":
        engine = "hunyuan3d-color"
    return cloud.image_to_3d({"image": _as_path(image, workdir)}, engine, o["hf_token"],
                             o["space"], o["space_api"], o["space_image_param"], o["seed"])


def _as_path(image, workdir):
    if isinstance(image, (str, Path)):
        return str(image)
    p = Path(workdir) / "input.png"
    image.save(p)
    return str(p)


def prep_3d(mesh, o):
    """Naprawa → obrót → skala → podstawa → wydrążenie → orientacja → decymacja → stół. Zachowuje kolory."""
    color_src = mesh.copy() if has_colors(mesh) else None
    xf = pp.Xf()
    mesh = pp.repair(mesh, o["smooth_iters"])
    if color_src is not None and o["smooth_iters"]:
        transfer_colors(mesh, color_src)
        color_src = mesh.copy()
    pp.rotate(mesh, xf, o["rotate_x"], o["rotate_y"], o["rotate_z"])
    pp.scale_to(mesh, xf, height_mm=o["height_mm"])
    if o["base_cut_mm"] > 0:
        mesh = pp.scale_to(pp.flat_base(mesh, o["base_cut_mm"]), xf, height_mm=o["height_mm"])
    pp.place_on_bed(mesh, xf)
    if o["pedestal"] or o["pedestal_text"]:
        mesh = pp.add_pedestal(mesh, o["pedestal_text"], o["pedestal_mm"])
    if o["hollow_mm"] > 0:
        mesh = pp.hollow(mesh, o["hollow_mm"], o["drain_mm"])
    if o["auto_orient"]:
        pp.auto_orient(mesh, xf, o["overhang_deg"])
    mesh = pp.decimate(mesh, o["target_faces"])
    pp.place_on_bed(mesh, xf)
    if color_src is not None:
        color_src.apply_transform(xf.M)
        transfer_colors(mesh, color_src)
    return mesh


def build(mode, inputs, o, workdir):
    """Zwraca listę części: (nazwa, siatka, rgba|None)."""
    if mode in ("full3d", "multiview", "text3d"):
        mesh = prep_3d(acquire_3d(mode, inputs, o, workdir), o)
        if o["split"]:
            parts = pp.split_for_bed(mesh, (o["bed_x"], o["bed_y"], o["bed_z"]), o["pin_d"], o["pin_len"])
            if len(parts) > 1:
                out = [(f"czesc{i + 1}", pp.lay_flat_for_print(p), None) for i, p in enumerate(parts)]
                out.append(("kolek", pp.make_pin(o["pin_d"], o["pin_len"]), None))
                return out
        return [("model", mesh, None)]

    image = inputs.get("image")
    if image is None:
        raise ValueError("Brak zdjęcia wejściowego.")
    if mode == "lithophane":
        from . import lithophane as lt
        if o["litho"] == "color":
            parts = lt.color_cmy(image, o["width_mm"], o["res"], o["smooth"])
            b = trimesh.util.concatenate([m for _, m, _ in parts]).bounds
            shift = [-(b[0, 0] + b[1, 0]) / 2, -(b[0, 1] + b[1, 1]) / 2, -b[0, 2]]
            return [(n, m.apply_translation(shift), c) for n, m, c in parts]  # wspólne przesunięcie
        h, _ = lt.litho_map(image, o["res"], o["smooth"], o["invert"])
        if o["litho"] == "cylinder":
            m = lt.cylinder(h, o["width_mm"], o["min_mm"], o["max_mm"], o["litho_base_mm"], o["litho_rim_mm"])
        else:
            m = lt.flat(h, o["width_mm"], o["min_mm"], o["max_mm"], o["shape"] if o["shape"] != "contour" else "rect",
                        o["frame_mm"])
            if o["litho"] == "curved":
                m = lt.bend(m, o["arc_deg"])
            elif o["litho"] == "flat":
                pass
        return [("litofan", pp.place_on_bed(m), None)]

    from .flat import make_flat
    m = make_flat(image, mode, o)
    xf = pp.Xf()
    pp.rotate(m, xf, o["rotate_x"], o["rotate_y"], o["rotate_z"])
    return [(mode, pp.place_on_bed(m), None)]


def export(parts, out_base: Path, o):
    """Zapisuje STL (zawsze) + opcjonalnie 3MF/GLB/PLY. Zwraca listę plików."""
    fmts = {f.strip().lower() for f in str(o["formats"]).split(",") if f.strip()} | {"stl"}
    out_base.parent.mkdir(parents=True, exist_ok=True)
    files = []
    if len(parts) == 1:
        parts[0][1].export(f"{out_base}.stl")
        files.append(f"{out_base}.stl")
    else:
        for name, m, _ in parts:
            p = f"{out_base}_{name}.stl"
            m.export(p)
            files.append(p)
    if "3mf" in fmts:
        from .color import write_3mf, write_painted_3mf
        p = f"{out_base}.3mf"
        if len(parts) == 1 and has_colors(parts[0][1]):
            pal = write_painted_3mf(p, parts[0][1], int(o["n_colors"]))
            log("3MF z malowaniem pod AMS/MMU, kolory filamentów: " +
                ", ".join("#%02X%02X%02X" % tuple(c) for c in pal))
        else:
            write_3mf(p, parts)
        files.append(p)
    for ext in ("glb", "ply", "obj"):
        if ext in fmts:
            from .color import export_colored
            m = trimesh.util.concatenate([p[1] for p in parts]) if len(parts) > 1 else parts[0][1]
            files.append(export_colored(m, f"{out_base}.{ext}"))
    return files


def preview_file(parts, files, workdir):
    """Plik do podglądu 3D w GUI: GLB z kolorami jeśli są, inaczej STL."""
    if len(parts) == 1 and has_colors(parts[0][1]):
        from .color import export_colored
        return export_colored(parts[0][1], str(Path(workdir) / "preview.glb"))
    if len(parts) > 1:
        from .color import export_colored
        scene_mesh = trimesh.util.concatenate([p[1] for p in parts if p[0] != "kolek"])
        return export_colored(scene_mesh, str(Path(workdir) / "preview.glb"))
    return files[0]


def run(mode, inputs: dict, o: dict, out_base=None):
    """
    mode: full3d | multiview | text3d | relief | heightmap | lithophane
    inputs: {'image': ścieżka/PIL, 'prompt': str, 'front'/'back'/'left'/'right': ścieżki}
    Zwraca dict: files, preview, report, parts, gcode.
    """
    if mode not in MODES:
        raise ValueError(f"Nieznany tryb {mode}")
    t = time.time()
    workdir = tempfile.mkdtemp(prefix="foto2stl_")
    if out_base is None:
        src = inputs.get("image") if isinstance(inputs.get("image"), (str, Path)) else None
        stem = safe_stem(src) if src else (safe_stem(inputs.get("prompt", "")[:30]) if mode == "text3d" else "model")
        out_base = Path(workdir) / f"{stem}_{mode}"
    out_base = Path(str(out_base).removesuffix(".stl"))
    if o.get("color") and "3mf" not in str(o["formats"]) and mode not in ("lithophane",):
        o["formats"] = str(o["formats"]) + ",3mf,glb"
    parts = build(mode, inputs, o, workdir)
    files = export(parts, out_base, o)
    rep = "\n".join(report(m, n if len(parts) > 1 else "") for n, m, _ in parts)
    if len(files) > 1:
        zp = f"{out_base}.zip"
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            for f in files:
                z.write(f, Path(f).name)
        files.append(zp)
    res = dict(files=files, report=rep, parts=parts, preview=preview_file(parts, files, workdir),
               gcode=None, seconds=time.time() - t, out_base=str(out_base))
    if o["slice"]:
        from .slicer import slice_model, upload
        target = next((f for f in files if f.endswith(".3mf")), files[0]) if len(parts) == 1 else files[0]
        res["gcode"] = slice_model(target, o["slicer_config"], Path(out_base).parent, o["slicer"],
                                   o["slicer_path"], o["slicer_filament"])
        files.append(res["gcode"])
        if o["printer_url"]:
            upload(res["gcode"], o["printer_url"], o["printer_kind"], o["printer_key"], o["start_print"])
    if o["save_history"]:
        try:
            res["history_dir"] = history.save(mode, [f for f in files if not f.endswith(".zip")], o, rep,
                                              inputs.get("image"), inputs.get("prompt", ""))
        except Exception as e:  # noqa: BLE001
            log(f"Nie zapisano historii: {e}")
    from .notify import mqtt_notify
    mqtt_notify(dict(mode=mode, files=[Path(f).name for f in files], report=rep,
                     seconds=round(res["seconds"], 1)), o["mqtt"], o["mqtt_topic"])
    log(f"Gotowe w {res['seconds']:.1f} s\n{rep}")
    return res
