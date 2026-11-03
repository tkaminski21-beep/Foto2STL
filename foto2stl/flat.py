"""Tryby płaskie: relief (AI-głębia) i heightmap — z kształtami, konturem, ramką, brelokiem, napisem."""
from __future__ import annotations

import numpy as np
import trimesh

from .core import (difference, extrude, fit_size, heightmap_to_mesh, image_colors, intersection,
                   load_image, log, mask_polygon, normalize, rembg_mask, shape_polygon, smooth_height,
                   text_polygon, threshold_mask, union)


def build_height(img, mode, o):
    img = fit_size(load_image(img), o["res"])
    mask = None
    need_mask = o.get("remove_bg") or o.get("shape") == "contour"
    if mode == "relief":
        from .ai_local import estimate_depth
        depth = estimate_depth(img, o["depth_model"], o["device"])
        if need_mask:
            mask = rembg_mask(img)
        h = normalize(depth, mask=mask)
        if mask is not None and o.get("remove_bg"):
            h = h * smooth_height(mask, 1.5)
    else:  # heightmap
        g = np.asarray(img.convert("L"), dtype=np.float32) / 255.0
        h = g
        if need_mask:
            from .core import has_alpha
            mask = (np.asarray(img.split()[-1], np.float32) / 255.0) if has_alpha(img) else threshold_mask(g)
            if has_alpha(img):
                h = h * mask
    if o.get("invert"):
        h = 1 - h
    h = np.power(np.clip(h, 0, 1), o.get("gamma", 1.0))
    return smooth_height(h, o["smooth"]), mask, img


def make_flat(img, mode, o) -> trimesh.Trimesh:
    h, mask, im = build_height(img, mode, o)
    H, W = h.shape
    px = o["width_mm"] / (W - 1)
    colors = image_colors(im, h.shape) if o.get("color") else None
    mesh = heightmap_to_mesh(h, o["width_mm"], o["base_mm"], o["relief_mm"], colors)
    top = o["base_mm"] + o["relief_mm"]
    w, hh = (W - 1) * px, (H - 1) * px

    shape = o.get("shape") or "rect"
    if shape == "contour":
        poly = mask_polygon(mask, px, margin_mm=o.get("contour_margin_mm", 2.0))
    else:
        poly = shape_polygon(shape, w, hh)
    if shape != "rect":
        src = mesh
        mesh = intersection(mesh, extrude(poly, -1, top + 1))
        if colors is not None:
            from .core import transfer_colors
            transfer_colors(mesh, src)

    if o.get("frame_mm", 0) > 0:
        ring = poly.difference(poly.buffer(-o["frame_mm"]))
        mesh = _keep_colors(union, mesh, extrude(ring, 0, top + o.get("frame_extra_mm", 0.5)))

    if o.get("keychain"):
        mesh = add_keychain(mesh, poly, o)

    if o.get("back_text"):
        tp = text_polygon(o["back_text"], o.get("text_mm", 6.0))
        from shapely import affinity
        c = poly.centroid
        tp = affinity.scale(tp, -1, 1, origin=(0, 0))  # lustro: czytelne po odwróceniu
        tp = affinity.translate(tp, c.x, c.y)
        depth = min(o.get("engrave_mm", 0.6), o["base_mm"] * 0.5)
        mesh = _keep_colors(difference, mesh, extrude(tp, -1, depth))
        log(f"Wygrawerowano napis na spodzie: „{o['back_text']}”")
    return mesh


def _keep_colors(op, mesh, other):
    from .core import has_colors, transfer_colors
    out = op(mesh, other)
    if has_colors(mesh) and out is not mesh:
        transfer_colors(out, mesh)
    return out


def add_keychain(mesh, poly, o):
    from shapely.geometry import Point
    r_out = o.get("ring_mm", 5.0)
    r_in = o.get("hole_mm", 4.0) / 2
    from shapely.geometry import LineString
    minx, miny, maxx, maxy = poly.bounds
    cx = (minx + maxx) / 2
    # górna krawędź kształtu dokładnie nad środkiem → tam doczepiamy oczko
    hit = LineString([(cx, miny - 1), (cx, maxy + 1)]).intersection(poly)
    top_y = hit.bounds[3] if not hit.is_empty else maxy
    cy = top_y + r_out * 0.35
    ring_poly = Point(cx, cy).buffer(r_out, quad_segs=32)
    t = o.get("keychain_t_mm") or o["base_mm"] + min(o["relief_mm"], 1.5)
    out = _keep_colors(union, mesh, extrude(ring_poly, 0, t))
    hole = trimesh.creation.cylinder(radius=r_in, height=200, sections=32)
    hole.apply_translation([cx, cy + r_out * 0.1, 0])
    log("Dodano oczko breloka")
    return _keep_colors(difference, out, hole)
