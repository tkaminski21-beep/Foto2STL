"""Wspólne narzędzia: obrazy, mapy wysokości → bryły, kształty, tekst, operacje boolowskie."""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageOps

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic"}


def log(msg: str) -> None:
    print(f"[foto2stl {time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ─────────────────────────── obrazy ───────────────────────────

def load_image(src) -> Image.Image:
    img = src if isinstance(src, Image.Image) else Image.open(src)
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        return img.convert("RGBA")
    return img.convert("RGB")


def fit_size(img: Image.Image, max_side: int) -> Image.Image:
    w, h = img.size
    s = max_side / max(w, h)
    if s < 1:
        img = img.resize((max(2, round(w * s)), max(2, round(h * s))), Image.LANCZOS)
    return img


def has_alpha(img: Image.Image) -> bool:
    return img.mode == "RGBA" and np.asarray(img.split()[-1]).min() < 250


def pick_device(pref: str = "auto") -> str:
    if pref and pref != "auto":
        return pref
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


def normalize(arr: np.ndarray, lo_pct=1.0, hi_pct=99.0, mask=None) -> np.ndarray:
    sel = arr[mask > 0.5] if mask is not None and (mask > 0.5).sum() > 100 else arr
    lo, hi = np.percentile(sel, [lo_pct, hi_pct])
    if hi - lo < 1e-9:
        return np.zeros_like(arr, dtype=np.float32)
    return np.clip((arr - lo) / (hi - lo), 0, 1).astype(np.float32)


def smooth_height(h: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return h.astype(np.float32)
    from skimage.filters import gaussian
    return gaussian(h, sigma=sigma, preserve_range=True).astype(np.float32)


_REMBG = {}


def rembg_session(model: str = "u2net"):
    """Sesja rembg z jawnie wybranym modelem. Od rembg 2.0.7x domyślny jest 'bria-rmbg'
    (1 GB, licencja niekomercyjna) — za ciężki dla Raspberry Pi / uConsole, więc podajemy własny:
    u2net (176 MB, domyślny), u2netp (5 MB, najszybszy), isnet-general-use, birefnet-general…"""
    model = model or "u2net"
    if model not in _REMBG:
        # pierwszy import rembg kompiluje pymatting (numba) — na ARM potrafi to trwać kilka minut
        log(f"Ładuję model usuwania tła (rembg: {model})…")
        import rembg
        _REMBG[model] = rembg.new_session(model)
    return _REMBG[model]


def rembg_mask(img: Image.Image, model: str = "u2net") -> np.ndarray:
    """Maska obiektu 0..1. Jeśli PNG ma już przezroczystość — używa jej zamiast AI."""
    if has_alpha(img):
        return np.asarray(img.split()[-1], dtype=np.float32) / 255.0
    import rembg
    out = rembg.remove(img.convert("RGB"), session=rembg_session(model))
    return np.asarray(out.split()[-1], dtype=np.float32) / 255.0


def threshold_mask(gray: np.ndarray) -> np.ndarray:
    """Maska bez AI (Otsu): obiekt = strona, której jest mniej przy krawędziach."""
    from skimage.filters import threshold_otsu
    t = threshold_otsu(gray)
    m = gray > t
    border = np.concatenate([m[0], m[-1], m[:, 0], m[:, -1]])
    if border.mean() > 0.5:
        m = ~m
    return m.astype(np.float32)


# ─────────────────── mapa wysokości → szczelna bryła ───────────────────

def surfaces_to_mesh(z_bot: np.ndarray, z_top: np.ndarray, px: float, colors=None) -> trimesh.Trimesh:
    """Bryła między dwiema powierzchniami (H, W) nad siatką pikseli o boku px [mm]."""
    H, W = z_top.shape
    jj, ii = np.meshgrid(np.arange(W), np.arange(H))
    x, y = jj * px, (H - 1 - ii) * px
    z_top = np.maximum(z_top, z_bot + 1e-3)
    top = np.stack([x, y, z_top], -1).reshape(-1, 3)
    bot = np.stack([x, y, np.broadcast_to(z_bot, z_top.shape)], -1).reshape(-1, 3)
    N = H * W
    idx = np.arange(N).reshape(H, W)
    a, b = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel()
    c, d = idx[1:, :-1].ravel(), idx[1:, 1:].ravel()
    top_f = np.concatenate([np.stack([a, c, b], 1), np.stack([b, c, d], 1)])
    bot_f = top_f[:, ::-1] + N
    ring = np.concatenate([idx[0, :], idx[1:, -1], idx[-1, -2::-1], idx[-2:0:-1, 0]])
    p, q = ring, np.roll(ring, -1)
    wall = np.concatenate([np.stack([p, q, p + N], 1), np.stack([q, q + N, p + N], 1)])
    vc = None
    if colors is not None:
        c8 = np.asarray(colors, dtype=np.uint8).reshape(-1, colors.shape[-1])
        if c8.shape[1] == 3:
            c8 = np.hstack([c8, np.full((len(c8), 1), 255, np.uint8)])
        vc = np.vstack([c8, c8])
    mesh = trimesh.Trimesh(np.vstack([top, bot]), np.vstack([top_f, bot_f, wall]),
                           vertex_colors=vc, process=False)
    mesh.fix_normals()
    return mesh


def heightmap_to_mesh(h, width_mm, base_mm, relief_mm, colors=None) -> trimesh.Trimesh:
    H, W = h.shape
    px = width_mm / (W - 1)
    return surfaces_to_mesh(np.zeros_like(h), base_mm + h * relief_mm, px, colors)


def image_colors(img: Image.Image, shape) -> np.ndarray:
    H, W = shape
    return np.asarray(img.convert("RGB").resize((W, H), Image.BILINEAR), dtype=np.uint8)


# ─────────────────────────── kształty 2D ───────────────────────────

def shape_polygon(name: str, w: float, h: float):
    """Kształt w układzie mm, wpisany w prostokąt 0..w × 0..h."""
    from shapely import affinity
    from shapely.geometry import Point, Polygon, box
    cx, cy = w / 2, h / 2
    s = min(w, h)
    if name in ("rect", "prostokat", None, ""):
        return box(0, 0, w, h)
    if name == "rounded":
        r = s * 0.12
        return box(r, r, w - r, h - r).buffer(r, quad_segs=16)
    if name == "circle":
        return Point(cx, cy).buffer(s / 2, quad_segs=64)
    if name == "oval":
        return affinity.scale(Point(cx, cy).buffer(1, quad_segs=64), w / 2, h / 2)
    if name == "hexagon":
        a = np.radians(np.arange(6) * 60 + 30)
        return Polygon(np.c_[cx + s / 2 * np.cos(a), cy + s / 2 * np.sin(a)])
    if name == "heart":
        t = np.linspace(0, 2 * np.pi, 240)
        x = 16 * np.sin(t) ** 3
        y = 13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t)
        poly = Polygon(np.c_[x, y]).buffer(0)
        minx, miny, maxx, maxy = poly.bounds
        k = min(w / (maxx - minx), h / (maxy - miny))
        poly = affinity.scale(poly, k, k, origin=(0, 0))
        minx, miny, maxx, maxy = poly.bounds
        return affinity.translate(poly, cx - (minx + maxx) / 2, cy - (miny + maxy) / 2)
    raise ValueError(f"Nieznany kształt: {name}")


def mask_polygon(mask: np.ndarray, px: float, margin_mm: float = 1.0, keep_all=False):
    """Kontur obiektu z maski → wielokąt shapely w mm (do przycięcia reliefu)."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    from skimage.measure import find_contours
    H, _ = mask.shape
    m = np.pad(mask > 0.5, 1)
    polys = []
    for c in find_contours(m.astype(float), 0.5):
        if len(c) < 8:
            continue
        rows, cols = c[:, 0] - 1, c[:, 1] - 1
        p = Polygon(np.c_[cols * px, (H - 1 - rows) * px]).buffer(0)
        if p.area > (5 * px) ** 2:
            polys.append(p)
    if not polys:
        raise ValueError("Nie wykryto konturu obiektu — spróbuj innego zdjęcia lub kształtu.")
    # kontury wewnętrzne (dziury) też trafiają do listy — symetryczna różnica je odejmuje
    polys.sort(key=lambda p: -p.area)
    g = polys[0]
    for p in polys[1:]:
        g = g.symmetric_difference(p)
    g = g.buffer(margin_mm).buffer(0)
    if not keep_all and g.geom_type == "MultiPolygon":
        g = max(g.geoms, key=lambda p: p.area)
    return g.simplify(px * 0.5)


def extrude(poly, z0: float, z1: float) -> trimesh.Trimesh:
    geoms = list(poly.geoms) if hasattr(poly, "geoms") else [poly]
    parts = [trimesh.creation.extrude_polygon(g, z1 - z0) for g in geoms if g.area > 1e-6]
    m = trimesh.util.concatenate(parts) if len(parts) > 1 else parts[0]
    m.apply_translation([0, 0, z0])
    return m


def text_polygon(text: str, size_mm: float, font: str | None = None, bold=True):
    """Tekst → wielokąt shapely (wysokość wersalików ≈ size_mm), wycentrowany w (0,0)."""
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath
    from shapely import affinity
    from shapely.geometry import Polygon
    fp = FontProperties(family=font or "DejaVu Sans", weight="bold" if bold else "normal")
    g = Polygon()
    for line_no, line in enumerate(text.split("\n")):
        tp = TextPath((0, -line_no * 1.25), line, size=1.0, prop=fp)
        lg = Polygon()
        for ring in tp.to_polygons():
            if len(ring) >= 3:
                lg = lg.symmetric_difference(Polygon(ring).buffer(0))
        minx, _, maxx, _ = lg.bounds if not lg.is_empty else (0, 0, 0, 0)
        g = g.union(affinity.translate(lg, -(minx + maxx) / 2, 0))
    if g.is_empty:
        raise ValueError("Pusty tekst")
    g = affinity.scale(g, size_mm / 0.73, size_mm / 0.73, origin=(0, 0))
    minx, miny, maxx, maxy = g.bounds
    return affinity.translate(g, -(minx + maxx) / 2, -(miny + maxy) / 2).buffer(0)


# ─────────────────────────── boolowskie ───────────────────────────

def _bool(op, meshes):
    try:
        out = getattr(trimesh.boolean, op)(meshes, engine="manifold")
        if out is not None and len(out.faces):
            return out
    except Exception as e:  # noqa: BLE001
        log(f"Operacja boolowska {op} nie powiodła się ({e}) — pomijam (pip install manifold3d)")
    return meshes[0]


def union(*m):
    return _bool("union", list(m))


def difference(a, *b):
    return _bool("difference", [a, *b])


def intersection(a, b):
    return _bool("intersection", [a, b])


def transfer_colors(dst: trimesh.Trimesh, src: trimesh.Trimesh) -> trimesh.Trimesh:
    """Przenosi kolory wierzchołków z src na dst (najbliższy sąsiad)."""
    try:
        vc = src.visual.vertex_colors
    except Exception:  # noqa: BLE001
        return dst
    if vc is None or len(vc) != len(src.vertices):
        return dst
    from scipy.spatial import cKDTree
    _, i = cKDTree(src.vertices).query(dst.vertices)
    dst.visual = trimesh.visual.ColorVisuals(dst, vertex_colors=np.asarray(vc)[i])
    return dst


def has_colors(mesh: trimesh.Trimesh) -> bool:
    try:
        if mesh.visual.kind != "vertex":
            return False
        vc = np.asarray(mesh.visual.vertex_colors)[:, :3]
        return vc.std() > 1
    except Exception:  # noqa: BLE001
        return False


def safe_stem(p) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in Path(str(p)).stem)[:60] or "model"


def plane_cut(mesh: trimesh.Trimesh, origin, normal):
    """Zostawia część bryły po stronie, w którą wskazuje normal (przekrój zamknięty). Manifold → fallback trimesh."""
    normal = np.asarray(normal, float) / np.linalg.norm(normal)
    try:
        import manifold3d as mf
        mm = mf.Manifold(mf.Mesh(vert_properties=np.asarray(mesh.vertices, np.float32),
                                 tri_verts=np.asarray(mesh.faces, np.uint32)))
        if not hasattr(mm, "status") or mm.status() == mf.Error.NoError:
            out = mm.trim_by_plane(tuple(normal), float(np.dot(normal, origin))).to_mesh()
            v = np.asarray(out.vert_properties)[:, :3]
            if len(v):
                return trimesh.Trimesh(v, np.asarray(out.tri_verts), process=True)
            return None
    except Exception:  # noqa: BLE001
        pass
    return mesh.slice_plane(origin, normal, cap=True)
