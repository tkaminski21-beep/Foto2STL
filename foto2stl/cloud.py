"""
Silniki chmurowe przez darmowe GPU na Hugging Face Spaces (gradio_client).

API Space'ów potrafi się zmieniać — dlatego wywołanie jest „samoopisujące”:
program czyta listę parametrów endpointu i wypełnia tylko te, które zna,
a resztę zostawia z wartościami domyślnymi. Podgląd API:  foto2stl --cloud-api tencent/Hunyuan3D-2
"""
from __future__ import annotations

import os
import random
from pathlib import Path

import trimesh

from .core import log

MESH_EXT = (".glb", ".gltf", ".obj", ".ply", ".stl", ".off")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")

# Profile image→3D
ENGINES = {
    "hunyuan3d": dict(space="tencent/Hunyuan3D-2", api="/shape_generation",
                      image="image", set={"check_box_rembg": True, "randomize_seed": True,
                                          "octree_resolution": 256, "steps": 30}),
    "hunyuan3d-color": dict(space="tencent/Hunyuan3D-2", api="/generation_all",
                            image="image", set={"check_box_rembg": True, "randomize_seed": True,
                                                "octree_resolution": 256, "steps": 30}, colored=True),
    "hunyuan3d-mv": dict(space="tencent/Hunyuan3D-2mv", api="/shape_generation",
                         views={"front": "mv_image_front", "back": "mv_image_back",
                                "left": "mv_image_left", "right": "mv_image_right"},
                         set={"check_box_rembg": True, "randomize_seed": True, "octree_resolution": 256}),
}

# Profile tekst→obraz (do trybu tekst→3D)
TEXT2IMG = {
    "flux": dict(space="black-forest-labs/FLUX.1-schnell", api="/infer", prompt="prompt",
                 set={"randomize_seed": True, "width": 1024, "height": 1024, "num_inference_steps": 4}),
}

PROMPT_SUFFIX = (", single object, centered, full view, three-quarter view from slightly above, "
                 "plain white background, soft studio lighting, matte material, no shadows, 3D render")


def _client(space: str, token: str | None = None):
    from gradio_client import Client
    token = token or os.environ.get("HF_TOKEN")
    try:
        return Client(space, token=token, verbose=False)
    except TypeError:  # starsze gradio_client
        return Client(space, hf_token=token)


def describe_api(space: str, token=None) -> str:
    c = _client(space, token)
    info = c.view_api(print_info=False, return_format="dict")
    lines = [f"Space: {space}"]
    for name, ep in (info.get("named_endpoints") or {}).items():
        params = ", ".join(f"{p.get('parameter_name') or p.get('label')}"
                           f"{'' if p.get('parameter_has_default') else '*'}" for p in ep.get("parameters", []))
        lines.append(f"  {name}({params})")
    lines.append("(* = wymagany)")
    return "\n".join(lines)


def call_space(space: str, api: str, values: dict, token=None):
    """Wywołuje endpoint, dopasowując podane wartości do jego parametrów."""
    from gradio_client import handle_file
    c = _client(space, token)
    info = c.view_api(print_info=False, return_format="dict")
    eps = info.get("named_endpoints") or {}
    if api not in eps:
        raise RuntimeError(f"Space {space} nie ma endpointu {api}. Dostępne: {', '.join(eps) or 'brak'}. "
                           f"Sprawdź: foto2stl --cloud-api {space}")
    kwargs = {}
    for p in eps[api].get("parameters", []):
        name = p.get("parameter_name") or p.get("label")
        if name in values and values[name] is not None:
            v = values[name]
            if isinstance(v, (str, Path)) and Path(str(v)).suffix.lower() in IMAGE_EXT and Path(str(v)).exists():
                v = handle_file(str(v))
            kwargs[name] = v
        elif not p.get("parameter_has_default"):
            kwargs[name] = None
    log(f"Chmura: {space} {api} (czekam na kolejkę GPU…)")
    return c.predict(api_name=api, **kwargs)


def find_files(obj, exts) -> list[str]:
    found = []
    if isinstance(obj, (list, tuple)):
        for o in obj:
            found += find_files(o, exts)
    elif isinstance(obj, dict):
        for k in ("path", "value", "name", "url"):
            if k in obj:
                found += find_files(obj[k], exts)
    elif isinstance(obj, str) and obj.lower().endswith(exts) and os.path.exists(obj):
        found.append(obj)
    return found


def load_any_mesh(path: str) -> trimesh.Trimesh:
    loaded = trimesh.load(path, force="scene")
    meshes = [g for g in loaded.dump() if isinstance(g, trimesh.Trimesh)] if hasattr(loaded, "dump") \
        else [loaded]
    colored = []
    for m in meshes:
        try:
            if m.visual.kind == "texture":
                m.visual = m.visual.to_color()
        except Exception:  # noqa: BLE001
            pass
        colored.append(m)
    mesh = trimesh.util.concatenate(colored) if len(colored) > 1 else colored[0]
    # glTF jest Y-up, drukarki Z-up
    if path.lower().endswith((".glb", ".gltf")):
        mesh.apply_transform(trimesh.transformations.rotation_matrix(1.5707963, [1, 0, 0]))
    return mesh


def image_to_3d(images: dict, engine: str = "hunyuan3d", token=None, space=None, api=None,
                image_param="image", seed=None) -> trimesh.Trimesh:
    """images: {'image': ścieżka} albo {'front':…, 'back':…, 'left':…, 'right':…} dla multi-view."""
    if space:  # własny Space
        prof = dict(space=space, api=api or "/predict", image=image_param, set={})
    else:
        if engine not in ENGINES:
            raise ValueError(f"Nieznany silnik chmurowy: {engine}. Dostępne: {', '.join(ENGINES)}")
        prof = ENGINES[engine]
    values = dict(prof.get("set", {}))
    if seed is not None:
        values.update(seed=int(seed), randomize_seed=False)
    if "views" in prof:
        for view, pname in prof["views"].items():
            if images.get(view):
                values[pname] = images[view]
        if not any(images.get(v) for v in prof["views"]):
            raise ValueError("Tryb wielu widoków wymaga co najmniej zdjęcia z przodu.")
    else:
        values[prof["image"]] = images.get("image") or images.get("front")
    result = call_space(prof["space"], prof["api"], values, token)
    files = find_files(result, MESH_EXT)
    if not files:
        raise RuntimeError(f"Space nie zwrócił pliku 3D (odpowiedź: {str(result)[:300]})")
    # przy generation_all pierwszy plik bywa bez tekstury — wybierz ostatni (z teksturą)
    path = files[-1] if prof.get("colored") else files[0]
    log(f"Chmura: pobrano {Path(path).name}")
    return load_any_mesh(path)


def text_to_image(prompt: str, out_path: str, generator="flux", token=None, seed=None, raw=False) -> str:
    prof = TEXT2IMG[generator]
    values = dict(prof["set"])
    values[prof["prompt"]] = prompt if raw else prompt + PROMPT_SUFFIX
    if seed is not None:
        values.update(seed=int(seed), randomize_seed=False)
    else:
        values["seed"] = random.randint(0, 2**31 - 1)
    result = call_space(prof["space"], prof["api"], values, token)
    files = find_files(result, IMAGE_EXT)
    if not files:
        raise RuntimeError(f"Generator obrazu nic nie zwrócił ({str(result)[:300]})")
    from PIL import Image
    Image.open(files[0]).convert("RGB").save(out_path)
    log(f"Obraz z opisu zapisany: {out_path}")
    return out_path
