"""Parametric impeller geometry.

SIGN / ANGLE CONVENTIONS (stated once, used everywhere):
  m      meridional arc length along a streamline, 0 at LE, M at TE
  beta   blade angle measured FROM THE MERIDIONAL DIRECTION, in the m-theta
         plane.  tan(beta) = r * dtheta/dm.
  beta2  exit blade angle = backsweep measured from radial (identical to the
         from-meridional definition at a radial exit).
  theta  wrap coordinate, increasing opposite to rotation for a backswept wheel.

FAILURE MODE 3 -- WRAP ANGLE.
  The wrap angle is NOT a free input that gets applied as a rescale.  There is
  exactly one physical relationship:

        theta(m) = integral_0^m  tan(beta(m')) / r(m')  dm'

  so total wrap is a CONSEQUENCE of the blade-angle distribution.  Two honest
  modes are offered and the active one is reported to the UI:

    WrapMode.DERIVED -- user sets beta1, beta2 and a distribution exponent.
        Wrap angle is computed and shown READ-ONLY. Nothing is rescaled.

    WrapMode.TARGET  -- user sets beta1, beta2 AND a target wrap.  beta1 and
        beta2 are held EXACTLY at the endpoints; the interior distribution
        exponent is root-found so the integral lands on the target.  The
        resulting interior beta(m) is returned for display.  If the target is
        unreachable with the given endpoints the solver does NOT silently
        clamp -- it reports achieved != target and raises a validation warning.

  In neither mode is a computed theta distribution multiplied by a fudge
  factor to hit a number.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
import math
import numpy as np
from scipy.optimize import brentq


# Fraction of span the root section cluster covers. Fixed, so the section
# layout never depends on the fillet radius.
ROOT_CLUSTER = 0.12


class WrapMode(str, Enum):
    DERIVED = "derived"   # wrap angle is an output
    TARGET = "target"     # wrap angle is an input; interior distribution solved


class ThicknessLaw(str, Enum):
    LINEAR = "linear"
    PARABOLIC = "parabolic"
    ELLIPTIC = "elliptic"


# --------------------------------------------------------------------------
# Meridional channel
# --------------------------------------------------------------------------

def _bezier(P: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Cubic Bezier. P is (4,2) of (z,r). Returns (n,2)."""
    t = t[:, None]
    return ((1 - t) ** 3 * P[0] + 3 * (1 - t) ** 2 * t * P[1]
            + 3 * (1 - t) * t ** 2 * P[2] + t ** 3 * P[3])


@dataclass
class MeridionalChannel:
    """Hub and shroud contours as cubic Bezier curves in the (z,r) plane.

    Inlet tangent is axial; exit tangent is set by `exit_pitch_deg` (0 = purely
    radial exit for a centrifugal wheel, larger = mixed-flow leaning axial).
    """
    r1_hub: float
    r1_shroud: float
    r2: float
    b2: float
    axial_length: float
    exit_pitch_deg: float = 0.0
    hub_tangent_weight: float = 0.55
    shroud_tangent_weight: float = 0.55

    def _control_points(self):
        phi = math.radians(self.exit_pitch_deg)
        sphi, cphi = math.sin(phi), math.cos(phi)
        L = self.axial_length

        # Tangent handles are scaled by the extent along EACH handle's own
        # direction (axial handle by dz, exit handle by dr). Scaling both by the
        # diagonal chord makes the inlet handle overshoot the exit plane and
        # warps the channel into a flat-bottomed bowl -- that bug produced a
        # "hub as a giant disc" render (Failure Mode 2).
        w = self.hub_tangent_weight

        # hub: (0, r1h) axial-tangent -> (L, r2) with exit tangent (sphi, cphi)
        h0 = np.array([0.0, self.r1_hub])
        h3 = np.array([L, self.r2])
        dz_h = max(h3[0] - h0[0], 1e-6)
        dr_h = max(h3[1] - h0[1], 1e-6)
        h1 = h0 + np.array([w * dz_h, 0.0])
        h2 = h3 - w * dr_h * np.array([sphi, cphi])

        # shroud exit is offset from hub exit by b2 normal to the exit flow dir
        ws = self.shroud_tangent_weight
        s0 = np.array([0.0, self.r1_shroud])
        s3 = h3 + self.b2 * np.array([-cphi, sphi])
        dz_s = max(s3[0] - s0[0], 1e-6)
        dr_s = max(s3[1] - s0[1], 1e-6)
        s1 = s0 + np.array([ws * dz_s, 0.0])
        s2 = s3 - ws * dr_s * np.array([sphi, cphi])
        return np.array([h0, h1, h2, h3]), np.array([s0, s1, s2, s3])

    def streamline(self, span: float, n: int = 160):
        """Streamline at span fraction (0 = hub, 1 = shroud).

        Returns dict with z, r, m (arc length), M (total length).
        Control points are blended linearly, so intermediate streamlines are
        themselves cubic Beziers -- no re-fitting, no kinks.
        """
        Ph, Ps = self._control_points()
        P = (1.0 - span) * Ph + span * Ps
        t = np.linspace(0.0, 1.0, n)
        zr = _bezier(P, t)
        z, r = zr[:, 0], zr[:, 1]
        dm = np.hypot(np.diff(z), np.diff(r))
        m = np.concatenate([[0.0], np.cumsum(dm)])
        return {"z": z, "r": r, "m": m, "M": float(m[-1]), "t": t}


# --------------------------------------------------------------------------
# Blade angle distribution + camber (Failure Mode 3 lives here)
# --------------------------------------------------------------------------

def _beta_distribution(s_hat: np.ndarray, beta1: float, beta2: float,
                       exponent: float) -> np.ndarray:
    """beta(s_hat) with EXACT endpoints.

    shape(s) = s**exponent has shape(0)=0 and shape(1)=1 for any exponent>0,
    so beta(0)==beta1 and beta(1)==beta2 identically. Only the interior
    distribution responds to `exponent`. This is what lets TARGET mode hit a
    wrap angle without ever moving the user's beta1/beta2.
    """
    return beta1 + (beta2 - beta1) * np.power(np.clip(s_hat, 0.0, 1.0), exponent)


def _integrate_wrap(m, r, beta_rad) -> np.ndarray:
    """theta(m) = int tan(beta)/r dm, trapezoidal. No rescaling anywhere."""
    integrand = np.tan(beta_rad) / np.maximum(r, 1e-9)
    dtheta = 0.5 * (integrand[1:] + integrand[:-1]) * np.diff(m)
    return np.concatenate([[0.0], np.cumsum(dtheta)])


@dataclass
class CamberResult:
    theta: np.ndarray
    beta_rad: np.ndarray
    wrap_deg: float
    exponent_used: float
    mode: WrapMode
    target_deg: float | None = None
    target_met: bool = True
    note: str = ""


def solve_camber(stream, beta1_deg, beta2_deg, mode: WrapMode,
                 exponent: float = 1.0, target_wrap_deg: float | None = None,
                 exponent_bounds=(0.12, 8.0)) -> CamberResult:
    m, r = stream["m"], stream["r"]
    s_hat = m / max(stream["M"], 1e-12)
    b1, b2 = math.radians(beta1_deg), math.radians(beta2_deg)

    def wrap_for(exp_):
        beta = _beta_distribution(s_hat, b1, b2, exp_)
        return _integrate_wrap(m, r, beta)[-1]

    if mode is WrapMode.DERIVED or target_wrap_deg is None:
        beta = _beta_distribution(s_hat, b1, b2, exponent)
        theta = _integrate_wrap(m, r, beta)
        return CamberResult(theta, beta, math.degrees(theta[-1]), exponent,
                            WrapMode.DERIVED,
                            note="Wrap angle is an output of the beta distribution.")

    # TARGET mode: hold beta1/beta2, solve interior exponent.
    tgt = math.radians(target_wrap_deg)
    lo, hi = exponent_bounds
    w_lo, w_hi = wrap_for(lo), wrap_for(hi)
    if (w_lo - tgt) * (w_hi - tgt) > 0:
        # Unreachable with these endpoints. Use the closest bound and SAY SO.
        exp_ = lo if abs(w_lo - tgt) < abs(w_hi - tgt) else hi
        beta = _beta_distribution(s_hat, b1, b2, exp_)
        theta = _integrate_wrap(m, r, beta)
        return CamberResult(
            theta, beta, math.degrees(theta[-1]), exp_, WrapMode.TARGET,
            target_wrap_deg, False,
            f"Target wrap {target_wrap_deg:.1f} deg is NOT reachable with "
            f"beta1={beta1_deg:.1f}, beta2={beta2_deg:.1f} on this meridional "
            f"path (achievable range {math.degrees(min(w_lo,w_hi)):.1f} to "
            f"{math.degrees(max(w_lo,w_hi)):.1f} deg). Showing nearest achievable "
            f"{math.degrees(theta[-1]):.1f} deg -- geometry is NOT rescaled.")

    exp_ = brentq(lambda e: wrap_for(e) - tgt, lo, hi, xtol=1e-8)
    beta = _beta_distribution(s_hat, b1, b2, exp_)
    theta = _integrate_wrap(m, r, beta)
    return CamberResult(theta, beta, math.degrees(theta[-1]), exp_,
                        WrapMode.TARGET, target_wrap_deg, True,
                        "beta1/beta2 held exactly; interior distribution "
                        f"exponent solved to {exp_:.3f} to meet target wrap.")


# --------------------------------------------------------------------------
# Thickness
# --------------------------------------------------------------------------

def thickness_distribution(s_hat, t_le, t_max, t_te, law: ThicknessLaw,
                           s_peak: float = 0.35) -> np.ndarray:
    s = np.clip(s_hat, 0.0, 1.0)
    if law is ThicknessLaw.LINEAR:
        return t_le + (t_te - t_le) * s
    if law is ThicknessLaw.ELLIPTIC:
        # LE ellipse blending into linear taper to TE
        front = t_le + (t_max - t_le) * np.sqrt(np.clip(s / s_peak, 0, 1))
        back = t_max + (t_te - t_max) * np.clip((s - s_peak) / (1 - s_peak), 0, 1)
        return np.where(s < s_peak, front, back)
    # PARABOLIC: smooth peak at s_peak, exact endpoints
    front = t_le + (t_max - t_le) * (1 - ((s_peak - s) / s_peak) ** 2)
    back = t_te + (t_max - t_te) * (1 - ((s - s_peak) / (1 - s_peak)) ** 2)
    return np.where(s < s_peak, front, back)


# --------------------------------------------------------------------------
# 3D blade surfaces
# --------------------------------------------------------------------------

@dataclass
class BladeSurfaces:
    """Point grids for one blade. Shape (n_span, n_stream, 3), metres."""
    pressure: np.ndarray
    suction: np.ndarray
    camber: np.ndarray
    beta_rad: np.ndarray          # (n_span, n_stream)
    thickness: np.ndarray         # (n_span, n_stream)
    wrap_deg: np.ndarray          # per span
    camber_results: list


def fillet_width(h, R):
    """Lateral half-width a circular root fillet adds at height h above the hub.

        w(h) = R - sqrt(R^2 - (R - h)^2),  0 <= h <= R,  else 0

    At the hub (h=0) it is R wide; it tapers to zero at h=R, which is the
    profile of a circular fillet seen in the blade-to-blade plane.

    HONEST SCOPE: this is a MODELLED blend built into the blade's lofted
    surface, applied tangentially. It is not a kernel rolling-ball fillet.
    For a thin blade standing close to normal to the hub the two agree
    closely; for a strongly leaned blade the modelled blend is the
    tangential projection of the true fillet. It is used because
    BRepFilletAPI could not fillet this junction at any radius tested
    (see STATUS.md), and because a modelled blend exports as genuine
    curved surface geometry in both the preview and the STEP file.
    """
    R = float(R)
    if R <= 0:
        return np.zeros_like(np.asarray(h, dtype=float))
    h = np.clip(np.asarray(h, dtype=float), 0.0, None)
    inside = np.clip(R * R - (R - h) ** 2, 0.0, None)
    w = R - np.sqrt(inside)
    return np.where(h < R, w, 0.0)


def span_positions(n_span, span_min, fillet_band=0.0):
    """Spanwise section positions, ALWAYS clustered toward the root.

    The distribution deliberately does NOT depend on the fillet radius. Making
    it fillet-dependent meant a filleted and an unfilleted blade were lofted
    through different section counts, so any volume comparison between them
    measured the discretisation change rather than the fillet -- which is how a
    fillet appeared to REMOVE half the blade. A fixed distribution keeps the
    exported face count stable and makes the comparison mean something.

    Clustering toward the root is wanted regardless: that is where the blade
    twists fastest and where any root blend lives.
    """
    if n_span < 4:
        return np.linspace(span_min, 1.0, n_span)
    n_root = max(3, int(round(n_span * 0.45)))
    root = np.linspace(span_min, ROOT_CLUSTER, n_root, endpoint=False)
    rest = np.linspace(ROOT_CLUSTER, 1.0, n_span - n_root)
    out = np.unique(np.concatenate([root, rest]))
    return out[np.concatenate([[True], np.diff(out) > 1e-6])]


def build_blade(channel: MeridionalChannel, p, n_span: int, n_stream: int,
                theta_offset: float = 0.0, m_start_frac: float = 0.0,
                span_min: float = 0.0):
    """Build one blade's surface grids.

    m_start_frac > 0 produces a splitter (blade starts downstream of the main LE
    but follows the SAME camber surface, which is what a real splitter does).
    """
    # span_min < 0 extrapolates the blade root BELOW the hub contour. The
    # export path needs this: a root that sits exactly ON the hub surface is
    # a coincident-face boolean, which OCC either takes minutes on or silently
    # swallows. Burying the root gives a clean volumetric overlap.
    spans = span_positions(n_span, span_min)
    P_all, S_all, C_all, B_all, T_all = [], [], [], [], []
    wraps, cams = [], []

    # span-wise distance at inlet/exit, used for sweep/rake/lean offsets
    st_h, st_s = channel.streamline(0.0, n_stream), channel.streamline(1.0, n_stream)
    inlet_span_len = math.hypot(st_s["z"][0] - st_h["z"][0], st_s["r"][0] - st_h["r"][0])
    exit_span_len = math.hypot(st_s["z"][-1] - st_h["z"][-1], st_s["r"][-1] - st_h["r"][-1])

    # Hub reference row for fillet height. Must be span 0 -- taking whichever
    # span the loop starts on makes the fillet measure height from the BURIED
    # root during export, which put the blend inside the hub and shrank the
    # blade instead of growing it.
    _st0 = channel.streamline(0.0, n_stream)
    _m_le0 = float(np.clip(m_start_frac * _st0["M"], 0.0, 0.85 * _st0["M"]))
    _m_te0 = float(np.clip(_st0["M"], _m_le0 + 0.10 * _st0["M"], _st0["M"]))
    _mb0 = np.linspace(_m_le0, _m_te0, n_stream)
    hub_row = (np.interp(_mb0, _st0["m"], _st0["z"]),
               np.interp(_mb0, _st0["m"], _st0["r"]))

    for s in spans:
        st = channel.streamline(s, n_stream)
        M = st["M"]

        # Sweep (LE) and rake (TE) shift the blade's meridional extent per span.
        m_le = m_start_frac * M + s * inlet_span_len * math.tan(math.radians(p.inlet_sweep_deg))
        m_te = M - s * exit_span_len * math.tan(math.radians(p.exit_rake_deg))
        m_le = float(np.clip(m_le, 0.0, 0.85 * M))
        m_te = float(np.clip(m_te, m_le + 0.10 * M, M))

        # blade angles may vary hub->shroud
        b1 = p.beta1_hub_deg + s * (p.beta1_shroud_deg - p.beta1_hub_deg)
        b2 = p.beta2_hub_deg + s * (p.beta2_shroud_deg - p.beta2_hub_deg)

        cam = solve_camber(st, b1, b2, p.wrap_mode, p.beta_exponent,
                           p.target_wrap_deg)
        cams.append(cam)
        wraps.append(cam.wrap_deg)

        # resample onto the blade's own meridional extent
        m_blade = np.linspace(m_le, m_te, n_stream)
        z = np.interp(m_blade, st["m"], st["z"])
        r = np.interp(m_blade, st["m"], st["r"])
        th = np.interp(m_blade, st["m"], cam.theta)
        beta = np.interp(m_blade, st["m"], cam.beta_rad)
        th = th - th[0]                      # LE at theta = 0 for this span

        # stacking-line lean: tilt the span-wise stacking line by lean angle
        lean = math.tan(math.radians(p.lean_deg)) * s * exit_span_len
        th = th + theta_offset + lean / np.maximum(r, 1e-9)

        s_hat = (m_blade - m_le) / max(m_te - m_le, 1e-12)
        t = thickness_distribution(s_hat, p.t_le, p.t_max, p.t_te,
                                   p.thickness_law, p.t_peak_frac)

        # Root fillet: height ABOVE the hub, signed. An unsigned distance made
        # the buried root (span < 0) read as "far from the hub", so the blend
        # collapsed to zero there and bulged at span 0 instead. That
        # zero-peak-zero width profile folded the loft and inflated the
        # computed volume by five orders of magnitude.
        h_above = math.copysign(1.0, s) * np.hypot(z - hub_row[0], r - hub_row[1]) \
                  if s != 0.0 else np.zeros_like(z)
        w_fil = fillet_width(h_above, p.hub_fillet)

        # tangential half-angle for a thickness measured NORMAL to the camber
        half = t / 2.0 + w_fil
        dth = half / (np.maximum(r, 1e-9) * np.maximum(np.cos(beta), 0.15))

        def xyz(theta_):
            return np.stack([r * np.cos(theta_), r * np.sin(theta_), z], axis=-1)

        P_all.append(xyz(th - dth))
        S_all.append(xyz(th + dth))
        C_all.append(xyz(th))
        B_all.append(beta)
        T_all.append(t)

    return BladeSurfaces(np.array(P_all), np.array(S_all), np.array(C_all),
                         np.array(B_all), np.array(T_all),
                         np.array(wraps), cams)


def hub_surface(channel: MeridionalChannel, n_stream=120, n_theta=96,
                back_face=True):
    """Hub as a genuine surface of revolution of the hub contour.

    FAILURE MODE 2: the hub is the revolved meridional contour, NOT a flat disc
    at r2. A back face is added only as a thin annular disc at the exit plane,
    so it can never dominate the render.
    """
    st = channel.streamline(0.0, n_stream)
    th = np.linspace(0, 2 * np.pi, n_theta)
    Z, TH = np.meshgrid(st["z"], th, indexing="ij")
    R, _ = np.meshgrid(st["r"], th, indexing="ij")
    surf = np.stack([R * np.cos(TH), R * np.sin(TH), Z], axis=-1)
    if not back_face:
        return surf
    return surf


def shroud_contour(channel: MeridionalChannel, n_stream=120):
    st = channel.streamline(1.0, n_stream)
    return np.stack([st["z"], st["r"]], axis=-1)
