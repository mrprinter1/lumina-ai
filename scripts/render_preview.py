import sys
import numpy as np, trimesh
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
src, dst = sys.argv[1], sys.argv[2]
m = trimesh.load(src)
m.apply_translation(-m.bounds.mean(axis=0))
tri, n = m.triangles, m.face_normals
fig = plt.figure(figsize=(15, 5))
for i, (el, az, t) in enumerate([(25, -60, "3/4"), (0, -90, "front"), (90, -90, "top")]):
    ax = fig.add_subplot(1, 3, i + 1, projection="3d")
    a, e = np.radians(az + 40), np.radians(el + 30)
    L = np.array([np.cos(a) * np.cos(e), np.sin(a) * np.cos(e), np.sin(e)])
    sh = np.clip(n @ L, 0, 1) * 0.7 + 0.3
    col = np.outer(sh, [0.83, 0.69, 0.22])
    ax.add_collection3d(Poly3DCollection(tri, facecolors=np.c_[col, np.ones(len(col))], edgecolor="none"))
    r = m.extents.max() / 2
    ax.set_xlim(-r, r); ax.set_ylim(-r, r); ax.set_zlim(-r, r); ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=el, azim=az); ax.set_axis_off(); ax.set_title(t)
plt.tight_layout(); plt.savefig(dst, dpi=80)
