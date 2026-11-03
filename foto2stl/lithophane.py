"""Litofany: płaskie (z ramką i kształtem), wygięte, cylindryczne (lampka) i kolorowe CMY."""
from __future__ import annotations

import numpy as np
import trimesh
from PIL import Image, ImageOps

from .core import (extrude, fit_size, intersection, load_image, log, shape_polygon,
                   smooth_height, surfaces_to_mesh, union)


def litho_map(img, res, smooth, invert=False) -> tuple[np.ndarray, Image.Image]:
    img = fit_size(load_image(img), res)
    g = np.asarray(ImageOps.autocontrast(img.convert("L"), cutoff=1), dtype=np.float32) / 255.0
    h = g if invert else 1 - g  # ciemne = grubiej
    return smooth_height(h, smooth), img


def flat(h, width_mm, min_mm, max_mm, shape="rect", frame_mm=0.0, frame_t_mm=None):
    H, W = h.shape
    px = width_mm / (W - 1)
    mesh = surfaces_to_mesh(np.zeros_like(h), min_mm + h * (max_mm - min_mm), px)
    w, hh = (W - 1) * px, (H - 1) * px
    poly = shape_polygon(shape, w, hh)
    if shape not in ("rect", None, ""):
        mesh = intersection(mesh, extrude(poly, -1, max_mm + 1))
    if frame_mm > 0:
        ring = poly.difference(poly.buffer(-frame_mm))
        mesh = union(mesh, extrude(ring, 0, frame_t_mm or max_mm + 1.0))
    return mesh


def bend(mesh: trimesh.Trimesh, angle_deg: float, thickness_inward=True):
    """Wygina płaski litofan (x = łuk) w wycinek walca o kącie angle_deg. Gładka strona na zewnątrz."""
    v = mesh.vertices.copy()
    xmin, xmax = v[:, 0].min(), v[:, 0].max()
    W = xmax - xmin
    R = W / np.radians(angle_deg)
    theta = (v[:, 0] - (xmin + xmax) / 2) / R
    r = R - v[:, 2] if thickness_inward else R + v[:, 2]
    out = np.c_[-r * np.sin(theta), r * np.cos(theta), v[:, 1]]  # obraz czytelny od zewnątrz
    m = trimesh.Trimesh(out, mesh.faces.copy(), process=False)
    m.fix_normals()
    return m


def cylinder(h, circumference_mm, min_mm, max_mm, base_mm=0.0, rim_mm=0.0):
    """Zamknięty litofan-cylinder (abażur): obraz dookoła, czytelny z zewnątrz."""
    H, W = h.shape
    R = circumference_mm / (2 * np.pi)
    px = circumference_mm / W
    th = -np.arange(W) / W * 2 * np.pi
    zs = (H - 1 - np.arange(H)) * px
    t = min_mm + h * (max_mm - min_mm)
    Z, TH = np.meshgrid(zs, th, indexing="ij")
    outer = np.stack([R * np.sin(TH), R * np.cos(TH), Z], -1).reshape(-1, 3)
    ri = R - t
    inner = np.stack([ri * np.sin(TH), ri * np.cos(TH), Z], -1).reshape(-1, 3)
    N = H * W
    idx = np.arange(N).reshape(H, W)
    nxt = np.roll(idx, -1, axis=1)
    a, b, c, d = idx[:-1].ravel(), nxt[:-1].ravel(), idx[1:].ravel(), nxt[1:].ravel()
    f_out = np.concatenate([np.stack([a, c, b], 1), np.stack([b, c, d], 1)])
    f_in = f_out[:, ::-1] + N
    top_o, top_n = idx[0], nxt[0]
    bot_o, bot_n = idx[-1], nxt[-1]
    caps = np.concatenate([
        np.stack([top_o, top_n, top_o + N], 1), np.stack([top_n, top_n + N, top_o + N], 1),
        np.stack([bot_o, bot_o + N, bot_n], 1), np.stack([bot_n, bot_o + N, bot_n + N], 1)])
    mesh = trimesh.Trimesh(np.vstack([outer, inner]), np.vstack([f_out, f_in, caps]), process=False)
    mesh.fix_normals()
    zmin = zs.min()
    parts = [mesh]
    if rim_mm > 0:  # pełne pierścienie u góry i dołu = sztywność
        for z0 in (zmin - rim_mm, zs.max()):
            ring = trimesh.creation.annulus(r_min=R - max_mm, r_max=R + 0.0, height=rim_mm + 0.2, sections=W)
            ring.apply_translation([0, 0, z0 + rim_mm / 2 + (0.1 if z0 < zmin else -0.1)])
            parts.append(ring)
    if base_mm > 0:  # dno z otworem na kabel/LED
        disc = trimesh.creation.annulus(r_min=min(10.0, R * 0.4), r_max=R - 0.01, height=base_mm, sections=W)
        disc.apply_translation([0, 0, zmin - (rim_mm if rim_mm > 0 else 0) - base_mm / 2 + 0.1])
        parts.append(disc)
    if len(parts) > 1:
        mesh = union(*parts)
    return mesh


def color_cmy(img, width_mm, res, smooth, white_min=0.6, white_max=2.6, layer_max=0.6):
    """
    Kolorowy litofan do druku wielomateriałowego: biały litofan + 3 cienkie warstwy C, M, Y.
    Zwraca listę (nazwa, siatka, kolor RGBA).
    """
    img = fit_size(load_image(img), res).convert("RGB")
    rgb = np.asarray(img, dtype=np.float32) / 255.0
    lum = np.asarray(ImageOps.autocontrast(img.convert("L"), cutoff=1), dtype=np.float32) / 255.0
    H, W = lum.shape
    px = width_mm / (W - 1)
    # saturacja oddziela kolor od jasności: szare piksele nie dostają farby
    sat = rgb.max(-1) - rgb.min(-1)
    cmy = (1 - rgb) - (1 - rgb).min(-1, keepdims=True)
    cmy = smooth_height(np.clip(cmy * (sat[..., None] > 0.05), 0, 1).reshape(H, W * 3), smooth).reshape(H, W, 3)
    z = np.zeros((H, W), np.float32)
    parts = []
    white = smooth_height(white_min + (1 - lum) * (white_max - white_min), smooth)
    parts.append(("bialy", surfaces_to_mesh(z, white, px), (255, 255, 255, 255)))
    z = white
    for i, (name, col) in enumerate((("cyan", (0, 174, 239, 255)), ("magenta", (236, 0, 140, 255)),
                                     ("zolty", (255, 230, 0, 255)))):
        top = z + 0.02 + cmy[..., i] * layer_max
        parts.append((name, surfaces_to_mesh(z, top, px), col))
        z = top
    log("Kolorowy litofan: 4 części (biały + C/M/Y) — przypisz filamenty w slicerze")
    return parts
