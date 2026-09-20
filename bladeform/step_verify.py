"""Independent verification of an exported STEP file.

FAILURE MODE 11: "it downloads" is not "it's correct". This module re-reads the
written file WITHOUT using the OpenCASCADE writer that produced it -- it is a
plain text parser over the STEP Part 21 entity list. It therefore cannot be
fooled by the same bug that wrote the file.

What it checks:
  * genuine curved surface entities are present (B_SPLINE_SURFACE etc.)
  * NO triangle-soup markers (POLY_LOOP / TRIANGULATED_*) -- the signature of a
    tessellated mesh wearing a STEP costume
  * the ratio of faces to surfaces is sane (a faked mesh has one flat PLANE and
    one 3-point POLY_LOOP per triangle)
"""
from __future__ import annotations
import re
from collections import Counter

SURFACE_TYPES = ["B_SPLINE_SURFACE_WITH_KNOTS", "B_SPLINE_SURFACE",
                 "CYLINDRICAL_SURFACE", "TOROIDAL_SURFACE", "CONICAL_SURFACE",
                 "SPHERICAL_SURFACE", "SURFACE_OF_REVOLUTION",
                 "SURFACE_OF_LINEAR_EXTRUSION", "PLANE"]
CURVED = [t for t in SURFACE_TYPES if t != "PLANE"]
MESH_MARKERS = ["POLY_LOOP", "TRIANGULATED_SURFACE_SET", "TESSELLATED_",
                "TRIANGULATED_FACE"]

_ENT = re.compile(r"#\d+\s*=\s*([A-Z_0-9]+)\s*\(", re.I)


def parse_entities(path: str) -> Counter:
    c = Counter()
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            for m in _ENT.finditer(line):
                c[m.group(1).upper()] += 1
    return c


def verify(path: str) -> dict:
    ents = parse_entities(path)
    faces = ents.get("ADVANCED_FACE", 0)
    curved = {t: ents.get(t, 0) for t in CURVED if ents.get(t, 0)}
    planes = ents.get("PLANE", 0)
    mesh_hits = {m: n for m in MESH_MARKERS
                 for n in [sum(v for k, v in ents.items() if k.startswith(m))] if n}

    problems = []
    if faces == 0:
        problems.append("no ADVANCED_FACE entities -- file has no B-rep geometry")
    if mesh_hits:
        problems.append(f"TRIANGLE-SOUP MARKERS PRESENT: {mesh_hits} -- this is a "
                        "tessellated mesh, not a B-rep solid")
    if not curved:
        problems.append("no curved surface entities -- every face is a PLANE, "
                        "which is what a faked mesh export looks like")
    if faces and planes / max(faces, 1) > 0.95:
        problems.append(f"{planes}/{faces} faces are planar -- suspicious")

    return {
        "path": path,
        "ok": not problems,
        "problems": problems,
        "advanced_faces": faces,
        "curved_surfaces": curved,
        "planes": planes,
        "closed_shells": ents.get("CLOSED_SHELL", 0),
        "manifold_solids": ents.get("MANIFOLD_SOLID_BREP", 0),
        "total_entities": sum(ents.values()),
    }


def compare_face_counts(path_a: str, path_b: str) -> dict:
    """Failure Mode 1's structural test: exports made at different PREVIEW
    tessellation settings must contain an identical number of faces."""
    a, b = verify(path_a), verify(path_b)
    return {"a_faces": a["advanced_faces"], "b_faces": b["advanced_faces"],
            "identical": a["advanced_faces"] == b["advanced_faces"],
            "a_curved": a["curved_surfaces"], "b_curved": b["curved_surfaces"]}
