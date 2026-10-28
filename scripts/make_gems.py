#!/usr/bin/env python3
"""Generate the 3D gem previews (web/gems/<shape>.glb) and the studio-light environment (web/gems/env.jpg).

The models are schematic: a faceted crown, girdle and pavilion built from the outline of each cut. They exist so
a client can recognise the shapes in the picker, not as exact diamond models. Run from the project root:
    .venv/bin/python scripts/make_gems.py
"""
import math
import os
import sys

import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFilter

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web", "gems")


# ---------- outlines: (N, 2) arrays in the x/z plane, N even so the half-step facet rings line up ----------

def circle(n=32):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.c_[np.cos(a), np.sin(a)] * 0.5


def oval(n=32, ratio=1.38):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.c_[np.cos(a) * 0.5, np.sin(a) * 0.5 * ratio]


def cushion(n=32, power=3.2):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    c, s = np.cos(a), np.sin(a)
    return np.c_[np.sign(c) * np.abs(c) ** (2 / power), np.sign(s) * np.abs(s) ** (2 / power)] * 0.5


def pear(n=32):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    x = np.sin(t) * np.sin(t / 2) ** 1.0
    z = -np.cos(t)
    pts = np.c_[x * 0.36, z * 0.5]
    pts[:, 1] -= pts[:, 1].mean() * 0.35
    return pts


def marquise(n=32):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    z = np.cos(t)
    x = np.sign(np.sin(t)) * (1 - np.abs(z) ** 1.5) * 0.17
    return np.c_[x, z * 0.5]


def rect_chamfer(w, l, c, mids):
    """Rectangle with cut corners. With mids, every edge also gets a midpoint (16 points instead of 8)."""
    hw, hl = w / 2, l / 2
    corners = [(hw - c, hl), (hw, hl - c), (hw, -hl + c), (hw - c, -hl), (-hw + c, -hl), (-hw, -hl + c),
               (-hw, hl - c), (-hw + c, hl)]
    if not mids:
        return np.array(corners, float)
    out = []
    for i, p in enumerate(corners):
        q = corners[(i + 1) % len(corners)]
        out += [p, ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)]
    return np.array(out, float)


def square(n=16):
    return rect_chamfer(1.0, 1.0, 0.001, True)


# ---------- faceting ----------

def _ring(outline, scale, y, shift=0.0):
    """Points of the outline scaled about its centre, at height y. shift 0.5 puts a point between each pair."""
    n = len(outline)
    c = outline.mean(axis=0)
    p = outline - c
    if shift:
        p = (p + np.roll(p, -1, axis=0)) / 2
    sx, sz = (scale, scale) if np.isscalar(scale) else scale
    return np.c_[p[:, 0] * sx, np.full(n, y), p[:, 1] * sz]


class Builder:
    def __init__(self):
        self.v, self.f = [], []

    def add(self, pts):
        i = len(self.v)
        self.v.extend(pts.tolist() if hasattr(pts, "tolist") else pts)
        return list(range(i, i + len(pts)))

    def quad_strip(self, a, b):
        n = len(a)
        for k in range(n):
            k1 = (k + 1) % n
            self.f += [[a[k], a[k1], b[k]], [a[k1], b[k1], b[k]]]

    def star_strip(self, a, b):
        """a: ring at whole steps, b: ring at half steps (b[k] sits between a[k] and a[k+1])."""
        n = len(a)
        for k in range(n):
            k1 = (k + 1) % n
            self.f += [[a[k], a[k1], b[k]], [a[k1], b[k1], b[k]]]

    def cap(self, ring, point):
        n = len(ring)
        for k in range(n):
            self.f.append([ring[k], ring[(k + 1) % n], point])

    def mesh(self):
        m = trimesh.Trimesh(np.array(self.v, float), np.array(self.f, int), process=False)
        m.merge_vertices()                        # a collapsed edge (the line culet) leaves coincident points
        m.update_faces(m.nondegenerate_faces())
        m.remove_unreferenced_vertices()
        # every facet faces away from the centre (the stones are convex)
        f = m.faces.copy()
        flip = np.einsum("ij,ij->i", m.face_normals, m.triangles_center - m.vertices.mean(axis=0)) < 0
        f[flip] = f[flip][:, ::-1]
        return trimesh.Trimesh(m.vertices, f, process=False)


def brilliant(outline, crown=0.17, pavilion=0.44, table=0.58, girdle=0.025):
    b = Builder()
    n = len(outline)
    t = b.add(_ring(outline, table, crown))
    cm = b.add(_ring(outline, 0.80, crown * 0.46, 0.5))
    g_top = b.add(_ring(outline, 1.0, 0.0))
    g_bot = b.add(_ring(outline, 1.0, -girdle))
    pm = b.add(_ring(outline, 0.60, -pavilion * 0.55, 0.5))
    culet = b.add([[0.0, -pavilion, 0.0]])[0]
    tc = b.add([[0.0, crown, 0.0]])[0]
    b.cap(t, tc)
    b.star_strip(t, cm)
    # between the half-step crown ring and the girdle the pattern flips: girdle is the whole-step ring
    b.star_strip(g_top, cm)
    b.quad_strip(g_top, g_bot)
    b.star_strip(g_bot, pm)
    b.cap(pm, culet)
    return b.mesh()


def step_cut(outline, crown=0.15, pavilion=0.42, table=0.56, girdle=0.03):
    """Rectangular step cut (emerald): bands that change slope, and a line culet instead of a point."""
    b = Builder()
    crown_rings = [(1.0, 0.0), (0.88, crown * 0.28), (0.74, crown * 0.62), (table, crown)]
    pav_rings = [(1.0, -girdle), (0.86, -pavilion * 0.30), (0.62, -pavilion * 0.66)]
    rings = [b.add(_ring(outline, s, y)) for s, y in reversed(crown_rings)]
    rings += [b.add(_ring(outline, s, y)) for s, y in pav_rings]
    keel = b.add(_ring(outline, (0.0, 0.46), -pavilion))
    rings.append(keel)
    # table
    tc = b.add([[0.0, crown, 0.0]])[0]
    b.cap(rings[0], tc)
    for a, c in zip(rings, rings[1:]):
        b.quad_strip(a, c)
    return b.mesh()


GEMS = {
    "round": lambda: brilliant(circle()),
    "oval": lambda: brilliant(oval()),
    "cushion": lambda: brilliant(cushion()),
    "pear": lambda: brilliant(pear(), table=0.52, pavilion=0.46),
    "marquise": lambda: brilliant(marquise(), table=0.5, pavilion=0.5),
    "princess": lambda: brilliant(square(), crown=0.16, pavilion=0.52, table=0.62),
    "radiant": lambda: brilliant(rect_chamfer(0.78, 1.0, 0.16, True), crown=0.16, table=0.58),
    "emerald": lambda: step_cut(rect_chamfer(0.72, 1.0, 0.17, False)),
}


def finish(mesh, name):
    mesh = mesh.copy()
    mesh.unmerge_vertices()          # one normal per facet: flat shading
    ext = mesh.extents
    mesh.apply_translation(-mesh.bounds.mean(axis=0))
    mesh.apply_scale(1.0 / max(ext[0], ext[2]))
    mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
        baseColorFactor=[238, 245, 255, 255], metallicFactor=1.0, roughnessFactor=0.06, doubleSided=True, name=name))
    return mesh


def studio_environment(path, w=1024, h=512):
    """A bright studio with dark flags: each facet mirrors either a light or a dark part, so a turning stone flashes."""
    rng = np.random.default_rng(11)
    ys = np.linspace(0, 1, h)[:, None]
    sky = np.array([176, 190, 206]) * (1 - ys) + np.array([92, 100, 110]) * ys          # soft overcast base
    img = Image.fromarray(np.repeat(sky[:, None, :], w, axis=1).reshape(h, w, 3).astype("uint8"))
    d = ImageDraw.Draw(img)
    d.rectangle([w * 0.04, 0, w * 0.96, h * 0.2], fill=(255, 255, 255))                 # overhead softbox
    for i in range(14):                                                                 # alternating light and dark strips
        x = int((i + rng.uniform(-0.15, 0.15)) * w / 14)
        wd = int(rng.uniform(w * 0.014, w * 0.04))
        top = int(h * rng.uniform(0.16, 0.28)); bot = int(h * rng.uniform(0.62, 0.8))
        fill = (255, 253, 247) if i % 2 == 0 else (24, 30, 38)
        d.rectangle([x, top, x + wd, bot], fill=fill)
    for _ in range(18):                                                                 # hard sparks
        x, y = rng.uniform(0, w), rng.uniform(h * 0.22, h * 0.72)
        r = rng.uniform(3, 8)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255))
    d.rectangle([0, int(h * 0.84), w, h], fill=(30, 34, 40))                            # floor
    img = img.filter(ImageFilter.GaussianBlur(1.6))
    img.save(path, quality=92)


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, build in GEMS.items():
        mesh = finish(build(), name)
        mesh.export(os.path.join(OUT, name + ".glb"), include_normals=True)
        print("%-9s faces %4d  extents %s" % (name, len(mesh.faces), np.round(mesh.extents, 2)))
    studio_environment(os.path.join(OUT, "env.jpg"))
    print("wrote", os.path.normpath(OUT))


if __name__ == "__main__":
    sys.exit(main())
