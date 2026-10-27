#!/usr/bin/env python3
"""GLB ring (from TRELLIS.2) -> repaired, mm-scaled STL + spec for wax printing.

Library use: process(glb_path, out_dir, inner_diameter_mm=...)
CLI:         python -m app.ring.postprocess ring.glb --inner-diameter 17.19 --out out/
"""
import argparse
import json
import math
import os
import sys

import numpy as np
import trimesh
from skimage import measure
from scipy import ndimage as ndi
from shapely.geometry import Polygon

# g/cm^3, approximate; they vary by alloy recipe. Override with --densities file.
DENSITIES = {
    "14K yellow gold": 13.4,
    "14K white gold": 13.8,
    "14K rose gold": 13.2,
    "18K yellow gold": 15.5,
    "18K white gold": 15.8,
    "18K rose gold": 15.0,
}
MIN_WALL_MM = 0.8


class RingError(Exception):
    """The file can't be turned into a printable ring automatically."""


def load_mesh(path):
    loaded = trimesh.load(path, force="scene")
    meshes = [g for g in loaded.dump() if isinstance(g, trimesh.Trimesh) and len(g.faces)]
    if not meshes:
        raise RingError("לא נמצאה גיאומטריה בקובץ.")
    return trimesh.util.concatenate(meshes)


def solidify(mesh, resolution=400):
    """Turn a messy open-shell mesh (thousands of fragments) into one watertight solid.

    Voxelizes the surface, closes small gaps, fills the interior and re-meshes.
    Resolution = voxels along the longest side (400 is ~0.05 mm on a ring).
    Marching cubes on a voxel grid leaves terraces (visible as stripes, and printable in wax);
    Taubin smoothing removes them without the shrinking plain Laplacian smoothing causes
    (about -1% volume at 10 iterations; the ring is scaled to the finger size afterwards).
    """
    pitch = float(max(mesh.extents)) / resolution
    surface = np.pad(mesh.voxelized(pitch).matrix, 3)
    filled = ndi.binary_fill_holes(ndi.binary_closing(surface, iterations=1))
    vol = ndi.gaussian_filter(filled.astype(float), 0.8)
    verts, faces, _, _ = measure.marching_cubes(vol, 0.5, spacing=(pitch,) * 3)
    out = trimesh.Trimesh(verts, faces)
    if out.volume < 0:
        out.invert()
    trimesh.smoothing.filter_taubin(out, lamb=0.5, nu=-0.53, iterations=10)
    return out


def prepare(mesh):
    """Return (watertight solid mesh, note about what was done)."""
    mesh = mesh.copy()
    mesh.merge_vertices()
    if mesh.is_watertight and mesh.body_count == 1:
        trimesh.repair.fix_normals(mesh)
        return mesh, "הקובץ הגיע כגוף סגור."
    n = mesh.body_count
    solid = solidify(mesh)
    return solid, "הקובץ לא היה גוף סגור (%d חלקים נפרדים) ונבנה מחדש כגוף אחד." % n


def _slice_polys(mesh, y):
    """Polygons of the cross-section at height y (plane normal = +Y), as (area, x, z)."""
    sec = mesh.section(plane_origin=[0, y, 0], plane_normal=[0, 1, 0])
    if sec is None:
        return []
    planar, T = sec.to_2D()
    out = []
    for q in planar.polygons_full:
        c = T @ np.array([q.centroid.x, q.centroid.y, 0, 1])
        out.append((q.area, c[0], c[2]))
    return out


def head_to_plus_y(mesh):
    """Rotate about the ring axis (Z) so the head points to +Y."""
    cx, cy = mesh.bounds[:, 0].mean(), mesh.bounds[:, 1].mean()
    v = mesh.vertices[:, :2] - [cx, cy]
    r = np.linalg.norm(v, axis=1)
    far = v[r >= np.percentile(r, 99.5)]
    ang = math.atan2(far[:, 1].mean(), far[:, 0].mean())
    mesh = mesh.copy()
    mesh.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2 - ang, [0, 0, 1],
                                                                 [cx, cy, 0]))
    return mesh


def remove_stone(mesh, step=0.2):
    """Cut out a center stone that the generator fused into the head, leaving prongs.

    Heuristic: the stone is the one cross-section polygon sitting on the head axis
    between the prongs. We find the culet (lowest slice where it exists), measure where
    the prongs are at every height, and subtract a cone that follows the inner prong edge.
    Returns (mesh, info dict) - info is None if no stone was found.
    """
    mesh = head_to_plus_y(mesh)
    top = mesh.bounds[1, 1]
    # Axis through the table apex: the very top slice is just the stone's table.
    apex = None
    for y in np.arange(top - 0.05, top - 1.5, -0.05):
        polys = _slice_polys(mesh, y)
        if len(polys) == 1:
            apex = (polys[0][1], polys[0][2])
            break
    if apex is None:
        return mesh, None
    ax, az = apex

    def central(polys):
        return [q for q in polys if math.hypot(q[1] - ax, q[2] - az) < 0.6]

    # Walk down until the central polygon disappears -> culet.
    y = top - 0.05
    culet = None
    while y > top - 12:
        if not central(_slice_polys(mesh, y)):
            culet = y + step
            break
        y -= step
    if culet is None:
        return mesh, None

    ys, ds = [], []
    for y in np.arange(culet, top + 0.01, step):
        others = [q for q in _slice_polys(mesh, y) if math.hypot(q[1] - ax, q[2] - az) >= 0.6]
        if len(others) == 4 and max(q[0] for q in others) < 4:
            d = np.mean([math.hypot(q[1] - ax, q[2] - az) for q in others])
            rp = math.sqrt(np.mean([q[0] for q in others]) / math.pi)
            ys.append(y)
            ds.append(d - rp)  # inner prong edge
    if len(ys) < 3:
        return mesh, None
    grid = np.arange(culet - 0.1, top + 0.6, 0.1)
    radii = np.interp(grid, ys, ds)
    prof = [[0.0, grid[0]]] + [[r, y] for r, y in zip(radii, grid)] + [[0.0, grid[-1]]]
    cutter = trimesh.creation.revolve(np.array(prof), sections=64)
    cutter.merge_vertices()
    # revolve() spins around Z; stand it on the Y axis, centred on the stone axis.
    cutter.apply_transform(trimesh.transformations.rotation_matrix(-math.pi / 2, [1, 0, 0]))
    # after the rotation, former Z (profile "y") became +Y only if sign matches - verify:
    if cutter.bounds[:, 1].mean() < 0:
        cutter.apply_transform(trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0]))
    cutter.apply_translation([ax, 0, az])
    result = trimesh.boolean.difference([mesh, cutter], engine="manifold")
    info = {"culet_y_mm": round(float(culet), 2), "table_y_mm": round(float(top), 2),
            "removed_volume_mm3": round(float(abs(mesh.volume) - abs(result.volume)), 1)}
    return result, info


def pick_axis(mesh, axis_arg):
    """Ring axis = through the finger hole. Default: thinnest bbox extent."""
    if axis_arg != "auto":
        return "xyz".index(axis_arg)
    return int(np.argmin(mesh.extents))


def align_axis_to_z(mesh, axis):
    if axis == 2:
        return mesh
    T = np.eye(4)
    if axis == 0:
        T[:3, :3] = trimesh.transformations.rotation_matrix(math.pi / 2, [0, 1, 0])[:3, :3]
    else:
        T[:3, :3] = trimesh.transformations.rotation_matrix(-math.pi / 2, [1, 0, 0])[:3, :3]
    mesh = mesh.copy()
    mesh.apply_transform(T)
    return mesh


def _fit_circle(pts):
    """Least-squares circle through 2D points -> (cx, cy, r)."""
    A = np.c_[2 * pts[:, 0], 2 * pts[:, 1], np.ones(len(pts))]
    b = (pts ** 2).sum(axis=1)
    cx, cy, c = np.linalg.lstsq(A, b, rcond=None)[0]
    return cx, cy, math.sqrt(max(c + cx * cx + cy * cy, 0))


def _inner_from_points(pts):
    """Finger-hole radius from section points when the loop isn't closed (e.g. a window
    in the head cuts the band at mid-width). Splits points into inner/outer edge by radius."""
    c = pts.mean(axis=0)
    for _ in range(3):  # re-centre on the inner edge
        r = np.linalg.norm(pts - c, axis=1)
        lo, hi = r.min(), np.median(r)
        for _ in range(20):  # 1-D two-means
            mid = (lo + hi) / 2
            lo, hi = r[r < mid].mean(), r[r >= mid].mean()
        inner = pts[r < (lo + hi) / 2]
        cx, cy, rad = _fit_circle(inner)
        c = np.array([cx, cy])
    return rad


def inner_diameter(mesh):
    """Diameter of the finger hole, from cross-sections near mid-width."""
    best = None
    zmin, zmax = mesh.bounds[:, 2]
    for frac in (0.5, 0.45, 0.55, 0.35, 0.65):
        section = mesh.section(plane_origin=[0, 0, zmin + (zmax - zmin) * frac], plane_normal=[0, 0, 1])
        if section is None:
            continue
        planar, T = section.to_2D()
        polys = planar.polygons_full
        if not polys:
            continue
        outer = max(polys, key=lambda p: p.area)
        if outer.interiors:
            area = max(Polygon(r).area for r in outer.interiors)
            d = 2.0 * math.sqrt(area / math.pi)
        else:
            d = 2.0 * _inner_from_points(np.asarray(planar.vertices))
        if best is None or d > best:
            best = d
    return best


def wall_thickness(mesh, samples=4000, seed=0):
    """Approximate local wall thickness by casting rays inward from surface points."""
    pts, face_idx = trimesh.sample.sample_surface(mesh, samples, seed=seed)
    normals = mesh.face_normals[face_idx]
    origins = pts - normals * 1e-3
    dist = np.full(len(pts), np.nan)
    # Without embree trimesh's ray tester allocates (candidate triangles x rays) at once,
    # which reaches many GB on a dense ring mesh. Cast in small batches to bound memory.
    batch = 100
    for i in range(0, len(pts), batch):
        o, n = origins[i:i + batch], normals[i:i + batch]
        hits_loc, ray_idx, _ = mesh.ray.intersects_location(o, -n, multiple_hits=False)
        dist[i + ray_idx] = np.linalg.norm(hits_loc - o[ray_idx], axis=1)
    return pts, dist


def process(glb_path, out_dir, inner_diameter_mm, shrink=1.0, densities=None,
            axis="auto", remove_fused_stone=False, name="ring", view_color=(212, 175, 55)):
    """Run the full pipeline. Writes <name>.stl and <name>_view.glb into out_dir.

    Returns a spec dict (all lengths in mm, weights in grams).
    """
    dens = dict(densities or DENSITIES)
    os.makedirs(out_dir, exist_ok=True)
    warnings = []

    mesh = load_mesh(glb_path)
    mesh, note = prepare(mesh)
    warnings.append(note)
    if not mesh.is_watertight:
        warnings.append("הרשת לא נסגרה אחרי התיקון האוטומטי - נדרש תיקון ידני לפני הדפסה.")

    axis_idx = pick_axis(mesh, axis)
    mesh = align_axis_to_z(mesh, axis_idx)
    mesh.apply_translation(-mesh.centroid)

    d0 = inner_diameter(mesh)
    if d0 is None or d0 <= 0:
        raise RingError("לא זוהה חור האצבע בקובץ.")
    scale = inner_diameter_mm / d0
    mesh.apply_scale(scale)
    if shrink != 1.0:
        mesh.apply_scale(shrink)
    # Sit on z=0, centred in XY on the hole axis, head towards +Y.
    mesh.apply_translation([-mesh.bounds[:, 0].mean(), -mesh.bounds[:, 1].mean(), -mesh.bounds[0, 2]])
    mesh = head_to_plus_y(mesh)

    stone_info = None
    if remove_fused_stone:
        mesh, stone_info = remove_stone(mesh)
        if stone_info is None:
            warnings.append("לא נמצאה אבן להסרה - הקובץ לא שונה.")
        elif not mesh.is_watertight:
            warnings.append("הרשת לא סגורה אחרי הסרת האבן.")
        else:
            mesh.apply_translation([0, 0, -mesh.bounds[0, 2]])

    d_check = inner_diameter(mesh)
    volume = float(abs(mesh.volume)) if mesh.is_watertight else None

    _, dist = wall_thickness(mesh)
    valid = dist[~np.isnan(dist)]
    thin = float(np.mean(valid < MIN_WALL_MM) * 100) if len(valid) else None
    p5 = float(np.percentile(valid, 5)) if len(valid) else None
    if thin is not None and thin > 2:
        warnings.append("%.1f%% מהמשטח דק מ-%.1f מ\"מ - לבדוק שיניים וחישוק." % (thin, MIN_WALL_MM))

    weights = {}
    if volume:
        for alloy, rho in dens.items():
            weights[alloy] = round(volume / 1000.0 * rho, 2)  # mm3 -> cm3 -> g

    stl_name, view_name = name + ".stl", name + "_view.glb"
    mesh.export(os.path.join(out_dir, stl_name))
    # Y-up copy for the browser viewer (glTF convention); the STL keeps Z = finger axis.
    view = mesh.copy()
    view.apply_translation(-view.bounds.mean(axis=0))
    view.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
        baseColorFactor=list(view_color) + [255], metallicFactor=1.0, roughnessFactor=0.25))
    # with vertex normals the viewer shades smoothly; without them every small triangle shows as a flat facet
    view.export(os.path.join(out_dir, view_name), include_normals=True)

    return {
        "stl": stl_name,
        "view_glb": view_name,
        "units": "mm",
        "target_inner_diameter_mm": round(inner_diameter_mm, 2),
        "inner_diameter_after_scaling_mm": round(d_check, 2) if d_check else None,
        "scale_applied": round(scale * shrink, 4),
        "shrink": shrink,
        "dimensions_mm": [round(float(v), 2) for v in mesh.extents],
        "stone_removed": stone_info,
        "watertight": bool(mesh.is_watertight),
        "volume_mm3": round(volume, 1) if volume else None,
        "estimated_metal_weight_g": weights,
        "wall_thickness_p5_mm": round(p5, 2) if p5 is not None else None,
        "percent_below_min_wall": round(thin, 1) if thin is not None else None,
        "min_wall_threshold_mm": MIN_WALL_MM,
        "warnings": warnings,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("glb")
    ap.add_argument("--inner-diameter", type=float, required=True, help="Finger-hole diameter in mm")
    ap.add_argument("--axis", choices=["auto", "x", "y", "z"], default="auto", help="Axis through the finger hole")
    ap.add_argument("--shrink", type=float, default=1.0, help="Scale factor for wax/casting compensation (1.0 = none)")
    ap.add_argument("--densities", help="JSON file {alloy: g/cm3} to override defaults")
    ap.add_argument("--no-stone", action="store_true", help="Cut out a center stone fused into the head")
    ap.add_argument("--out", default="out")
    args = ap.parse_args()

    dens = None
    if args.densities:
        with open(args.densities) as f:
            dens = json.load(f)
    name = os.path.splitext(os.path.basename(args.glb))[0]
    try:
        spec = process(args.glb, args.out, args.inner_diameter, args.shrink, dens, args.axis, args.no_stone, name)
    except RingError as e:
        sys.exit(str(e))
    with open(os.path.join(args.out, name + "_spec.json"), "w") as f:
        json.dump(spec, f, indent=2, ensure_ascii=False)
    print(json.dumps(spec, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
