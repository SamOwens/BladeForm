"""STL, project JSON, and HTML design-report export."""
from __future__ import annotations
import json, struct, base64, io, math, datetime
import numpy as np
from .mesh import build_scene
from .params import Design, validate
from .performance import evaluate, optimal_beta1, choke_mass_flow
from .fluids import air, water, custom
from . import cmap as cmapmod
from .units import SI, to_display, unit_label


def fluid_for(d: Design):
    if d.fluid_kind == "water":
        return water()
    if d.fluid_kind == "custom":
        return custom(**d.custom_fluid) if d.custom_fluid else air()
    return air()


# ---------------------------------------------------------------- STL
def export_stl(d: Design, path: str, lod: int = 2) -> dict:
    """Binary STL of the preview tessellation.

    Unlike STEP, an STL IS a mesh, so tying it to `lod` is correct here.
    """
    sc = build_scene(d, lod=lod)
    V, F = sc["vertices"], sc["faces"]
    tris = V[F]
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-16)
    with open(path, "wb") as fh:
        fh.write(b"BladeForm STL - preview tessellation, not a CAD solid".ljust(80, b"\0"))
        fh.write(struct.pack("<I", len(F)))
        for i in range(len(F)):
            fh.write(struct.pack("<12fH", *n[i], *tris[i][0], *tris[i][1],
                                 *tris[i][2], 0))
    return {"path": path, "triangles": int(len(F)), "lod": lod}


# ---------------------------------------------------------------- project JSON
PROJECT_VERSION = 1


def save_project(d: Design, path: str, snapshots=None) -> dict:
    payload = {"format": "bladeform-project", "version": PROJECT_VERSION,
               "saved": datetime.datetime.now().isoformat(timespec="seconds"),
               "design": d.to_dict(),
               "snapshots": snapshots or []}
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2)
    return {"path": path, "snapshots": len(payload["snapshots"])}


def load_project(path: str):
    with open(path) as fh:
        p = json.load(fh)
    if p.get("format") != "bladeform-project":
        raise ValueError("not a BladeForm project file")
    if p.get("version", 0) > PROJECT_VERSION:
        raise ValueError(f"project version {p['version']} is newer than this "
                         f"build understands (v{PROJECT_VERSION})")
    return Design.from_dict(p["design"]), p.get("snapshots", [])


# ---------------------------------------------------------------- HTML report
def _png_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    return base64.b64encode(buf.getvalue()).decode()


def _meridional_fig(d: Design):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from .geometry import MeridionalChannel
    ch = MeridionalChannel(d.r1_hub, d.r1_shroud, d.r2, d.b2,
                           d.axial_length, d.exit_pitch_deg)
    fig, ax = plt.subplots(figsize=(5.4, 4.0))
    for span, col, lab in ((0.0, "#8a6d3b", "hub"), (1.0, "#31708f", "shroud")):
        st = ch.streamline(span, 200)
        ax.plot(st["z"] * 1000, st["r"] * 1000, col, lw=2, label=lab)
    for span in (0.25, 0.5, 0.75):
        st = ch.streamline(span, 200)
        ax.plot(st["z"] * 1000, st["r"] * 1000, color="#c9c9c9", lw=.8)
    h, s = ch.streamline(0, 3), ch.streamline(1, 3)
    for i in (0, -1):
        ax.plot([h["z"][i] * 1000, s["z"][i] * 1000],
                [h["r"][i] * 1000, s["r"][i] * 1000], "k--", lw=1)
    ax.set_aspect("equal"); ax.grid(alpha=.3); ax.legend(fontsize=8)
    ax.set_xlabel("z [mm]"); ax.set_ylabel("r [mm]")
    ax.set_title("Meridional channel", fontsize=10)
    return fig


def export_report(d: Design, path: str, system: str = SI,
                  include_map: bool = True) -> dict:
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fl = fluid_for(d)
    op = evaluate(d, fl)
    b1h, b1s = optimal_beta1(d, fl)
    issues = validate(d)

    merid = _png_b64(_meridional_fig(d)); plt.close("all")
    map_png = None
    if include_map:
        m = cmapmod.generate_map(d, fl)
        fig, ax = plt.subplots(figsize=(6.2, 4.4))
        cm = plt.get_cmap("viridis")
        for i, ln in enumerate(m["lines"]):
            x = [p["corr_flow"] for p in ln["points"]]
            y = [p["y"] for p in ln["points"]]
            ax.plot(x, y, color=cm(i / max(len(m["lines"]) - 1, 1)), lw=1.6)
        if len(m["surge"]) > 1:
            sp = sorted(m["surge"]); ax.plot([p[0] for p in sp], [p[1] for p in sp],
                                             "--", color="#c0392b", lw=1.5,
                                             label="Surge (estimate)")
        if len(m["choke"]) > 1:
            cpts = sorted(m["choke"]); ax.plot([p[0] for p in cpts], [p[1] for p in cpts],
                                               ":", color="#2c3e50", lw=1.5,
                                               label="Choke (estimate)")
        ax.plot(m["design"]["corr_flow"], m["design"]["y"], "o", color="#e67e22",
                ms=8, mec="k", label="Design point")
        ax.set_xlabel("Corrected mass flow [kg/s]"); ax.set_ylabel(m["y_label"])
        ax.grid(alpha=.3); ax.legend(fontsize=8)
        ax.set_title("Performance map - 1D mean-line estimate", fontsize=10)
        map_png = _png_b64(fig); plt.close("all")

    def row(label, value, dim, places=4):
        v = to_display(value, dim, system)
        return (f"<tr><td>{label}</td><td class='n'>{v:.{places}g}</td>"
                f"<td class='u'>{unit_label(dim, system)}</td></tr>")

    geom = "".join([
        row("Inlet hub radius", d.r1_hub * 1000, "length_mm"),
        row("Inlet shroud radius", d.r1_shroud * 1000, "length_mm"),
        row("Exit radius", d.r2 * 1000, "length_mm"),
        row("Exit blade height", d.b2 * 1000, "length_mm"),
        row("Axial length", d.axial_length * 1000, "length_mm"),
        row("Hub fillet radius", d.hub_fillet * 1000, "length_mm"),
        row("Hub-tip ratio", d.hub_tip_ratio, "ratio", 3),
        row("Shaft speed", d.rpm, "rpm", 6),
    ])
    blade = "".join([
        f"<tr><td>Main blades</td><td class='n'>{d.n_main}</td><td class='u'>-</td></tr>",
        f"<tr><td>Splitter blades</td><td class='n'>{d.n_splitter}</td><td class='u'>-</td></tr>",
        row("Inlet blade angle (hub)", d.beta1_hub_deg, "angle", 3),
        row("Inlet blade angle (shroud)", d.beta1_shroud_deg, "angle", 3),
        row("Backsweep (exit)", d.beta2_hub_deg, "angle", 3),
        row("Zero-incidence beta1 hub (ref)", b1h or 0, "angle", 3),
        row("Zero-incidence beta1 shroud (ref)", b1s or 0, "angle", 3),
        f"<tr><td>Wrap-angle mode</td><td class='n'>{d.wrap_mode.value}</td>"
        f"<td class='u'>-</td></tr>",
    ])
    perf = "".join([
        row("Blade tip speed U2", op.U2, "speed"),
        row("Euler work", op.euler_work / 1000, "ratio"),
        row("Shaft power", op.power_W / 1000, "power"),
        row("Stage efficiency (est.)", op.eta_tt, "ratio", 3),
        row("Impeller efficiency (est.)", op.eta_impeller, "ratio", 3),
        row("Slip factor (Wiesner)", op.slip, "ratio", 3),
        row("Flow coefficient", op.flow_coeff, "ratio", 3),
        row("Work coefficient", op.work_coeff, "ratio", 3),
        row("Specific speed", op.specific_speed, "ratio", 3),
    ])
    if fl.compressible:
        perf += row("Pressure ratio (est.)", op.pressure_ratio, "ratio", 4)
        perf += row("Inducer tip relative Mach", op.M1_rel or 0, "ratio", 3)
        mc = choke_mass_flow(d, fl)
        if mc:
            perf += row("Choke mass flow (est.)", mc, "massflow", 4)
    else:
        perf += row("Head (est.)", op.head_m, "head")
        perf += row("NPSH required (est.)", op.npsh_required or 0, "head")
        perf += row("NPSH available", op.npsh_available or 0, "head")

    warn_html = "".join(
        f"<li class='{i.level}'><b>{i.field}</b>: {i.message}</li>" for i in issues) \
        or "<li class='ok'>No validation issues.</li>"
    msg_html = "".join(f"<li class='warn'>{m}</li>" for m in op.messages)

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>BladeForm design report - {d.name}</title><style>
body{{font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
max-width:960px;margin:2rem auto;padding:0 1.25rem;color:#1b2430}}
h1{{font-size:1.5rem;margin-bottom:.25rem}} h2{{font-size:1.05rem;margin-top:2rem;
border-bottom:1px solid #dde3ea;padding-bottom:.3rem}}
table{{border-collapse:collapse;width:100%;margin:.5rem 0}}
td{{padding:.3rem .5rem;border-bottom:1px solid #eef2f6}}
td.n{{text-align:right;font-variant-numeric:tabular-nums;font-weight:600;width:8rem}}
td.u{{color:#6b7885;width:6rem}}
.sub{{color:#6b7885;margin-top:0}} .cols{{display:flex;gap:1.5rem;flex-wrap:wrap}}
.cols>div{{flex:1 1 380px}} img{{max-width:100%;border:1px solid #e3e8ee;border-radius:6px}}
li.warn{{color:#a06a00}} li.error{{color:#b3261e}} li.ok{{color:#3a7d44}}
.note{{background:#fff8e6;border-left:3px solid #e0a800;padding:.6rem .9rem;
border-radius:4px;margin:1rem 0;font-size:.92rem}}
</style></head><body>
<h1>{d.name}</h1>
<p class="sub">BladeForm design report &middot; archetype <b>{d.archetype}</b>
&middot; fluid <b>{fl.name}</b> ({'compressible' if fl.compressible else 'incompressible'})
&middot; units <b>{system}</b> &middot; {datetime.datetime.now():%Y-%m-%d %H:%M}</p>

<div class="note"><b>All performance figures are first-order estimates</b> from a
1D mean-line model (Euler work, Wiesner slip, Oh/Jansen/Coppage-type loss
correlations). Surge and choke lines come from simple correlations, not CFD or
test data. Treat them as design-space guidance, not validated performance.</div>

<h2>Geometry</h2><div class="cols"><div><table>{geom}</table></div>
<div><img src="data:image/png;base64,{merid}" alt="meridional"></div></div>

<h2>Blade definition</h2><table>{blade}</table>

<h2>Derived performance</h2><table>{perf}</table>
{'<h2>Performance map</h2><img src="data:image/png;base64,' + map_png + '">' if map_png else ''}

<h2>Validation</h2><ul>{warn_html}{msg_html}</ul>
</body></html>"""
    with open(path, "w") as fh:
        fh.write(html)
    return {"path": path, "issues": len(issues), "bytes": len(html)}
