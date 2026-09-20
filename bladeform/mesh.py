"""Tessellation for the live 3D preview.

This mesh is for DISPLAY ONLY. It is deliberately separate from the export
path: STEP export builds B-rep surfaces from the same parametric definition,
never from this mesh (Failure Mode 1). `lod` changes this mesh's triangle count
and must have NO effect on the exported STEP face count -- tests/test_step.py
asserts exactly that.
"""
from __future__ import annotations
import numpy as np
import math
from .geometry import MeridionalChannel, build_blade


def _grid_faces(ni, nj, offset=0, flip=False):
    f = []
    for i in range(ni - 1):
        for j in range(nj - 1):
            a = offset + i * nj + j
            b = a + 1
            c = a + nj
            d = c + 1
            f += [[a, c, b], [b, c, d]] if not flip else [[a, b, c], [b, d, c]]
    return f


def orient_faces(V, F):
    """Make every triangle in a closed shell wind the same way, outward.

    The hand-written patch orientations in blade_mesh left 148 of 1614 edges
    wound the same direction on both sides -- a closed shell with inconsistent
    normals. It renders fine with double-sided materials, which is exactly why
    it went unnoticed, but it flips ~9% of STL facet normals and makes any
    divergence-theorem volume wrong (it disagreed with the CAD kernel by 3x).

    Every edge is used exactly twice, so a breadth-first walk over shared edges
    fixes orientation; a final signed-volume check fixes outward vs inward.
    """
    F = np.asarray(F).copy()
    edge_map = {}
    for ti, tri in enumerate(F):
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            edge_map.setdefault((min(a, b), max(a, b)), []).append(ti)

    seen = np.zeros(len(F), dtype=bool)
    from collections import deque
    for seed in range(len(F)):
        if seen[seed]:
            continue
        seen[seed] = True
        q = deque([seed])
        while q:
            ti = q.popleft()
            tri = F[ti]
            directed = {(tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])}
            for a, b in list(directed):
                for tj in edge_map.get((min(a, b), max(a, b)), ()):
                    if tj == ti or seen[tj]:
                        continue
                    nb = F[tj]
                    # same direction on both sides -> the neighbour is flipped
                    if (a, b) in {(nb[0], nb[1]), (nb[1], nb[2]), (nb[2], nb[0])}:
                        F[tj] = [nb[0], nb[2], nb[1]]
                    seen[tj] = True
                    q.append(tj)

    tri = V[F]
    vol = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0
    if vol < 0:
        F = F[:, ::-1].copy()
    return F


def signed_volume(V, F):
    tri = V[F]
    return float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0)


def blade_mesh(P, S):
    """Closed blade shell from pressure/suction grids, with LE/TE and tip caps."""
    ni, nj, _ = P.shape
    verts = [P.reshape(-1, 3), S.reshape(-1, 3)]
    n = ni * nj
    faces = _grid_faces(ni, nj, 0, flip=False) + _grid_faces(ni, nj, n, flip=True)

    # leading edge (j=0) and trailing edge (j=nj-1) closing strips
    for j, flip in ((0, True), (nj - 1, False)):
        for i in range(ni - 1):
            a, b = i * nj + j, (i + 1) * nj + j
            c, d = n + a, n + b
            faces += [[a, c, b], [b, c, d]] if not flip else [[a, b, c], [b, d, c]]
    # tip cap (i = ni-1) and hub cap (i = 0)
    for i, flip in ((0, False), (ni - 1, True)):
        for j in range(nj - 1):
            a, b = i * nj + j, i * nj + j + 1
            c, d = n + a, n + b
            faces += [[a, c, b], [b, c, d]] if not flip else [[a, b, c], [b, d, c]]
    V = np.vstack(verts)
    return V, orient_faces(V, np.array(faces, dtype=np.int64))


def build_scene(d, lod: int = 1):
    """Full impeller tessellation. lod 0=coarse 1=normal 2=fine."""
    n_span = (5, 9, 15)[lod]
    n_stream = (24, 44, 80)[lod]
    n_theta = (48, 96, 160)[lod]

    ch = MeridionalChannel(d.r1_hub, d.r1_shroud, d.r2, d.b2,
                           d.axial_length, d.exit_pitch_deg)

    V, F, groups = [], [], []
    base = 0

    def add(v, f, tag):
        nonlocal base
        V.append(v); F.append(f + base)
        groups.append((tag, base, base + len(v)))
        base += len(v)

    # main blades, evenly spaced
    per_passage = (d.n_splitter // d.n_main) if d.n_main else 0
    blades = []
    for k in range(d.n_main):
        th0 = 2 * math.pi * k / max(d.n_main, 1)
        blades.append((th0, 0.0, "main"))
        for sidx in range(per_passage):
            frac = (sidx + 1) / (per_passage + 1)
            blades.append((th0 + 2 * math.pi * frac / d.n_main,
                           d.splitter_start_frac, "splitter"))

    first = None
    for th0, mstart, tag in blades:
        b = build_blade(ch, d, n_span, n_stream, th0, mstart)
        if first is None:
            first = b
        v, f = blade_mesh(b.pressure, b.suction)
        add(v, f, tag)

    # hub: revolved meridional contour (NOT a disc)
    st = ch.streamline(0.0, n_stream)
    th = np.linspace(0, 2 * np.pi, n_theta)
    Z, TH = np.meshgrid(st["z"], th, indexing="ij")
    R, _ = np.meshgrid(st["r"], th, indexing="ij")
    hv = np.stack([R * np.cos(TH), R * np.sin(TH), Z], axis=-1).reshape(-1, 3)
    add(hv, np.array(_grid_faces(n_stream, n_theta), dtype=np.int64), "hub")

    return {
        "vertices": np.vstack(V),
        "faces": np.vstack(F),
        "groups": groups,
        "blade": first,
        "channel": ch,
        "shroud": np.stack([ch.streamline(1.0, n_stream)["z"],
                            ch.streamline(1.0, n_stream)["r"]], axis=-1),
        "tri_count": int(sum(len(f) for f in F)),
    }
