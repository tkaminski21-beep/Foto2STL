"""Lokalne modele AI: Depth Anything V2 (głębia) i TripoSR (pełne 3D)."""
from __future__ import annotations

import os
import re
import sys
import time
import types
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

from .core import has_alpha, load_image, log, rembg_session

_DEPTH = {}
_TSR = {}


def estimate_depth(img: Image.Image, model_id: str, device: str) -> np.ndarray:
    """Względna głębia (większa = bliżej) w pełnej precyzji float, w rozmiarze obrazu."""
    from transformers import pipeline
    key = (model_id, device)
    if key not in _DEPTH:
        log(f"Ładuję model głębi {model_id} ({device})…")
        try:
            _DEPTH[key] = pipeline("depth-estimation", model=model_id, device=0 if device == "cuda" else -1)
        except OSError as e:
            raise RuntimeError(
                f"Nie mogę wczytać modelu głębi '{model_id}'. Za pierwszym razem pobiera się on z huggingface.co "
                "(Small ≈ 100 MB) — sprawdź internet; potem działa offline z ~/.cache/huggingface. "
                f"Można też podać lokalny katalog: --depth-model ŚCIEŻKA.\nSzczegóły: {e}") from e
    t = time.time()
    out = _DEPTH[key](img.convert("RGB"))
    pd = out["predicted_depth"]
    pd = pd.squeeze().float().cpu().numpy() if hasattr(pd, "cpu") else np.asarray(pd).squeeze()
    log(f"Mapa głębi w {time.time() - t:.1f} s")
    return np.asarray(Image.fromarray(pd.astype(np.float32)).resize(img.size, Image.BICUBIC))


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


def _ram_gb():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 2**20
    except (OSError, ValueError):
        pass
    return None


def default_triposr_dir() -> str:
    # w wersji .exe (PyInstaller) TripoSR leży obok Foto2STL.exe, a nie obok kodu w _internal
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return os.environ.get("TRIPOSR_DIR", str(base / "TripoSR"))


TRIPOSR_REPO = "stabilityai/TripoSR"


def _read_weights(path: str, trusted: bool):
    """torch.load z mapowaniem pliku (mmap): wagi nie są kopiowane do RAM-u, tylko czytane z dysku
    na żądanie. Od torch 2.6 domyślne jest weights_only=True; pełne odpakowanie pickle dopuszczamy
    tylko dla oficjalnego pliku TripoSR, gdyby zawierał coś poza samymi tensorami."""
    import pickle
    import torch
    for weights_only in ((True, False) if trusted else (True,)):
        try:
            try:
                return torch.load(path, map_location="cpu", mmap=True, weights_only=weights_only)
            except RuntimeError as e:  # stary format pliku (nie-zip) nie obsługuje mmap
                if "mmap" not in str(e) and "zip" not in str(e):
                    raise
                return torch.load(path, map_location="cpu", weights_only=weights_only)
        except pickle.UnpicklingError:
            if not weights_only or not trusted:
                raise
            log("model.ckpt zawiera obiekty spoza tensorów — wczytuję bez weights_only (oficjalny plik TripoSR)")


# Checkpoint TripoSR zapisano pod transformers 4.35. transformers 5 przemianował moduły ViT (enkoder DINO
# w TripoSR), np. encoder.layer.N.attention.attention.query → layers.N.attention.q_proj — kształty bez zmian.
# Sam transformers stosuje te reguły tylko we własnym from_pretrained (conversion_mapping.py, "ViTModel"),
# a TripoSR wczytuje wagi zwykłym load_state_dict, więc tłumaczymy nazwy sami. Kolejność ma znaczenie.
_VIT_PREFIX = "image_tokenizer.model."
_VIT_RENAMES = [
    (re.compile(r"\.encoder\.layer\.(\d+)\."), r".layers.\1."),
    (re.compile(r"\.attention\.attention\.query\."), ".attention.q_proj."),
    (re.compile(r"\.attention\.attention\.key\."), ".attention.k_proj."),
    (re.compile(r"\.attention\.attention\.value\."), ".attention.v_proj."),
    (re.compile(r"\.attention\.output\.dense\."), ".attention.o_proj."),
    (re.compile(r"\.intermediate\.dense\."), ".mlp.fc1."),
    (re.compile(r"\.output\.dense\."), ".mlp.fc2."),
]


def adapt_vit_keys(state: dict, model_keys) -> dict:
    """Dopasowuje nazwy wag enkodera ViT z checkpointu do zainstalowanej wersji transformers."""
    model_keys = set(model_keys)
    if set(state) == model_keys:
        return state
    out = {}
    for k, v in state.items():
        if k.startswith(_VIT_PREFIX) and k not in model_keys:
            new = k[len(_VIT_PREFIX) - 1:]  # zostaw kropkę na początku dla wzorców
            for pat, rep in _VIT_RENAMES:
                new = pat.sub(rep, new)
            k = _VIT_PREFIX[:-1] + new
        out[k] = v
    missing, unexpected = model_keys - set(out), set(out) - model_keys
    if missing or unexpected:
        import transformers
        raise RuntimeError(
            f"Wagi TripoSR nie pasują do transformers {transformers.__version__} "
            f"(brak {len(missing)} kluczy, np. {sorted(missing)[:2]}; nadmiarowe {len(unexpected)}, "
            f"np. {sorted(unexpected)[:2]}). Obejście: pip install \"transformers<5\" w osobnym venv "
            "albo silnik chmurowy --engine hunyuan3d.")
    log("TripoSR: dopasowano nazwy wag enkodera DINO do transformers 5")
    return out


def _tsr_from_pretrained(repo: str):
    """Jak TSR.from_pretrained, ale ~1,6 GB mniej RAM-u: wagi trafiają do modelu bez kopii (assign=True).
    Oryginał trzyma naraz model i drugi egzemplarz wag — szczyt ~4,5 GB, za dużo na Pi/uConsole z 4 GB."""
    import gc
    from huggingface_hub import hf_hub_download
    from omegaconf import OmegaConf
    from tsr.system import TSR
    if os.path.isdir(repo):
        cfg_path, ckpt_path = os.path.join(repo, "config.yaml"), os.path.join(repo, "model.ckpt")
    else:
        try:
            cfg_path = hf_hub_download(repo_id=repo, filename="config.yaml")
            ckpt_path = hf_hub_download(repo_id=repo, filename="model.ckpt")
        except Exception as e:  # noqa: BLE001 — brak sieci, zablokowany huggingface.co, przerwane pobieranie
            raise RuntimeError(f"Nie mogę pobrać TripoSR z huggingface.co ({repo}): {e}\n"
                               "Sprawdź internet — wagi (~1,7 GB) pobierają się raz do ~/.cache/huggingface. "
                               "Albo użyj silnika chmurowego: --engine hunyuan3d") from e
    cfg = OmegaConf.load(cfg_path)
    OmegaConf.resolve(cfg)
    model = TSR(cfg)
    state = _read_weights(ckpt_path, trusted=(repo == TRIPOSR_REPO))
    state = adapt_vit_keys(state, model.state_dict().keys())
    model.load_state_dict(state, assign=True)
    del state
    gc.collect()
    return model.eval()


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
    log(f"Ładuję TripoSR ({device}) — za pierwszym razem pobiera ~1,7 GB…")
    model = _tsr_from_pretrained(TRIPOSR_REPO)
    model.renderer.set_chunk_size(8192)
    model.to(device)
    if device == "cpu":
        torch.set_num_threads(max(1, os.cpu_count() or 4))
    _TSR[device] = model
    return model


def prepare_for_triposr(img: Image.Image, fg_ratio: float, rembg_model: str = "u2net") -> Image.Image:
    from tsr.utils import remove_background, resize_foreground
    if not has_alpha(img):
        img = remove_background(img.convert("RGB"), rembg_session(rembg_model))
    img = resize_foreground(img.convert("RGBA"), fg_ratio)
    a = np.asarray(img).astype(np.float32) / 255.0
    rgb = a[:, :, :3] * a[:, :, 3:4] + (1 - a[:, :, 3:4]) * 0.5
    return Image.fromarray((rgb * 255).astype(np.uint8))


def triposr(img, device="cpu", triposr_dir=None, mc_res=256, mc_threshold=25.0,
            fg_ratio=0.85, debug_dir=None, rembg_model="u2net", **_) -> trimesh.Trimesh:
    import torch
    ram = _ram_gb()
    if device == "cpu" and ram and ram < 6:
        log(f"Uwaga: {ram:.1f} GB RAM. TripoSR na CPU potrzebuje ok. 4 GB przy --mc-res 128 i 5 GB przy 256 "
            f"(teraz: {mc_res}). Na Raspberry Pi / uConsole: --mc-res 128 i swap, albo chmura: --engine hunyuan3d.")
    model = load_triposr(triposr_dir, device)
    src = prepare_for_triposr(load_image(img), fg_ratio, rembg_model)
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
