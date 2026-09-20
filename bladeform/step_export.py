"""Genuine B-rep STEP export via OpenCASCADE (OCP).

FAILURE MODE 1 -- what this must NOT be.
  A previous attempt wrote each preview triangle as its own ADVANCED_FACE with a
  flat PLANE and a 3-point POLY_LOOP. That opens in a STEP viewer, which makes it
  a convincing fake rather than a harmless one.

What this module actually does instead:
  * Blade sections are interpolated as B-spline CURVES and lofted with
    BRepOffsetAPI_ThruSections -> the lateral surface is a real B_SPLINE_SURFACE.
  * The hub is a genuine SURFACE OF REVOLUTION of the hub meridional curve.
  * Hub fillets are real BRepFilletAPI surfaces, not chamfered facets.

Structural guarantee:
  N_SECTIONS / N_SECTION_PTS below are properties of the SURFACE DEFINITION and
  are deliberately module-level constants. The preview tessellation `lod` is not
  an input to this module at all, so the exported face count cannot vary with
  viewer detail. tests/test_step.py asserts byte-identical face counts across
  lod=0 and lod=2, which is the check Failure Mode 1 demands.
"""
from __future__ import annotations
import math
import numpy as np

from OCP.gp import gp_Pnt, gp_Ax1, gp_Ax2, gp_Dir, gp_Vec, gp_Pnt2d, gp_Circ
from OCP.collections import HArray1_gp_Pnt
from OCP.GeomAPI import GeomAPI_Interpolate
from OCP.GeomFill import GeomFill_BSplineCurves, GeomFill_FillingStyle
from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire,
                                BRepBuilderAPI_MakeFace, BRepBuilderAPI_Sewing,
                                BRepBuilderAPI_Transform, BRepBuilderAPI_MakeSolid)
from OCP.BRepOffsetAPI import (BRepOffsetAPI_ThruSections,
                               BRepOffsetAPI_MakeFilling)
from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol, BRepPrimAPI_MakePrism
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
from OCP.collections import List_TopoDS_Shape
from OCP.BRep import BRep_Tool
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.TopExp import TopExp_Explorer, TopExp
from OCP.collections import (IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as EdgeFaceMap)
from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_SOLID, TopAbs_SHELL
from OCP.BRep import BRep_Builder
from OCP.gp import gp_Trsf, gp_Ax3
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
from OCP.Interface import Interface_Static
from OCP.GeomAbs import GeomAbs_Shape
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
from OCP.ShapeFix import ShapeFix_Solid, ShapeFix_Shape

from .geometry import MeridionalChannel, build_blade

# --- SURFACE DEFINITION resolution. NOT tessellation. NOT tied to viewer LOD. ---
# Chosen because the boolean is reliable here on all four presets. Coarser
# (5 x 30) made the pump fuse return a ZERO-face shape while still reporting
# success; finer (9 x 60) made the fuse fail outright. Neither is tessellation:
# these fix the SURFACE definition and are independent of the preview LOD.
N_SECTIONS = 13        # spanwise sections lofted through (root-clustered)
N_SECTION_PTS = 44     # points interpolated per section curve
ROOT_BURY = -0.04      # blade root extends this far below the hub (span units)

Z_AXIS = gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1))


def _bspline_curve(pts: np.ndarray):
    """Open B-spline curve interpolated through pts (n,3)."""
    keep = [pts[0]]
    for q in pts[1:]:
        if np.linalg.norm(q - keep[-1]) > 1e-10:
            keep.append(q)
    pts = np.array(keep)
    if len(pts) < 2:
        raise RuntimeError("degenerate edge")
    arr = HArray1_gp_Pnt(1, len(pts))
    for i, (x, y, z) in enumerate(pts, start=1):
        arr.SetValue(i, gp_Pnt(float(x), float(y), float(z)))
    itp = GeomAPI_Interpolate(arr, False, 1e-9)
    itp.Perform()
    if not itp.IsDone():
        raise RuntimeError("edge interpolation failed")
    return itp.Curve()


def _bspline_edge(pts: np.ndarray):
    return BRepBuilderAPI_MakeEdge(_bspline_curve(pts)).Edge()


def _section_wire(P, S, C, i, t_le, t_te):
    """Closed 4-edge aerofoil section at span i.

    A single closed spline running pressure-LE-to-TE then suction-TE-to-LE puts
    a cusp at each end; interpolating through those cusps produced a
    self-intersecting surface and an INVALID solid, which then made the boolean
    fuse return an empty shape while still answering IsDone()=True.

    LE and TE are closed with STRAIGHT segments (blunt ends). An earlier version
    used a 3-point nose arc, but for thin blades (turbocharger t_le = 0.29 mm)
    the three points are nearly collinear and the resulting near-degenerate
    curve made the cap-filling step throw Standard_NoSuchObject. Blunt ends are
    also an honest representation of a blade with finite LE/TE thickness; add a
    nose radius downstream in CAD if a rounded LE is wanted.
    """
    p_side, s_side, cam = P[i], S[i], C[i]
    # ROUNDED LE/TE. Blunt straight ends create a sharp corner where the
    # pressure-root, end, and suction-root edges meet after the boolean. The
    # fillet then computed both contours as ChFiDS_Ok but still failed with a
    # faulty VERTEX at that corner. Rounding removes the corner so the root
    # junction is one smooth closed contour.
    d_le = cam[0] - cam[1]; d_le = d_le / max(np.linalg.norm(d_le), 1e-12)
    d_te = cam[-1] - cam[-2]; d_te = d_te / max(np.linalg.norm(d_te), 1e-12)
    # Nose offsets stay at the nominal half-THICKNESS. A root fillet widens the
    # section TANGENTIALLY; feeding that tangential width in here instead
    # pushed the leading edge forward by the fillet radius and inflated the
    # lofted volume by an order of magnitude. The two are different directions.
    nose_le = cam[0] + d_le * (t_le * 0.5)
    nose_te = cam[-1] + d_te * (t_te * 0.5)

    # Built head-to-tail as a closed loop P0 -> S0 -> Send -> Pend -> P0, so the
    # four curves can be handed straight to a Coons patch. Passing them in
    # non-chained order raised "invalid filling style".
    c_le = _bspline_curve(np.array([p_side[0], nose_le, s_side[0]]))
    c_suct = _bspline_curve(s_side)                        # S0 -> Send
    c_te = _bspline_curve(np.array([s_side[-1], nose_te, p_side[-1]]))
    c_press = _bspline_curve(p_side[::-1])                 # Pend -> P0

    mw = BRepBuilderAPI_MakeWire()
    for _c in (c_le, c_suct, c_te, c_press):
        mw.Add(BRepBuilderAPI_MakeEdge(_c).Edge())
    if not mw.IsDone():
        raise RuntimeError("section wire not closed")
    return mw.Wire(), (c_le, c_suct, c_te, c_press)


def _cap_face(curves):
    """Coons cap bounded by all FOUR section curves.

    A 2-curve GeomFill closes its ends with straight lines, which no longer
    matches the wire once LE/TE are rounded, leaving a sewing gap. The 4-curve
    Coons patch is bounded by exactly the curves the loft uses.
    """
    c1, c2, c3, c4 = curves
    srf = None
    tried = []
    for style in (GeomFill_FillingStyle.GeomFill_CoonsStyle,
                  GeomFill_FillingStyle.GeomFill_CurvedStyle,
                  GeomFill_FillingStyle.GeomFill_StretchStyle):
        try:
            srf = GeomFill_BSplineCurves(c1, c2, c3, c4, style).Surface()
            if srf is not None:
                break
        except Exception as exc:
            tried.append(f"{style}:{type(exc).__name__}")
    if srf is None:
        raise RuntimeError(f"cap surface construction failed ({tried})")
    mf = BRepBuilderAPI_MakeFace(srf, 1e-7)
    if not mf.IsDone():
        raise RuntimeError("cap face construction failed")
    return mf.Face()


def build_blade_solid(d, theta_offset=0.0, m_start_frac=0.0, bury=ROOT_BURY):
    """One blade as a closed B-rep solid: 4 lofted B-spline faces + 2 filled caps."""
    ch = MeridionalChannel(d.r1_hub, d.r1_shroud, d.r2, d.b2,
                           d.axial_length, d.exit_pitch_deg)
    b = build_blade(ch, d, N_SECTIONS, N_SECTION_PTS, theta_offset, m_start_frac,
                    span_min=bury)
    sections = [_section_wire(b.pressure, b.suction, b.camber, i, d.t_le, d.t_te)
                for i in range(N_SECTIONS)]
    wires = [w for w, _ in sections]

    # RULED between sections. A smooth loft overshoots between the closely
    # spaced sections the root fillet needs and self-intersects, inflating the
    # solid by up to 1000x while still reporting valid. Ruled surfaces are
    # genuine B-rep (they export as B_SPLINE_SURFACE) and cannot overshoot.
    loft = BRepOffsetAPI_ThruSections(False, True, 1e-6)    # SHELL, ruled
    for w in wires:
        loft.AddWire(w)
    loft.Build()
    if not loft.IsDone():
        raise RuntimeError("blade loft failed")

    sew = BRepBuilderAPI_Sewing(1e-6)
    sew.Add(loft.Shape())
    sew.Add(_cap_face(sections[0][1]))
    sew.Add(_cap_face(sections[-1][1]))
    sew.Perform()
    shell = sew.SewedShape()

    mk = BRepBuilderAPI_MakeSolid()
    ex = TopExp_Explorer(shell, TopAbs_SHELL)
    ns = 0
    while ex.More():
        mk.Add(TopoDS.Shell(ex.Current())); ns += 1; ex.Next()
    if ns != 1:
        raise RuntimeError(f"sewing produced {ns} shells, expected 1 "
                           "(blade surfaces did not close)")
    solid = mk.Solid()
    fix = ShapeFix_Solid(solid)
    fix.Perform()
    solid = fix.Solid()
    # Fold detector. BRepCheck does not test self-intersection, so a folded
    # loft can report valid while its volume integral is nonsense. A blade
    # cannot plausibly exceed the annulus it lives in.
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(solid, g)
    envelope = math.pi * d.r2 ** 2 * max(d.axial_length, d.b2)
    if not (0 < g.Mass() < 0.5 * envelope):
        raise RuntimeError(
            f"blade solid volume {g.Mass():.3e} m^3 is implausible against a "
            f"{envelope:.3e} m^3 envelope -- the loft has folded (check the "
            "root fillet width against blade pitch)")
    if not BRepCheck_Analyzer(solid).IsValid():
        raise RuntimeError("blade solid is INVALID -- refusing to export it "
                           "(an invalid solid makes booleans silently return "
                           "empty shapes while still reporting IsDone)")
    return solid


def build_hub_solid(d):
    """Hub as a real SURFACE OF REVOLUTION of the hub meridional contour.

    The profile is a closed planar wire in the XZ half-plane:
        bore -> inlet annulus -> [B-spline hub contour] -> back face -> bore
    A shaft bore is included so the profile never touches the axis, which
    avoids the degenerate-apex construction error a single-spline profile hit.
    """
    ch = MeridionalChannel(d.r1_hub, d.r1_shroud, d.r2, d.b2,
                           d.axial_length, d.exit_pitch_deg)
    st = ch.streamline(0.0, 90)
    z, r = st["z"], st["r"]
    z0, zmax = float(z[0]), float(z[-1])
    r_bore = 0.35 * d.r1_hub

    # B-spline edge through the hub contour
    arr = HArray1_gp_Pnt(1, len(z))
    for i, (zz, rr) in enumerate(zip(z, r), start=1):
        arr.SetValue(i, gp_Pnt(float(rr), 0.0, float(zz)))
    itp = GeomAPI_Interpolate(arr, False, 1e-9)
    itp.Perform()
    if not itp.IsDone():
        raise RuntimeError("hub contour interpolation failed")
    e_contour = BRepBuilderAPI_MakeEdge(itp.Curve()).Edge()

    A = gp_Pnt(r_bore, 0.0, z0)
    B = gp_Pnt(float(r[0]), 0.0, z0)
    C = gp_Pnt(float(r[-1]), 0.0, zmax)
    D = gp_Pnt(r_bore, 0.0, zmax)

    mw = BRepBuilderAPI_MakeWire()
    mw.Add(BRepBuilderAPI_MakeEdge(A, B).Edge())   # inlet annular face
    mw.Add(e_contour)                              # contoured flow surface
    mw.Add(BRepBuilderAPI_MakeEdge(C, D).Edge())   # back face
    mw.Add(BRepBuilderAPI_MakeEdge(D, A).Edge())   # bore
    wire = mw.Wire()
    face = BRepBuilderAPI_MakeFace(wire, True).Face()
    rev = BRepPrimAPI_MakeRevol(face, Z_AXIS)
    rev.Build()
    if not rev.IsDone():
        raise RuntimeError("hub revolve failed")
    return rev.Shape()


def _rotate(shape, angle):
    t = gp_Trsf(); t.SetRotation(Z_AXIS, angle)
    return BRepBuilderAPI_Transform(shape, t, True).Shape()


def build_impeller(d, apply_fillet=True):
    """Fuse hub + all blades, then fillet the blade-hub junction edges."""
    notes = []
    hub = build_hub_solid(d)
    base_blade = build_blade_solid(d, 0.0, 0.0)
    per_passage = (d.n_splitter // d.n_main) if d.n_main else 0
    base_split = (build_blade_solid(d, 0.0, d.splitter_start_frac)
                  if per_passage else None)

    # ONE multi-tool boolean instead of N sequential pairwise fuses. Sequential
    # fusing took ~60-95 s per blade and got slower as the shape grew; a single
    # fuse with all blades as tools runs the intersection once.
    tools = List_TopoDS_Shape()
    for k in range(d.n_main):
        th0 = 2 * math.pi * k / max(d.n_main, 1)
        tools.Append(_rotate(base_blade, th0))
        for sidx in range(per_passage):
            frac = (sidx + 1) / (per_passage + 1)
            tools.Append(_rotate(base_split, th0 + 2 * math.pi * frac / d.n_main))
    tool_list = list(tools)
    args = List_TopoDS_Shape(); args.Append(hub)
    fu = BRepAlgoAPI_Fuse()
    fu.SetArguments(args); fu.SetTools(tools); fu.SetRunParallel(True)
    fu.Build()
    if not fu.IsDone():
        raise RuntimeError("impeller fuse failed")
    shape = fu.Shape()
    _fuse = fu

    # Guards against the boolean "succeeding" with nothing in it. OCC returned
    # IsDone()=True with a 0-face shape for one preset/resolution combination,
    # and has also silently swallowed blades when inputs were coincident.
    hub_faces, hub_vol = count_faces(hub), _volume(hub)
    n_blades = d.n_main + (d.n_splitter if per_passage else 0)
    if count_faces(shape) == 0:
        raise RuntimeError("fuse returned a shape with ZERO faces "
                           "(IsDone reported success)")
    if not BRepCheck_Analyzer(shape).IsValid():
        # Boolean results routinely need repair (tiny gaps, wrong orientations).
        # Earlier versions of this file never checked, so INVALID solids were
        # being written to STEP and verified as if fine.
        fx = ShapeFix_Shape(shape)
        fx.SetPrecision(1e-7); fx.SetMaxTolerance(1e-4)
        fx.Perform()
        shape = fx.Shape()
        if not BRepCheck_Analyzer(shape).IsValid():
            raise RuntimeError("fused impeller is not a valid solid, and "
                               "ShapeFix could not repair it")
        notes.append("Fused shape required ShapeFix repair to become a valid solid.")
    vol = _volume(shape)
    if vol <= hub_vol * 1.0001:
        raise RuntimeError(
            f"fuse added no material: volume {vol:.3e} vs hub alone "
            f"{hub_vol:.3e} -- the blades were swallowed rather than fused")
    if count_faces(shape) <= hub_faces:
        raise RuntimeError(
            f"fuse produced {count_faces(shape)} faces but the hub alone has "
            f"{hub_faces} -- blades did not survive the boolean")

    n_faces_prefillet = count_faces(shape)

    if apply_fillet and d.hub_fillet > 1e-6:
        edges = hub_blade_junction_edges(shape, fu, hub, tool_list)
        # NOTE: fu.SectionEdges() also reports 6 edges here, but they are not the
        # same topological objects as the ones inside the fused shape, so
        # BRepFilletAPI accepted them and then failed with IsDone()=False.
        # Selecting from the fused shape's own edge->face map avoids that.
        if edges:
            fil = BRepFilletAPI_MakeFillet(shape)
            for e in edges:
                fil.Add(float(d.hub_fillet), e)
            try:
                fil.Build()
                if fil.IsDone():
                    filleted = fil.Shape()
                    nf = count_faces(filleted)
                    if nf > n_faces_prefillet:
                        shape = filleted
                        notes.append(
                            f"Hub fillet r={d.hub_fillet*1000:.3f} mm applied to "
                            f"{len(edges)} blade-hub edges "
                            f"({n_faces_prefillet} -> {nf} faces).")
                    else:
                        notes.append("FILLET PRODUCED NO NEW FACES -- treated as "
                                     "failed; sharp junctions exported.")
                else:
                    notes.append(f"FILLET FAILED (IsDone=False) on {len(edges)} "
                                 "edges -- sharp junctions exported. Try a "
                                 "smaller radius.")
            except Exception as exc:
                notes.append(f"FILLET FAILED ({type(exc).__name__}) -- sharp "
                             "junctions exported.")
        else:
            notes.append("FILLET SKIPPED -- no blade-hub junction edges found.")
    elif d.hub_fillet <= 1e-6:
        notes.append("Hub fillet radius is zero -- sharp junctions by request.")
    return shape, notes, n_faces_prefillet


def _result_faces(fu, src):
    """Faces of the boolean RESULT that came from `src`."""
    out = set()
    ex = TopExp_Explorer(src, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face(ex.Current())
        mod = list(fu.Modified(f))
        if mod:
            for m in mod:
                out.add(m.TShape())
        elif not fu.IsDeleted(f):
            out.add(f.TShape())
        ex.Next()
    return out


def hub_blade_junction_edges(shape, fu=None, hub=None, tools=None):
    """Edges of the FUSED shape lying between a hub face and a blade face.

    Provenance from the boolean itself, not a surface-type guess. An earlier
    version required one face to be a SurfaceOfRevolution and the other a
    B-spline, which silently dropped every edge where the blade crosses the
    hub's PLANAR inlet annulus and back face. That left the root loop OPEN,
    and filleting an open chain is exactly what produced ChFiDS_WalkingFailure
    at its free ends. On one pump case the old filter found 9 edges where the
    true junction has 18.
    """
    if fu is None or hub is None or tools is None:
        raise ValueError("junction edge selection needs the boolean's provenance")
    hub_set = _result_faces(fu, hub)
    blade_set = set()
    for t in tools:
        blade_set |= _result_faces(fu, t)

    m = EdgeFaceMap()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, m)
    out = []
    for i in range(1, m.Size() + 1):
        faces = list(m.FindFromIndex(i))
        if len(faces) != 2:
            continue
        a, b = faces[0].TShape(), faces[1].TShape()
        if (a in hub_set and b in blade_set) or (b in hub_set and a in blade_set):
            out.append(TopoDS.Edge(m.FindKey(i)))
    return out


def _volume(shape) -> float:
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, g)
    return float(g.Mass())


def count_faces(shape) -> int:
    n = 0
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        n += 1; ex.Next()
    return n


def diffuser_vane_angles(d, fluid=None):
    """Vane inlet/exit flow angles from radial, degrees.

    The inlet angle is the swirl the impeller actually delivers, carried out to
    the vane leading edge as a free vortex (c_th*r constant) with continuity on
    the meridional component. Using a fixed stagger instead means the vanes are
    drawn at whatever angle looks plausible rather than the one the flow
    arrives at.
    """
    from .performance import evaluate
    from .fluids import air, water, custom as custom_fluid
    if fluid is None:
        fluid = (water() if d.fluid_kind == "water"
                 else custom_fluid(**d.custom_fluid) if d.fluid_kind == "custom"
                 else air())
    op = evaluate(d, fluid)
    r3 = d.r2 * 1.04
    if not op.ok or op.c_m2 <= 0:
        return 65.0, 65.0 - d.diffuser_turn_deg
    c_th3 = op.c_th2 * d.r2 / r3                       # free vortex
    c_m3 = op.c_m2 * d.r2 * d.b2 / (r3 * d.b2)         # continuity, constant width
    a3 = math.degrees(math.atan2(c_th3, max(c_m3, 1e-9)))
    return a3, max(a3 - d.diffuser_turn_deg, 5.0)


def build_diffuser_vanes(d):
    """Vaned diffuser as prismatic solids: a cambered profile extruded across
    the passage width. Planar caps + extruded lateral faces, all genuine B-rep."""
    if not d.diffuser_on or d.diffuser_vanes < 1:
        return []
    a3, a4 = diffuser_vane_angles(d)
    r3, r4 = d.r2 * 1.04, d.r2 * d.diffuser_ratio
    if r4 <= r3 * 1.02:
        return []
    z_lo = d.axial_length - d.b2
    n = 40
    rs = np.linspace(r3, r4, n)
    al = np.radians(np.linspace(a3, a4, n))
    # dtheta/dr = tan(alpha)/r  with alpha measured from radial
    integrand = np.tan(al) / np.maximum(rs, 1e-9)
    th = np.concatenate([[0.0], np.cumsum(0.5 * (integrand[1:] + integrand[:-1]) * np.diff(rs))])
    t_max = max((r4 - r3) * 0.06, d.t_te)
    sh = (rs - r3) / max(r4 - r3, 1e-9)
    t = t_max * (0.35 + 0.65 * np.sin(np.pi * np.clip(sh, 0, 1)) ** 0.7)
    dth = t / (2.0 * np.maximum(rs, 1e-9) * np.maximum(np.cos(al), 0.2))

    out = []
    for k in range(d.diffuser_vanes):
        off = 2 * math.pi * k / d.diffuser_vanes
        press = np.stack([rs * np.cos(th - dth + off), rs * np.sin(th - dth + off),
                          np.full(n, z_lo)], axis=-1)
        suct = np.stack([rs * np.cos(th + dth + off), rs * np.sin(th + dth + off),
                         np.full(n, z_lo)], axis=-1)
        mw = BRepBuilderAPI_MakeWire()
        mw.Add(BRepBuilderAPI_MakeEdge(_bspline_curve(press)).Edge())
        mw.Add(BRepBuilderAPI_MakeEdge(
            gp_Pnt(*map(float, press[-1])), gp_Pnt(*map(float, suct[-1]))).Edge())
        mw.Add(BRepBuilderAPI_MakeEdge(_bspline_curve(suct[::-1])).Edge())
        mw.Add(BRepBuilderAPI_MakeEdge(
            gp_Pnt(*map(float, suct[0])), gp_Pnt(*map(float, press[0]))).Edge())
        if not mw.IsDone():
            continue
        face = BRepBuilderAPI_MakeFace(mw.Wire(), True).Face()
        prism = BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, float(d.b2))).Shape()
        if BRepCheck_Analyzer(prism).IsValid():
            out.append(prism)
    return out


def build_volute(d):
    """Collector scroll: circular sections lofted along a spiral.

    Cross-section area follows A(theta) = A_exit * (theta/2pi)^n, so the exit
    pipe area and the scroll are consistent by construction rather than being
    two unrelated numbers.
    """
    if not d.volute_on:
        return []
    r_in = d.r2 * (d.diffuser_ratio if d.diffuser_on else 1.08)
    z_c = d.axial_length - d.b2 * 0.5
    A_exit = math.pi * (d.volute_exit_d / 2.0) ** 2
    n = 33
    loft = BRepOffsetAPI_ThruSections(True, False, 1e-6)
    added = 0
    for i in range(n):
        frac = 0.04 + 0.96 * i / (n - 1)          # start at the tongue, not zero
        area = A_exit * max(frac, 1e-4) ** max(d.volute_area_exponent, 0.2)
        a = math.sqrt(area / math.pi)
        ang = 2 * math.pi * frac
        Rc = r_in + a
        centre = gp_Pnt(Rc * math.cos(ang), Rc * math.sin(ang), z_c)
        tangent = gp_Dir(-math.sin(ang), math.cos(ang), 0.0)
        circ = gp_Circ(gp_Ax2(centre, tangent), a)
        edge = BRepBuilderAPI_MakeEdge(circ).Edge()
        loft.AddWire(BRepBuilderAPI_MakeWire(edge).Wire())
        added += 1
    if added < 2:
        return []
    loft.Build()
    if not loft.IsDone():
        return []
    shp = loft.Shape()
    return [shp] if BRepCheck_Analyzer(shp).IsValid() else []


def build_compound(d):
    """Hub and blades as SEPARATE valid solids in one STEP assembly.

    No boolean, so nothing can be silently swallowed or degraded. Every solid is
    individually checked. This is a genuine multi-body B-rep assembly (the kind
    CAD systems exchange all the time), NOT a mesh -- but it has no hub fillet,
    because the blade-hub junction does not exist as an edge until the bodies
    are united. Downstream CAD can unite and fillet it.
    """
    notes = []
    builder = BRep_Builder()
    comp = TopoDS_Compound()
    builder.MakeCompound(comp)

    hub = build_hub_solid(d)
    if not BRepCheck_Analyzer(hub).IsValid():
        raise RuntimeError("hub solid is invalid")
    builder.Add(comp, hub)

    base_blade = build_blade_solid(d, 0.0, 0.0)
    per_passage = (d.n_splitter // d.n_main) if d.n_main else 0
    base_split = (build_blade_solid(d, 0.0, d.splitter_start_frac)
                  if per_passage else None)
    n = 0
    for k in range(d.n_main):
        th0 = 2 * math.pi * k / max(d.n_main, 1)
        builder.Add(comp, _rotate(base_blade, th0)); n += 1
        for sidx in range(per_passage):
            frac = (sidx + 1) / (per_passage + 1)
            builder.Add(comp, _rotate(base_split,
                        th0 + 2 * math.pi * frac / d.n_main)); n += 1
    n_extra = 0
    for extra in build_diffuser_vanes(d):
        builder.Add(comp, extra); n_extra += 1
    if n_extra:
        a3, a4 = diffuser_vane_angles(d)
        notes.append(f"{n_extra} diffuser vanes, leading edge set to the "
                     f"{a3:.1f} deg swirl the impeller delivers, turning to "
                     f"{a4:.1f} deg.")
    for extra in build_volute(d):
        builder.Add(comp, extra); n_extra += 1
        notes.append(f"Volute scroll, area growing as (theta/2pi)^"
                     f"{d.volute_area_exponent:g} to a {d.volute_exit_d*1000:.0f} mm exit.")
    notes.append(
        f"Multi-body assembly: 1 hub + {n} blade solids"
        + (f" + {n_extra} downstream solids" if n_extra else "")
        + ", each individually validated. The hub fillet "
        f"(r={d.hub_fillet*1000:.3f} mm) is a blend modelled into the blade "
        "surface, not a kernel fillet operation -- see STATUS.md.")
    return comp, notes, count_faces(comp)


def export_step(d, path: str, apply_fillet=True, schema="AP214", mode="compound"):
    """mode='compound' (default, reliable) or 'fused' (single solid, fragile).

    'fused' runs a boolean per blade. On the machine this was developed on it
    took ~19 s for one blade and ~195 s for three, and produced an INVALID solid
    for 3 of the 4 presets (ShapeFix could not repair it). It is kept because it
    is the only path that can carry a hub fillet, but it is not the default and
    it validates its own output rather than trusting IsDone().
    """
    if mode == "compound":
        shape, notes, pre = build_compound(d)
    elif mode == "fused":
        shape, notes, pre = build_impeller(d, apply_fillet)
    else:
        raise ValueError(f"unknown export mode {mode!r}")
    # Geometry in this package is always SI metres. CAD (Onshape, SolidWorks,
    # etc.) expects STEP coordinates in millimetres. Relying on OCC's unit
    # statics is flaky across versions, so scale the solid ×1000 explicitly
    # before writing and leave write.step.unit at its default (MM).
    trsf = gp_Trsf()
    trsf.SetScaleFactor(1000.0)  # m → mm
    shape_mm = BRepBuilderAPI_Transform(shape, trsf, True).Shape()

    Interface_Static.SetCVal_s("write.step.schema", schema)
    Interface_Static.SetIVal_s("write.surfacecurve.mode", 1)
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    w = STEPControl_Writer()
    w.Transfer(shape_mm, STEPControl_AsIs)
    status = w.Write(path)
    return {"path": path, "mode": mode, "faces": count_faces(shape_mm),
            "faces_before_fillet": pre, "notes": notes, "status": str(status),
            "units": "mm (scaled ×1000 from SI metres)"}
