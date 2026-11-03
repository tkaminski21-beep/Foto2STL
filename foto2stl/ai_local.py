"""Lokalne modele AI: Depth Anything V2 (głębia) i TripoSR (pełne 3D)."""
from __future__ import annotations

import os
import sys
import time
import types
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

from .core import has_alpha, load_image, log

_DEPTH = {}
_TSR = {}
_REMBG = None


def estimate_depth(img: Image.Image, model_id: str, device: str) -> np.ndarray:
    """Względna głębia (większa = bliżej) w pełnej precyzji float, w rozmiarze obrazu."""
    from transformers import pipeline
    key = (model_id, device)
    if key not in _DEPTH:
        log(f"Ładuję model głębi {model_id} ({device})…")
        _DEPTH[key] = pipeline("depth-estimation", model=model_id, device=0 if device == "cuda" else -1)
    t = time.time()
    out = _DEPTH[key](img.convert("RGB"))
    pd = out["predicted_depth"]
    pd = pd.squeeze().float().cpu().numpy() if hasattr(pd, "cpu") else np.asarray(pd).squeeze()
    log(f"Mapa głębi w {time.time() - t:.1f} s")
    return np.asarray(Image.fromarray(pd.astype(np.float32), mode="F").resize(img.size, Image.BICUBIC))


def install_mcubes_shim() -> None:
    """Zamiennik 'torchmcubes' oparty na scikit-image (bez kompilacji C++)."""
    try:
        import torchmcubes  # noqa: F401
        return
    except ImportError:
        pass
    import torch
    from skimage.measure import marching_cubes as sk_mc

    def marching_cubes(vol, thresh):
        v = vol.detach().float().cpu().numpy()
        try:
            verts, faces, _, _ = sk_mc(v, level=float(thresh))
        except (ValueError, RuntimeError):
            raise RuntimeError("Nie znaleziono powierzchni obiektu — obniż próg (--mc-threshold).")
        verts = np.ascontiguousarray(verts[:, ::-1])  # torchmcubes: (x,y,z) = (oś2, oś1, oś0)
        return torch.from_numpy(verts.astype(np.float32)), torch.from_numpy(faces.astype(np.int64))

    mod = types.ModuleType("torchmcubes")
    mod.marching_cubes = marching_cubes
    sys.modules["torchmcubes"] = mod
    log("Brak torchmcubes — używam zamiennika ze scikit-image.")


def default_triposr_dir() -> str:
    return os.environ.get("TRIPOSR_DIR", str(Path(__file__).resolve().parent.parent / "TripoSR"))


def load_triposr(triposr_dir: str, device: str):
    if device in _TSR:
        return _TSR[device]
    d = Path(triposr_dir or default_triposr_dir()).expanduser().resolve()
    if not (d / "tsr").is_dir():
        raise FileNotFoundError(
            f"Nie znaleziono TripoSR w '{d}'. Uruchom: git clone https://github.com/VAST-AI-Research/TripoSR "
            "(albo użyj silnika chmurowego: --engine hunyuan3d).")
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))
    install_mcubes_shim()
    import torch
    from tsr.system import TSR
    log(f"Ładuję TripoSR ({device}) — za pierwszym razem pobiera ~1,7 GB…")
    model = TSR.from_pretrained("stabilityai/TripoSR", config_name="config.yaml", weight_name="model.ckpt")
    model.renderer.set_chunk_size(8192)
    model.to(device)
    if device == "cpu":
        torch.set_num_threads(max(1, os.cpu_count() or 4))
    _TSR[device] = model
    return model


def prepare_for_triposr(img: Image.Image, fg_ratio: float) -> Image.Image:
    global _REMBG
    from tsr.utils import remove_background, resize_foreground
    if not has_alpha(img):
        import rembg
        if _REMBG is None:
            _REMBG = rembg.new_session()
        img = remove_background(img.convert("RGB"), _REMBG)
    img = resize_foreground(img.convert("RGBA"), fg_ratio)
    a = np.asarray(img).astype(np.float32) / 255.0
    rgb = a[:, :, :3] * a[:, :, 3:4] + (1 - a[:, :, 3:4]) * 0.5
    return Image.fromarray((rgb * 255).astype(np.uint8))


def triposr(img, device="cpu", triposr_dir=None, mc_res=256, mc_threshold=25.0,
            fg_ratio=0.85, debug_dir=None, **_) -> trimesh.Trimesh:
    import torch
    model = load_triposr(triposr_dir, device)
    src = prepare_for_triposr(load_image(img), fg_ratio)
    if debug_dir:
        Path(debug_dir).mkdir(parents=True, exist_ok=True)
        src.save(Path(debug_dir) / "triposr_input.png")
    t = time.time()
    with torch.no_grad():
        codes = model([src], device=device)
        try:
            meshes = model.extract_mesh(codes, has_vertex_color=True, resolution=mc_res, threshold=mc_threshold)
        except TypeError:
            meshes = model.extract_mesh(codes, resolution=mc_res, threshold=mc_threshold)
    log(f"TripoSR: rekonstrukcja w {time.time() - t:.1f} s")
    m = meshes[0]
    vc = getattr(m.visual, "vertex_colors", None)
    return trimesh.Trimesh(m.vertices, m.faces, vertex_colors=vc, process=True)
