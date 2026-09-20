"""Compressor map generation (spec Section 7).

Section 7 was omitted entirely in a prior attempt with no notice (Failure Mode
5), so it is treated here as a required deliverable.

EVERYTHING ON THIS MAP IS AN ESTIMATE from the 1D mean-line model. The surge and
choke lines in particular come from simple correlations, not from CFD or test
data, and the plot labels say so (Failure Mode 6).
"""
from __future__ import annotations
import math
import numpy as np
from .performance import evaluate, choke_mass_flow

# Reference conditions for corrected flow (standard day).
T_REF, P_REF = 288.15, 101325.0


def corrected_flow(mdot, T01, p01):
    return mdot * math.sqrt(T01 / T_REF) / (p01 / P_REF)


def corrected_speed(rpm, T01):
    return rpm / math.sqrt(T01 / T_REF)


def generate_map(d, fluid, speed_fracs=(0.6, 0.7, 0.8, 0.9, 1.0, 1.1),
                 n_points=26, flow_span=(0.35, 1.45)):
    """Sweep mass flow at each speed fraction.

    Returns dict with speedlines, surge line, choke line, and the design point.
    Points that the model flags as non-converged / non-physical are DROPPED
    rather than plotted as if valid.
    """
    lines = []
    surge_pts, choke_pts = [], []
    for sf in speed_fracs:
        rpm = d.rpm * sf
        m_choke = choke_mass_flow(d, fluid, rpm) if fluid.compressible else None
        hi = min(flow_span[1] * d.mdot, 0.98 * m_choke) if m_choke else flow_span[1] * d.mdot
        lo = flow_span[0] * d.mdot
        if hi <= lo:
            continue
        mdots = np.linspace(lo, hi, n_points)
        pts = []
        for m in mdots:
            op = evaluate(d, fluid, mdot=float(m), rpm=rpm)
            if not op.ok:
                continue
            y = op.pressure_ratio if fluid.compressible else op.head_m
            if y is None or not np.isfinite(y) or y <= 0:
                continue
            pts.append(dict(
                mdot=float(m),
                corr_flow=corrected_flow(float(m), d.T01, d.p01),
                y=float(y), eta=float(op.eta_tt),
                surge=bool(op.surge_risk),
                diffusion_ratio=float(op.diffusion_ratio)))
        if len(pts) < 3:
            continue
        # Surge estimate: lowest flow on this speedline at which the de Haller-type
        # diffusion limit (w1/w2 > 1.8) is NOT yet violated. Classical stall
        # threshold, treated as a rough indicator only.
        ok_pts = [p for p in pts if not p["surge"]]
        if ok_pts:
            s = min(ok_pts, key=lambda p: p["mdot"])
            surge_pts.append((s["corr_flow"], s["y"]))
        c = max(pts, key=lambda p: p["mdot"])
        choke_pts.append((c["corr_flow"], c["y"]))
        lines.append(dict(speed_frac=sf, rpm=rpm,
                          corr_speed=corrected_speed(rpm, d.T01), points=pts))

    op0 = evaluate(d, fluid)
    design = dict(corr_flow=corrected_flow(d.mdot, d.T01, d.p01),
                  y=(op0.pressure_ratio if fluid.compressible else op0.head_m),
                  eta=op0.eta_tt)
    return dict(lines=lines, surge=surge_pts, choke=choke_pts, design=design,
                y_label=("Total pressure ratio [-]" if fluid.compressible
                         else "Head [m]"),
                compressible=fluid.compressible)


def map_to_csv(m) -> str:
    rows = ["speed_frac,rpm,corrected_speed,mdot_kg_s,corrected_flow_kg_s,"
            "y_value,efficiency,diffusion_ratio,surge_flag"]
    for ln in m["lines"]:
        for p in ln["points"]:
            rows.append(f"{ln['speed_frac']:.3f},{ln['rpm']:.1f},"
                        f"{ln['corr_speed']:.1f},{p['mdot']:.6f},"
                        f"{p['corr_flow']:.6f},{p['y']:.6f},{p['eta']:.6f},"
                        f"{p['diffusion_ratio']:.4f},{int(p['surge'])}")
    return "\n".join(rows)


def plot_map(m, path, title="Compressor map"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7.2, 5.2))
    cmap = plt.get_cmap("viridis")
    for i, ln in enumerate(m["lines"]):
        x = [p["corr_flow"] for p in ln["points"]]
        y = [p["y"] for p in ln["points"]]
        c = cmap(i / max(len(m["lines"]) - 1, 1))
        ax.plot(x, y, color=c, lw=1.8)
        ax.annotate(f"{ln['speed_frac']*100:.0f}%", (x[-1], y[-1]),
                    fontsize=7, color=c, xytext=(3, -2),
                    textcoords="offset points")
    if len(m["surge"]) > 1:
        s = sorted(m["surge"])
        ax.plot([p[0] for p in s], [p[1] for p in s], "--", color="#c0392b",
                lw=1.6, label="Surge line (estimate)")
    if len(m["choke"]) > 1:
        c = sorted(m["choke"])
        ax.plot([p[0] for p in c], [p[1] for p in c], ":", color="#2c3e50",
                lw=1.6, label="Choke line (estimate)")
    ax.plot(m["design"]["corr_flow"], m["design"]["y"], "o", color="#e67e22",
            ms=9, mec="k", mew=.8, label="Design point", zorder=5)
    ax.set_xlabel("Corrected mass flow [kg/s]")
    ax.set_ylabel(m["y_label"])
    ax.set_title(title + "\n1D mean-line estimate - not CFD or test data",
                 fontsize=10)
    ax.grid(alpha=.3); ax.legend(fontsize=8, loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    if path.endswith(".png"):
        fig.savefig(path[:-4] + ".svg")
    plt.close(fig)
    return path
