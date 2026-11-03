"""Kolory: kwantyzacja, eksport 3MF (części lub malowanie trójkątów pod AMS/MMU), GLB/PLY."""
from __future__ import annotations

import zipfile
from xml.sax.saxutils import escape

import numpy as np
import trimesh


def quantize(mesh: trimesh.Trimesh, n_colors=4, seed=0):
    """Kolory ścian → n kolorów (k-means). Zwraca (etykiety ścian, paleta RGB uint8)."""
    from scipy.cluster.vq import kmeans2
    vc = np.asarray(mesh.visual.vertex_colors)[:, :3].astype(np.float32)
    fc = vc[mesh.faces].mean(1)
    rng = np.random.default_rng(seed)
    sample = fc[rng.choice(len(fc), min(len(fc), 20000), replace=False)]
    cent, _ = kmeans2(sample, n_colors, minit="++", seed=seed)
    labels = np.argmin(((fc[:, None, :] - cent[None]) ** 2).sum(-1), 1)
    order = np.argsort(-np.bincount(labels, minlength=n_colors))  # najczęstszy kolor = filament 1
    remap = np.empty(n_colors, int)
    remap[order] = np.arange(n_colors)
    return remap[labels], np.clip(cent[order], 0, 255).astype(np.uint8)


def _paint_code(state: int) -> str:
    """Kodowanie malowania trójkąta (PrusaSlicer/OrcaSlicer/Bambu Studio): 1→'4', 2→'8', 3→'0C', 4→'1C'…"""
    if state <= 0:
        return ""
    if state < 3:
        return format(state << 2, "X")
    return format(state - 3, "X") + "C"


def _hex(c):
    c = list(c) + [255] * (4 - len(c))
    return "#" + "".join(f"{int(v):02X}" for v in c[:4])


def write_3mf(path, parts, face_states=None, palette=None):
    """
    parts: lista (nazwa, siatka, rgba|None). Każda część = osobny obiekt (slicer pyta,
    czy złożyć w jeden obiekt wieloczęściowy — odpowiedz „tak”).
    face_states: dla jednej części — numer filamentu na każdy trójkąt (malowanie MMU/AMS).
    """
    ns = ('xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
          'xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06" xml:lang="en-US" unit="millimeter"')
    out = [f'<?xml version="1.0" encoding="UTF-8"?>\n<model {ns}>',
           '<metadata name="Application">Foto2STL</metadata>', "<resources>"]
    cols = [p[2] or (200, 200, 200, 255) for p in parts]
    if palette is not None:
        cols = [tuple(c) + (255,) for c in palette]
    out.append('<basematerials id="1">' + "".join(
        f'<base name="kolor{i + 1}" displaycolor="{_hex(c)}"/>' for i, c in enumerate(cols)) + "</basematerials>")
    for oid, (name, mesh, _) in enumerate(parts, start=2):
        pindex = 0 if palette is not None else oid - 2
        out.append(f'<object id="{oid}" name="{escape(name)}" type="model" pid="1" pindex="{pindex}"><mesh><vertices>')
        out.append("".join(f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in mesh.vertices))
        out.append("</vertices><triangles>")
        tri = []
        for fi, (a, b, c) in enumerate(mesh.faces):
            extra = ""
            if face_states is not None and oid == 2:
                code = _paint_code(int(face_states[fi]) + 1)
                if code and face_states[fi] > 0:
                    extra = f' paint_color="{code}" slic3rpe:mmu_segmentation="{code}"'
                if palette is not None:
                    extra += f' pid="1" p1="{int(face_states[fi])}"'
            tri.append(f'<triangle v1="{a}" v2="{b}" v3="{c}"{extra}/>')
        out.append("".join(tri))
        out.append("</triangles></mesh></object>")
    out.append("</resources><build>")
    out += [f'<item objectid="{oid}"/>' for oid in range(2, len(parts) + 2)]
    out.append("</build></model>")
    ct = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
          'content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
          'relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing'
          '-3dmodel+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/'
            'package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", "\n".join(out))
    return path


def write_painted_3mf(path, mesh, n_colors=4):
    labels, pal = quantize(mesh, n_colors)
    write_3mf(path, [("model", mesh, None)], face_states=labels, palette=pal)
    return pal


def export_colored(mesh, path):
    """GLB/PLY z kolorami wierzchołków — do podglądu i dalszej obróbki."""
    m = mesh.copy()
    if str(path).lower().endswith(".glb"):
        m.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))  # Z-up → Y-up
    m.export(path)
    return path
