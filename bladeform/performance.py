"""1D mean-line performance model.

EMPIRICAL CONSTANTS (Failure Mode 6): every correlation below carries its
source. Where a value is a judgement call rather than a published correlation
it says so in plain words. All of this is first-order -- results are ESTIMATES
and the UI labels them as such.

Loss set follows the arrangement in Oh, Yoon & Chung (1997), "An optimum set of
loss models for performance prediction in centrifugal compressors", Proc IMechE
Part A, which assembles the individual correlations cited per-term below.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import math
import numpy as np
from .fluids import Fluid, IncompressiblePropertyError

G = 9.80665


@dataclass
class OperatingPoint:
    ok: bool = True
    messages: list = field(default_factory=list)

    # velocities / thermo
    c_m1: float = 0.0
    U1s: float = 0.0
    w1s: float = 0.0
    M1_rel: float | None = None
    c_m2: float = 0.0
    c_th2: float = 0.0
    U2: float = 0.0
    w2: float = 0.0
    slip: float = 0.0

    # energy
    euler_work: float = 0.0        # J/kg
    work_actual: float = 0.0       # J/kg (incl. parasitic)
    losses: dict = field(default_factory=dict)
    eta_tt: float = 0.0          # STAGE total-to-total (used for PR/head)
    eta_impeller: float = 0.0    # impeller alone, excl. diffuser/volute
    c2: float = 0.0
    c3: float = 0.0
    power_W: float = 0.0

    # results
    pressure_ratio: float | None = None
    head_m: float | None = None
    dp_Pa: float | None = None
    T02: float | None = None

    # non-dimensional
    flow_coeff: float = 0.0
    work_coeff: float = 0.0
    specific_speed: float = 0.0

    # limits
    npsh_required: float | None = None
    npsh_available: float | None = None
    cavitating: bool = False
    diffusion_ratio: float = 0.0
    surge_risk: bool = False
    choked: bool = False


def _passage_geometry(d, Z_eff, beta2_deg):
    """Blade surface path length and mean passage hydraulic diameter.

    L_b = integral dm / cos(beta) along the mid-span camber -- the distance the
    flow actually travels over the blade, which for a wrapped impeller is much
    longer than the meridional length.

    d_hyd = 4 * Area / Perimeter for the blade-to-blade passage, evaluated at
    inlet and exit and averaged. Passage width is the pitch resolved normal to
    the blade, minus blade thickness.
    """
    from .geometry import MeridionalChannel, solve_camber, WrapMode
    ch = MeridionalChannel(d.r1_hub, d.r1_shroud, d.r2, d.b2,
                           d.axial_length, d.exit_pitch_deg)
    st = ch.streamline(0.5, 120)
    b1 = 0.5 * (d.beta1_hub_deg + d.beta1_shroud_deg)
    cam = solve_camber(st, b1, beta2_deg, d.wrap_mode, d.beta_exponent,
                       d.target_wrap_deg)
    cosb = np.maximum(np.cos(cam.beta_rad), 0.15)
    L_b = float(np.trapezoid(1.0 / cosb, st["m"])) if hasattr(np, "trapezoid")         else float(np.trapz(1.0 / cosb, st["m"]))

    r1_rms = math.sqrt(0.5 * (d.r1_shroud ** 2 + d.r1_hub ** 2))
    Z = max(Z_eff, 1.0)

    def dh(radius, height, beta_deg, thick):
        width = max(2 * math.pi * radius / Z * math.cos(math.radians(beta_deg)) - thick,
                    1e-6)
        height = max(height, 1e-6)
        return 4.0 * (width * height) / (2.0 * (width + height))

    d1 = dh(r1_rms, d.r1_shroud - d.r1_hub, b1, d.t_le)
    d2 = dh(d.r2, d.b2, beta2_deg, d.t_te)
    return L_b, 0.5 * (d1 + d2)


def wiesner_slip(beta2_deg: float, Z: int, radius_ratio: float) -> float:
    """Wiesner (1967) slip factor, with his own low-radius-ratio correction.

    sigma = 1 - sqrt(cos(beta2)) / Z^0.7,  beta2 measured from radial.
    Valid while r1/r2 <= eps_limit = exp(-8.16*cos(beta2)/Z); beyond that
    Wiesner's cubic correction applies.
    """
    b2 = math.radians(abs(beta2_deg))
    cb = max(math.cos(b2), 1e-6)
    sigma = 1.0 - math.sqrt(cb) / max(Z, 1) ** 0.7
    eps_lim = math.exp(-8.16 * cb / max(Z, 1))
    if radius_ratio > eps_lim:
        f = ((radius_ratio - eps_lim) / max(1.0 - eps_lim, 1e-9))
        sigma *= (1.0 - f ** 3)
    return float(np.clip(sigma, 0.05, 1.0))


def _inlet_compressible(fluid, p01, T01, mdot, A1, blockage=0.03):
    """Solve inlet static state by iteration on meridional velocity."""
    cp = fluid.cp(T01); g = fluid.gamma(T01); R = fluid.gas_constant()
    rho0 = p01 / (R * T01)
    cm = mdot / max(rho0 * A1 * (1 - blockage), 1e-9)
    for _ in range(60):
        T1 = T01 - cm * cm / (2 * cp)
        if T1 <= 1.0:
            return None, None, None
        p1 = p01 * (T1 / T01) ** (g / (g - 1))
        rho1 = p1 / (R * T1)
        cm_new = mdot / max(rho1 * A1 * (1 - blockage), 1e-9)
        if abs(cm_new - cm) < 1e-8:
            cm = cm_new; break
        cm = 0.5 * cm + 0.5 * cm_new
    T1 = T01 - cm * cm / (2 * cp)
    if T1 <= 1.0:
        # The in-loop guard does not cover the final evaluation. Without this
        # a negative static temperature reached the power operation and
        # produced a silent NaN instead of an honest "no solution".
        return None, None, None
    p1 = p01 * (T1 / T01) ** (g / (g - 1))
    return cm, T1, p1 / (R * T1)


def evaluate(d, fluid: Fluid, mdot: float | None = None,
             rpm: float | None = None, blockage_exit: float = 0.08) -> OperatingPoint:
    """Evaluate one operating point. Works for compressible AND incompressible.

    The two branches are genuinely separate: the incompressible path never
    touches gamma / R / sound speed (the Liquid class raises if it tries).
    """
    op = OperatingPoint()
    mdot = d.mdot if mdot is None else mdot
    rpm = d.rpm if rpm is None else rpm
    omega = rpm * 2 * math.pi / 60.0

    r1s, r1h, r2, b2 = d.r1_shroud, d.r1_hub, d.r2, d.b2
    A1 = math.pi * (r1s ** 2 - r1h ** 2)
    A2 = 2 * math.pi * r2 * b2
    r1_rms = math.sqrt(0.5 * (r1s ** 2 + r1h ** 2))
    Z_main = max(d.n_main, 1)
    # Splitters only act over the fraction of the passage they occupy; treating
    # them as full blades over-predicts slip. Weighting by covered meridional
    # length is a standard first-order treatment (see e.g. Japikse, "Centrifugal
    # Compressor Design and Performance"), not an exact result.
    Z_eff = Z_main + d.n_splitter * (1.0 - d.splitter_start_frac)

    op.U2 = omega * r2
    op.U1s = omega * r1s

    # ---------------- inlet ----------------
    if fluid.compressible:
        cm1, T1, rho1 = _inlet_compressible(fluid, d.p01, d.T01, mdot, A1)
        if cm1 is None:
            op.ok = False; op.messages.append("Inlet choked / no static solution."); return op
        op.c_m1 = cm1
        op.w1s = math.hypot(cm1, op.U1s)
        op.M1_rel = op.w1s / fluid.sound_speed(T1)
        rho_in = rho1
    else:
        rho_in = fluid.density(d.p01, d.T01)
        op.c_m1 = mdot / max(rho_in * A1, 1e-9)
        op.w1s = math.hypot(op.c_m1, op.U1s)
        op.M1_rel = None            # not evaluated for a liquid -- by design

    # ---------------- exit / Euler + slip ----------------
    beta2 = d.beta2_hub_deg
    op.slip = wiesner_slip(beta2, int(round(Z_eff)), r1_rms / r2)

    rho2 = rho_in
    converged = True
    for it in range(80):
        op.c_m2 = mdot / max(rho2 * A2 * (1 - blockage_exit), 1e-9)
        op.c_th2 = op.slip * op.U2 - op.c_m2 * math.tan(math.radians(beta2))
        op.euler_work = op.U2 * op.c_th2
        if not fluid.compressible:
            break
        cp = fluid.cp(d.T01); g = fluid.gamma(d.T01); R = fluid.gas_constant()
        T02 = d.T01 + op.euler_work / cp
        c2 = math.hypot(op.c_m2, op.c_th2)
        T2 = T02 - c2 * c2 / (2 * cp)
        if T2 <= 1.0 or T02 <= 1.0:
            converged = False; break
        p2 = d.p01 * max(T2 / d.T01, 1e-6) ** (g / (g - 1))
        rho2_new = p2 / (R * T2)
        # Bound the update: an unbounded fixed point here ran away to rho2 -> 0
        # and produced c_m2 of order 1e8 m/s before this clamp existed.
        rho2_new = float(np.clip(rho2_new, 0.05 * rho_in, 20.0 * rho_in))
        if abs(rho2_new - rho2) < 1e-9 * max(rho_in, 1e-9):
            rho2 = rho2_new; break
        rho2 = 0.6 * rho2 + 0.4 * rho2_new
    else:
        converged = False
    if not converged:
        op.ok = False
        op.messages.append("Exit state did not converge -- geometry and duty are "
                           "mutually inconsistent (check exit area vs mass flow).")
    if op.euler_work <= 0:
        op.ok = False
        op.messages.append(f"Euler work is non-positive ({op.euler_work:.0f} J/kg): "
                           "backsweep and meridional velocity cancel the blade "
                           "speed. Increase exit area, reduce backsweep, or raise RPM.")

    op.w2 = math.hypot(op.c_m2, op.slip * op.U2 - op.c_th2 + op.c_m2 * 0.0)
    op.w2 = math.hypot(op.c_m2, op.U2 - op.c_th2)

    # ---------------- losses ----------------
    L = {}
    # Incidence: half the tangential kinetic energy destroyed at the LE.
    # Conrad et al. (1980) "shock-free" incidence model, f_inc typically 0.5-0.7.
    F_INC = 0.6
    beta1_flow = math.degrees(math.atan2(op.U1s, max(op.c_m1, 1e-9)))
    w_th1 = op.c_m1 * abs(math.tan(math.radians(beta1_flow))
                          - math.tan(math.radians(d.beta1_shroud_deg)))
    L["incidence"] = F_INC * w_th1 ** 2 / 2.0

    # Blade loading (diffusion). Coppage et al. (1956), coefficient 0.05.
    denom = (Z_eff / math.pi) * (1 - r1s / r2) + 2 * r1s / r2
    Df = 1 - op.w2 / max(op.w1s, 1e-9) + 0.75 * op.euler_work / max(op.U2 ** 2, 1e-9) \
        * (op.w1s / max(op.w2, 1e-9)) / max(denom, 1e-9)
    Df = float(np.clip(Df, 0.0, 0.95))
    L["blade_loading"] = 0.05 * Df ** 2 * op.U2 ** 2

    # Skin friction. Jansen (1967). cf from a smooth-pipe turbulent estimate.
    mu = fluid.viscosity(d.T01)
    # Blade path length and passage hydraulic diameter, both from the actual
    # geometry rather than the rough stand-ins used before (1.2 x meridional
    # length, and a hydraulic diameter taken from the exit alone). Those
    # under-read the friction term; these are first-principles, so the
    # published Jansen correlation is left untouched.
    L_b, d_hyd = _passage_geometry(d, Z_eff, beta2)
    w_avg = 0.5 * (op.w1s + op.w2)
    Re = rho_in * w_avg * max(d_hyd, 1e-6) / max(mu, 1e-12)
    cf = 0.0412 * max(Re, 1e3) ** -0.1925   # Jansen's fit to smooth-wall data
    L["skin_friction"] = 2.0 * cf * (L_b / max(d_hyd, 1e-9)) * w_avg ** 2

    # Tip clearance. Jansen (1967), coefficient 0.6. Clearance taken as 2% of b2
    # when not otherwise specified -- that is a typical shrouded/open value, not
    # a measured number for any particular machine.
    eps_cl = 0.02 * b2
    _inner = (4 * math.pi / max(b2 * Z_eff, 1e-9)) * \
             ((r1s ** 2 - r1h ** 2) / max((r2 - r1s) * (1 + rho2 / max(rho_in, 1e-9)), 1e-9)) * \
             abs(op.c_th2) * abs(op.c_m1)
    L["clearance"] = 0.6 * (eps_cl / max(b2, 1e-9)) * abs(op.c_th2) * math.sqrt(max(_inner, 0.0))

    # --- parasitic (add to input work, not subtracted from useful work) ---
    # Disk friction, Daily & Nece (1960) turbulent-flow regime constant.
    rho_avg = 0.5 * (rho_in + rho2)
    Re_df = max(op.U2 * r2 * rho_avg / max(mu, 1e-12), 1e3)
    f_df = 0.0402 / Re_df ** 0.2
    L["disk_friction"] = f_df * rho_avg * op.U2 ** 3 * r2 ** 2 / (4 * max(mdot, 1e-9))

    # Recirculation. Oh et al. (1997) form; sinh makes it blow up at high exit
    # flow angle, which is the intended behaviour near surge.
    alpha2 = math.atan2(abs(op.c_th2), max(op.c_m2, 1e-9))
    # Oh et al. fit the sinh form for compressor exit flow angles up to ~75 deg.
    # Past that it grows without bound (it exceeded the Euler work entirely for a
    # low-flow-coefficient pump), so alpha2 is capped at 75 deg and the term is
    # additionally limited to 25% of Euler work. Both limits are engineering
    # judgement to keep the model bounded, NOT part of the published correlation.
    alpha2_c = min(alpha2, math.radians(75.0))
    _rc = 8e-5 * math.sinh(3.5 * alpha2_c ** 3) * Df ** 2 * op.U2 ** 2
    L["recirculation"] = min(_rc, 0.25 * max(op.euler_work, 0.0))

    # --- exit kinetic energy: mixing + downstream recovery ---
    # The impeller leaves ~30-40% of its work as exit kinetic energy. How much
    # of that is recovered dominates STAGE efficiency; omitting it gave a
    # physically impossible eta ~ 0.95.
    op.c2 = math.hypot(op.c_m2, op.c_th2)

    # Wake mixing at the impeller exit. Johnston & Dean (1966). Wake fraction
    # 0.20 and blockage 0.10 are mid-range values for a well-designed wheel;
    # both are typical figures, not measurements of any specific machine.
    EPS_WAKE, B_BLOCK = 0.20, 0.10
    tan_a2 = abs(op.c_th2) / max(op.c_m2, 1e-9)
    L["mixing"] = (1.0 / (1.0 + tan_a2 ** 2)) * \
                  ((1 - EPS_WAKE - B_BLOCK) / (1 - EPS_WAKE)) ** 2 * op.c2 ** 2 / 2.0

    # Diffuser / volute. Modelled as imperfect recovery of the dynamic head:
    #   loss = (1 - eta_diff) * (c2^2 - c3^2)/2
    # eta_diff 0.60 vaneless / 0.78 vaned are typical ranges (Japikse); the
    # velocity ratios below are design intent, not computed diffuser geometry.
    if d.diffuser_on:
        eta_diff, c3_ratio = 0.78, 0.30       # vaned diffuser
    else:
        eta_diff, c3_ratio = 0.60, 0.50       # vaneless space only
    if d.volute_on:
        eta_diff -= 0.05                      # extra volute mixing, rough allowance
    op.c3 = c3_ratio * op.c2
    L["diffuser"] = (1.0 - eta_diff) * (op.c2 ** 2 - op.c3 ** 2) / 2.0

    impeller_int = L["incidence"] + L["blade_loading"] + L["skin_friction"] + L["clearance"]
    stage_int = impeller_int + L["mixing"] + L["diffuser"]
    parasitic = L["disk_friction"] + L["recirculation"]
    op.losses = L

    op.work_actual = op.euler_work + parasitic
    op.eta_impeller = float(np.clip(max(op.euler_work - impeller_int, 1e-6)
                                    / max(op.work_actual, 1e-9), 0.02, 0.99))
    useful = max(op.euler_work - stage_int, 1e-6)
    op.eta_tt = float(np.clip(useful / max(op.work_actual, 1e-9), 0.02, 0.98))
    op.power_W = mdot * op.work_actual

    # ---------------- outputs: two genuinely different branches ----------------
    if fluid.compressible:
        cp = fluid.cp(d.T01); g = fluid.gamma(d.T01)
        op.T02 = d.T01 + op.work_actual / cp
        op.pressure_ratio = (1 + op.eta_tt * op.work_actual / (cp * d.T01)) ** (g / (g - 1))
        op.dp_Pa = d.p01 * (op.pressure_ratio - 1)
        op.head_m = None
    else:
        rho = fluid.density(d.p01, d.T01)
        op.head_m = useful / G
        op.dp_Pa = rho * G * op.head_m
        op.pressure_ratio = None
        op.T02 = d.T01 + op.work_actual * (1 - op.eta_tt) / fluid.cp(d.T01)
        # NPSH. Gulich, "Centrifugal Pumps": NPSHr = l_c*cm1^2/2g + l_w*w1s^2/2g
        # with l_c ~ 1.1 and l_w ~ 0.25 for a conventional (non-inducer) impeller.
        LAM_C, LAM_W = 1.1, 0.25
        op.npsh_required = (LAM_C * op.c_m1 ** 2 + LAM_W * op.w1s ** 2) / (2 * G)
        pv = fluid.vapour_pressure(d.T01)
        op.npsh_available = (d.p01 - pv) / (rho * G)
        op.cavitating = op.npsh_available < 1.1 * op.npsh_required
        if op.cavitating:
            op.messages.append(
                f"Cavitation risk: NPSHa {op.npsh_available:.1f} m < 1.1 x NPSHr "
                f"{op.npsh_required:.1f} m (estimate).")

    # ---------------- non-dimensional + limits ----------------
    vol = mdot / max(rho_in, 1e-9)
    op.flow_coeff = vol / max(op.U2 * r2 ** 2, 1e-9)
    op.work_coeff = op.euler_work / max(op.U2 ** 2, 1e-9)
    head_for_ns = (op.head_m * G) if op.head_m is not None else op.euler_work
    op.specific_speed = omega * math.sqrt(max(vol, 1e-12)) / max(head_for_ns, 1e-9) ** 0.75

    # de Haller-type diffusion limit. w2/w1 < ~0.55 (i.e. w1/w2 > 1.8) is the
    # classical stall threshold; treat as a ROUGH surge indicator only.
    op.diffusion_ratio = op.w1s / max(op.w2, 1e-9)
    op.surge_risk = op.diffusion_ratio > 1.8
    if op.M1_rel is not None and op.M1_rel > 1.0:
        op.messages.append(f"Inducer tip relative Mach {op.M1_rel:.2f} -- supersonic.")
    return op


def choke_mass_flow(d, fluid, rpm=None, iters=25) -> float | None:
    """Mass flow at which the inducer throat reaches relative Mach 1.

    Solved in the ROTATING frame. With zero inlet swirl the relative stagnation
    temperature is T0rel = T01 + U^2/(2*cp) -- it is NOT equal to T01. Treating
    it as T01 made choke flow independent of shaft speed, which drew a vertical
    choke line on the map and pushed the design point outside it.

    Throat area is pitch*cos(beta1) minus blade thickness -- a geometric
    estimate, not a CFD result.
    """
    if not fluid.compressible:
        return None
    rpm = d.rpm if rpm is None else rpm
    omega = rpm * 2 * math.pi / 60.0
    r1s, r1h = d.r1_shroud, d.r1_hub
    r_rms = math.sqrt(0.5 * (r1s ** 2 + r1h ** 2))
    beta = math.radians(d.beta1_shroud_deg)
    pitch = 2 * math.pi * r_rms / max(d.n_main, 1)
    throat = max(pitch * math.cos(beta) - d.t_le, 1e-6)
    A_th = throat * (r1s - r1h) * max(d.n_main, 1)
    A1 = math.pi * (r1s ** 2 - r1h ** 2)

    g = fluid.gamma(d.T01); R = fluid.gas_constant(); cp = fluid.cp(d.T01)
    U = omega * r_rms
    K = math.sqrt(g / R) * (2.0 / (g + 1.0)) ** ((g + 1.0) / (2.0 * (g - 1.0)))

    # The relative stagnation state depends on the inlet static state, which
    # depends on the mass flow we are solving for -> fixed-point iterate.
    mdot = d.mdot
    for _ in range(iters):
        cm1, T1, rho1 = _inlet_compressible(fluid, d.p01, d.T01, mdot, A1)
        if cm1 is None:
            mdot *= 0.8
            continue
        p1 = rho1 * R * T1
        w1sq = cm1 * cm1 + U * U
        T0rel = T1 + w1sq / (2 * cp)
        p0rel = p1 * (T0rel / T1) ** (g / (g - 1))
        new = A_th * p0rel / math.sqrt(T0rel) * K
        if abs(new - mdot) < 1e-9:
            return new
        mdot = 0.5 * mdot + 0.5 * new
    return mdot


def optimal_beta1(d, fluid, mdot=None, rpm=None):
    """Incidence-free inlet blade angles at hub and shroud, degrees.

    beta1_opt = atan(U1 / c_m1). Offered as a DERIVED READ-ONLY hint so the user
    can see how far their chosen beta1 sits from zero-incidence; it never
    overwrites what they typed.
    """
    mdot = d.mdot if mdot is None else mdot
    rpm = d.rpm if rpm is None else rpm
    omega = rpm * 2 * math.pi / 60.0
    A1 = math.pi * (d.r1_shroud ** 2 - d.r1_hub ** 2)
    if fluid.compressible:
        cm1, _, _ = _inlet_compressible(fluid, d.p01, d.T01, mdot, A1)
        if cm1 is None:
            return None, None
    else:
        cm1 = mdot / max(fluid.density(d.p01, d.T01) * A1, 1e-9)
    return (math.degrees(math.atan2(omega * d.r1_hub, cm1)),
            math.degrees(math.atan2(omega * d.r1_shroud, cm1)))


# ---------------------------------------------------------------------------
# Duty-based sizing (used to generate self-consistent presets)
# ---------------------------------------------------------------------------

def size_from_duty(fluid, mdot, rpm, pressure_ratio=None, head_m=None,
                   p01=101325.0, T01=288.15, psi=0.62, eta_guess=0.78,
                   phi2=0.28, beta2=35.0, htr=0.40, beta1s_target=60.0,
                   exit_pitch_deg=0.0, u2_scale=1.0):
    """Size an impeller from duty using standard preliminary-design rules.

    psi (work coefficient) 0.55-0.70 and phi2 (c_m2/U2) 0.22-0.32 are the
    conventional bands quoted in Dixon & Hall and Japikse; beta1s_target near
    60 deg is the classical inducer optimum that minimises inducer-tip relative
    velocity. These are DESIGN CHOICES, not physical laws. Lowering
    beta1s_target opens the inducer throat and buys choke margin.
    """
    from scipy.optimize import brentq
    omega = rpm * 2 * math.pi / 60.0
    if fluid.compressible:
        cp = fluid.cp(T01); g = fluid.gamma(T01)
        dh0s = cp * T01 * (pressure_ratio ** ((g - 1) / g) - 1)
        dh0 = dh0s / eta_guess
    else:
        dh0 = G * head_m / eta_guess
    rho1 = fluid.density(p01, T01)
    U2 = math.sqrt(dh0 / psi) * u2_scale
    r2 = U2 / omega

    def beta1s_err(r1s):
        r1h = htr * r1s
        A1 = math.pi * (r1s ** 2 - r1h ** 2)
        if fluid.compressible:
            cm1, _, _ = _inlet_compressible(fluid, p01, T01, mdot, A1)
            if cm1 is None:
                return 1e6
        else:
            cm1 = mdot / max(rho1 * A1, 1e-9)
        return math.degrees(math.atan2(omega * r1s, cm1)) - beta1s_target

    # Scan for a valid bracket first: at very small r1s the inlet has no static
    # solution and beta1s_err returns a large positive sentinel, so a fixed
    # bracket can be same-signed at both ends.
    grid = np.linspace(0.08 * r2, 0.95 * r2, 80)
    vals = [beta1s_err(x) for x in grid]
    lo = hi = None
    for i in range(len(grid) - 1):
        if vals[i] < 1e5 and vals[i + 1] < 1e5 and vals[i] * vals[i + 1] < 0:
            lo, hi = grid[i], grid[i + 1]; break
    if lo is None:
        raise ValueError(
            f"Cannot size an inducer for mdot={mdot} kg/s at {rpm} rpm with "
            f"hub-tip ratio {htr}: no inlet radius gives beta1s={beta1s_target} deg.")
    r1s = brentq(beta1s_err, lo, hi, xtol=1e-12)
    r1h = htr * r1s
    A1 = math.pi * (r1s ** 2 - r1h ** 2)
    if fluid.compressible:
        cm1, _, _ = _inlet_compressible(fluid, p01, T01, mdot, A1)
        rho2 = rho1 * pressure_ratio ** (1 / fluid.gamma(T01))
    else:
        cm1 = mdot / max(rho1 * A1, 1e-9)
        rho2 = rho1
    cm2 = phi2 * U2
    A2 = mdot / max(rho2 * cm2 * (1 - 0.08), 1e-9)
    b2 = A2 / (2 * math.pi * r2)
    # Axial length: L/r2 ~ 0.35-0.55 is typical for a centrifugal stage.
    L = 0.55 * r2
    return dict(r1_hub=r1h, r1_shroud=r1s, r2=r2, b2=b2, axial_length=L,
                beta1_hub_deg=math.degrees(math.atan2(omega * r1h, cm1)),
                beta1_shroud_deg=math.degrees(math.atan2(omega * r1s, cm1)),
                beta2_hub_deg=beta2, beta2_shroud_deg=beta2,
                exit_pitch_deg=exit_pitch_deg, U2=U2, c_m1=cm1, c_m2=cm2)


def size_converged(fluid, template: dict, target_pressure_ratio=None,
                   target_head_m=None, tol=2e-3, max_outer=30, **duty):
    """Size from duty, then iterate until the machine actually MEETS the target.

    A single sizing pass assumes an efficiency (0.78 by default) to convert the
    required pressure rise into blade speed. The loss model then predicts a
    different efficiency, so the sized machine misses its own target by roughly
    that error -- presets built this way were landing about 10% off.

    Two nested corrections fix it:
      inner -- re-size using the efficiency the loss model actually predicts,
               until that efficiency stops moving;
      outer -- scale blade speed until the achieved pressure ratio (or head)
               matches the target.

    Returns (Design, OperatingPoint). Raises if it cannot converge, rather than
    returning a machine that quietly misses its duty.
    """
    from .params import Design
    GEOM = ("r1_hub", "r1_shroud", "r2", "b2", "axial_length", "exit_pitch_deg",
            "beta1_hub_deg", "beta1_shroud_deg", "beta2_hub_deg", "beta2_shroud_deg")
    compressible = fluid.compressible
    target = target_pressure_ratio if compressible else target_head_m
    if target is None:
        raise ValueError("size_converged needs a target pressure ratio or head")

    scale, best = 1.0, None
    for _ in range(max_outer):
        eta = duty.get("eta_guess", 0.78)
        d = op = None
        for _ in range(25):
            kw = dict(duty); kw.pop("eta_guess", None)
            if compressible:
                kw["pressure_ratio"] = target_pressure_ratio
            else:
                kw["head_m"] = target_head_m
            geom = size_from_duty(fluid, eta_guess=eta, u2_scale=scale, **kw)
            d = Design(**{**template, **{k: geom[k] for k in GEOM}})
            op = evaluate(d, fluid)
            if not op.ok:
                break
            eta_new = op.eta_tt
            if abs(eta_new - eta) < 1e-5:
                eta = eta_new
                break
            eta = 0.6 * eta + 0.4 * eta_new
        if op is None or not op.ok:
            scale *= 1.05
            continue
        achieved = op.pressure_ratio if compressible else op.head_m
        best = (d, op)
        base = 1.0 if compressible else 0.0
        err = (achieved - base) / max(target - base, 1e-9) - 1.0
        if abs(err) < tol:
            return d, op
        scale *= (1.0 - 0.45 * max(min(err, 0.5), -0.5))
    if best is None:
        raise RuntimeError("duty sizing did not converge to a working machine")
    raise RuntimeError(
        f"duty sizing reached {('PR' if compressible else 'head')} "
        f"{(best[1].pressure_ratio if compressible else best[1].head_m):.4f} "
        f"against a target of {target:.4f} and stopped improving")
