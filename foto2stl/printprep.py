"""Przygotowanie do druku: naprawa, skala, podstawa, wydrążanie, orientacja, podział na części."""
from __future__ import annotations

import numpy as np
import trimesh

from .core import difference, extrude, log, plane_cut, text_polygon, union


class Xf:
    """Śledzi przekształcenia, żeby na końcu przenieść kolory z oryginału."""
    def __init__(self):
        self.M = np.eye(4)

    def apply(self, mesh, M):
        mesh.apply_transform(M)
        self.M = M @ self.M
        return mesh


def keep_largest(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    parts = mesh.split(only_watertight=False)
    if len(parts) > 1:
        log(f"Usuwam {len(parts) - 1} drobnych odłamków")
        mesh = max(parts, key=lambda m: len(m.faces))
    return mesh


def scale_to(mesh, xf: Xf, height_mm=None, size_mm=None):
    ext = mesh.extents
    target, cur = (height_mm, ext[2]) if height_mm else (size_mm, ext.max())
    if target and cur > 0:
        xf.apply(mesh, trimesh.transformations.scale_matrix(target / cur))
    return mesh


def place_on_bed(mesh, xf: Xf | None = None):
    b = mesh.bounds
    M = trimesh.transformations.translation_matrix(
        [-(b[0, 0] + b[1, 0]) / 2, -(b[0, 1] + b[1, 1]) / 2, -b[0, 2]])
    return xf.apply(mesh, M) if xf else mesh.apply_transform(M)


def rotate(mesh, xf: Xf, rx=0.0, ry=0.0, rz=0.0):
    for ang, ax in ((rx, [1, 0, 0]), (ry, [0, 1, 0]), (rz, [0, 0, 1])):
        if ang:
            xf.apply(mesh, trimesh.transformations.rotation_matrix(np.radians(ang), ax, mesh.centroid))
    return mesh


def flat_base(mesh, cut_mm: float):
    if cut_mm <= 0:
        return mesh
    try:
        cut = plane_cut(mesh, [0, 0, mesh.bounds[0, 2] + cut_mm], [0, 0, 1])
        if cut is not None and len(cut.faces):
            return cut
    except Exception as e:  # noqa: BLE001
        log(f"Nie udało się ściąć podstawy ({e})")
    return mesh


def repair(mesh, smooth_iters=0):
    mesh = keep_largest(mesh)
    trimesh.repair.fix_winding(mesh)
    trimesh.repair.fill_holes(mesh)
    if smooth_iters > 0:
        trimesh.smoothing.filter_taubin(mesh, iterations=smooth_iters)
    mesh.fix_normals()
    return mesh


def decimate(mesh, target_faces: int):
    if not target_faces or len(mesh.faces) <= target_faces:
        return mesh
    try:
        dec = mesh.simplify_quadric_decimation(face_count=target_faces)
        if mesh.is_watertight and not dec.is_watertight:
            trimesh.repair.fill_holes(dec)
        if mesh.is_watertight and not dec.is_watertight:
            log("Decymacja rozszczelniła siatkę — zostawiam pełną rozdzielczość")
            return mesh
        return dec
    except Exception as e:  # noqa: BLE001
        log(f"Decymacja niedostępna ({e}) — pip install fast-simplification")
        return mesh


# ─────────────────────────── wydrążanie ───────────────────────────

def hollow(mesh: trimesh.Trimesh, wall_mm=2.0, drain_mm=0.0, max_voxels=220):
    """Wydrąża bryłę (ścianka wall_mm) i opcjonalnie dodaje otwór odpływowy w najniższym miejscu."""
    from scipy.ndimage import distance_transform_edt
    from skimage.measure import marching_cubes
    if not mesh.is_watertight:
        log("Wydrążanie wymaga szczelnej bryły — pomijam")
        return mesh
    pitch = max(wall_mm / 3, mesh.extents.max() / max_voxels)
    vox = mesh.voxelized(pitch).fill()
    solid = np.pad(vox.matrix, 2)
    dist = distance_transform_edt(solid) * pitch
    inner = dist > wall_mm + pitch * 0.5
    if inner.sum() < 8:
        log("Model za cienki na wydrążenie przy tej grubości ścianki — pomijam")
        return mesh
    verts, faces, _, _ = marching_cubes(inner.astype(np.float32), 0.5)
    verts = trimesh.transform_points(verts - 2, vox.transform)
    cav = trimesh.Trimesh(verts, faces, process=True)
    cav = keep_largest(cav)
    trimesh.smoothing.filter_taubin(cav, iterations=10)
    cav.fix_normals()
    if not cav.is_watertight:
        log("Nie udało się zbudować wnęki — pomijam wydrążanie")
        return mesh
    cav.invert()
    out = trimesh.util.concatenate([mesh, cav])
    log(f"Wydrążono: objętość {abs(mesh.volume) / 1000:.1f} → {abs(out.volume) / 1000:.1f} cm³")
    if drain_mm > 0:
        lo = cav.vertices[np.argmin(cav.vertices[:, 2])]
        z0 = mesh.bounds[0, 2] - 1
        h = lo[2] - z0 + wall_mm
        cyl = trimesh.creation.cylinder(radius=drain_mm / 2, height=h, sections=32)
        cyl.apply_translation([lo[0], lo[1], z0 + h / 2])
        out2 = difference(out, cyl)
        if out2 is not out:
            log(f"Otwór odpływowy Ø{drain_mm} mm w najniższym punkcie wnęki")
            out = out2
    return out


# ─────────────────────── automatyczna orientacja ───────────────────────

def support_score(mesh: trimesh.Trimesh, overhang_deg=45.0):
    zmin = mesh.bounds[0, 2]
    n = mesh.face_normals
    a = mesh.area_faces
    c = mesh.triangles_center[:, 2]
    on_bed = (c < zmin + 0.3) & (n[:, 2] < -0.95)
    over = (n[:, 2] < -np.sin(np.radians(overhang_deg))) & ~on_bed
    overhang = (a[over] * -n[over, 2]).sum()
    contact = a[on_bed].sum()
    return overhang - 0.5 * contact + 0.002 * mesh.extents[2] * a.sum() / 100, overhang, contact


def auto_orient(mesh: trimesh.Trimesh, xf: Xf, overhang_deg=45.0, max_candidates=24):
    cands = [np.eye(4)]
    for ax, ang in (([1, 0, 0], 90), ([1, 0, 0], -90), ([1, 0, 0], 180), ([0, 1, 0], 90), ([0, 1, 0], -90)):
        cands.append(trimesh.transformations.rotation_matrix(np.radians(ang), ax))
    try:
        poses, prob = trimesh.poses.compute_stable_poses(mesh, n_samples=1)
        for T in poses[np.argsort(-prob)][:max_candidates]:
            R = T.copy()
            R[:3, 3] = 0
            cands.append(R)
    except Exception as e:  # noqa: BLE001
        log(f"Stabilne pozycje niedostępne ({e}) — sprawdzam tylko 6 osi")
    best, best_s = None, None
    base_s = support_score(mesh, overhang_deg)
    for R in cands:
        m = mesh.copy()
        m.apply_transform(R)
        s = support_score(m, overhang_deg)
        if best_s is None or s[0] < best_s[0]:
            best, best_s = R, s
    xf.apply(mesh, best)
    log(f"Auto-orientacja: nawisy {base_s[1] / 100:.1f} → {best_s[1] / 100:.1f} cm², "
        f"styk ze stołem {best_s[2] / 100:.1f} cm²")
    return mesh


# ─────────────────────── podstawka z napisem ───────────────────────

# Standardowe okrągłe podstawki w grach bitewnych / modelarstwie [mm]
ROUND_BASES = (25, 28, 32, 40, 50, 60, 80, 100, 130, 160)


def footprint_radius(mesh) -> float:
    """Promień okręgu wokół środka obrysu XY, w którym mieści się cały model (widok z góry)."""
    v = mesh.vertices[:, :2]
    c = (v.min(0) + v.max(0)) / 2
    return float(np.sqrt(((v - c) ** 2).sum(1)).max())


def fit_to_round_base(mesh, xf: Xf, diameter: float, margin: float = 0.92):
    """Skaluje model tak, żeby z góry mieścił się w całości na okrągłej podstawce o średnicy diameter."""
    r = footprint_radius(mesh)
    if r > 0:
        xf.apply(mesh, trimesh.transformations.scale_matrix(diameter / 2 * margin / r))
    return mesh


def add_round_base(mesh, diameter=32.0, height_mm=3.5, bevel_mm=0.8):
    """Okrągła podstawka modelarska pod modelem (model musi już stać na z=0). Jeśli model z góry
    wystaje poza podaną średnicę, podstawka rośnie do najbliższego standardowego rozmiaru."""
    from shapely.geometry import Point
    need = footprint_radius(mesh) * 2 / 0.92
    d = float(diameter)
    if need > d + 1e-6:
        d = next((s for s in ROUND_BASES if s >= need), round(need))
        log(f"Model nie mieści się na podstawce Ø{diameter:g} mm — używam Ø{d:g} mm")
    b = mesh.bounds
    cx, cy = (b[0, 0] + b[1, 0]) / 2, (b[0, 1] + b[1, 1]) / 2
    z0 = b[0, 2]
    # sfazowana krawędź jak w podstawkach do gier: dolny krążek pełny, górny węższy o bevel_mm
    low = extrude(Point(cx, cy).buffer(d / 2, quad_segs=64), z0 - height_mm, z0 - bevel_mm)
    top = trimesh.creation.cylinder(radius=d / 2, height=bevel_mm, sections=256)
    top.vertices[top.vertices[:, 2] > 0, :2] = (top.vertices[top.vertices[:, 2] > 0, :2] * ((d / 2 - bevel_mm) / (d / 2)))
    top.apply_translation([cx, cy, z0 - bevel_mm / 2])
    lift = extrude(Point(cx, cy).buffer(d / 2 - bevel_mm, quad_segs=64), z0 - bevel_mm, z0 + 0.4)
    out = union(low, top, lift, mesh)
    log(f"Dodano okrągłą podstawkę Ø{d:g} × {height_mm:g} mm")
    return out


def add_pedestal(mesh, text="", height_mm=5.0, text_mm=7.0, emboss_mm=0.8, shape="rounded"):
    from shapely.geometry import box, Point
    b = mesh.bounds
    w, d = b[1, 0] - b[0, 0], b[1, 1] - b[0, 1]
    tw = 0
    tpoly = None
    if text:
        tpoly = text_polygon(text, text_mm)
        tw = tpoly.bounds[2] - tpoly.bounds[0]
    pw = max(w * 1.15 + 6, tw + 10)
    strip = (text_mm + 8) if text else 0
    pd = d * 1.15 + 6 + strip
    cx, cy = (b[0, 0] + b[1, 0]) / 2, (b[0, 1] + b[1, 1]) / 2
    x0, y0 = cx - pw / 2, cy - (d * 1.15 + 6) / 2 - strip
    if shape == "circle" and not text:
        poly = Point(cx, cy).buffer(max(pw, pd) / 2, quad_segs=48)
    else:
        r = min(4.0, pw / 6, pd / 6)
        poly = box(x0 + r, y0 + r, x0 + pw - r, y0 + pd - r).buffer(r, quad_segs=12)
    z0 = b[0, 2]
    ped = extrude(poly, z0 - height_mm, z0 + 0.4)  # 0,4 mm zakładki — model wtapia się w podstawkę
    parts = [ped, mesh]
    if tpoly is not None:
        from shapely import affinity
        tp = affinity.translate(tpoly, cx, y0 + strip / 2 + 1)
        parts.append(extrude(tp, z0 + 0.39, z0 + 0.4 + emboss_mm))
    out = union(*parts)
    log("Dodano podstawkę" + (f" z napisem „{text}”" if text else ""))
    return out


# ─────────────────────── podział na części z kołkami ───────────────────────

def _pin_points(poly, pin_d):
    inner = poly.buffer(-pin_d * 1.6)
    if inner.is_empty:
        return []
    geoms = list(inner.geoms) if hasattr(inner, "geoms") else [inner]
    pts = []
    for g in geoms:
        if g.area < (pin_d * 2) ** 2:
            continue
        minx, miny, maxx, maxy = g.bounds
        if max(maxx - minx, maxy - miny) > pin_d * 8:  # duży przekrój → 2 kołki
            from shapely.geometry import box
            if maxx - minx >= maxy - miny:
                halves = [box(minx, miny, (minx + maxx) / 2, maxy), box((minx + maxx) / 2, miny, maxx, maxy)]
            else:
                halves = [box(minx, miny, maxx, (miny + maxy) / 2), box(minx, (miny + maxy) / 2, maxx, maxy)]
            for hb in halves:
                part = g.intersection(hb)
                if not part.is_empty and part.area > (pin_d * 1.5) ** 2:
                    pts.append(part.representative_point())
        else:
            pts.append(g.representative_point())
    return pts


def split_for_bed(mesh, bed=(220.0, 220.0, 250.0), pin_d=4.0, pin_len=10.0, clearance=0.25, _depth=0):
    ext = mesh.extents
    ratio = ext / np.asarray(bed)
    if ratio.max() <= 1.0 or _depth > 6:
        return [mesh]
    ax = int(np.argmax(ratio))
    normal = np.eye(3)[ax]
    origin = mesh.bounds.mean(axis=0)
    holes = []
    sec = mesh.section(plane_origin=origin, plane_normal=normal)
    if sec is not None:
        planar, to3d = sec.to_planar()
        for poly in planar.polygons_full:
            for p in _pin_points(poly, pin_d):
                c3 = trimesh.transform_points([[p.x, p.y, 0]], to3d)[0]
                cyl = trimesh.creation.cylinder(radius=pin_d / 2 + clearance, height=pin_len + 1, sections=32)
                cyl.apply_transform(trimesh.geometry.align_vectors([0, 0, 1], normal))
                cyl.apply_translation(c3)
                holes.append(cyl)
    if holes:
        mesh = difference(mesh, *holes)
    parts = []
    for sgn in (1, -1):
        p = plane_cut(mesh, origin, normal * sgn)
        if p is not None and len(p.faces):
            parts += split_for_bed(p, bed, pin_d, pin_len, clearance, _depth + 1)
    if _depth == 0:
        log(f"Podzielono na {len(parts)} części, otwory na kołki Ø{pin_d} × {pin_len} mm")
    return parts


def make_pin(pin_d=4.0, pin_len=10.0):
    pin = trimesh.creation.cylinder(radius=pin_d / 2, height=pin_len - 0.5, sections=32)
    return place_on_bed(pin)


def lay_flat_for_print(part):
    """Kładzie część przekrojem (największą płaską ścianą) na stół."""
    xf = Xf()
    n = part.facets_normal if len(part.facets) else None
    if n is not None and len(n):
        i = int(np.argmax(part.facets_area))
        xf.apply(part, trimesh.geometry.align_vectors(n[i], [0, 0, -1]))
    return place_on_bed(part)
