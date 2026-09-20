"""Parameter set, presets and validation."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict, replace
import math
from .geometry import WrapMode, ThicknessLaw


@dataclass
class Design:
    name: str = "Untitled"
    archetype: str = "baseline_compressor"

    # --- operating conditions (SI) ---
    rpm: float = 22000.0
    p01: float = 101325.0          # Pa
    T01: float = 288.15            # K
    mdot: float = 0.85             # kg/s  (mass flow; pumps use volumetric->mass)
    fluid_kind: str = "air"        # air | water | custom
    custom_fluid: dict = field(default_factory=dict)

    # --- meridional geometry (m) ---
    r1_hub: float = 0.0130
    r1_shroud: float = 0.0330
    r2: float = 0.0600
    b2: float = 0.0055
    axial_length: float = 0.0330
    exit_pitch_deg: float = 0.0
    hub_fillet: float = 0.0012

    # --- blade definition ---
    n_main: int = 7
    n_splitter: int = 7
    splitter_start_frac: float = 0.35
    beta1_hub_deg: float = 38.0
    beta1_shroud_deg: float = 60.0
    beta2_hub_deg: float = 35.0
    beta2_shroud_deg: float = 35.0
    wrap_mode: WrapMode = WrapMode.DERIVED
    target_wrap_deg: float = 110.0
    beta_exponent: float = 1.0
    inlet_sweep_deg: float = 0.0
    exit_rake_deg: float = 0.0
    lean_deg: float = 0.0
    t_le: float = 0.0006
    t_max: float = 0.0012
    t_te: float = 0.0008
    t_peak_frac: float = 0.35
    thickness_law: ThicknessLaw = ThicknessLaw.PARABOLIC

    # --- downstream elements ---
    diffuser_on: bool = False
    diffuser_ratio: float = 1.55
    diffuser_vanes: int = 17
    volute_on: bool = False
    volute_exit_d: float = 0.075
    volute_area_exponent: float = 1.0   # A(theta) = A_exit * (theta/2pi)^n
    diffuser_turn_deg: float = 12.0     # how much the vanes turn the flow

    # --- targets ---
    target_pressure_ratio: float = 2.8
    target_head_m: float = 40.0

    @property
    def omega(self) -> float:
        return self.rpm * 2.0 * math.pi / 60.0

    @property
    def U2(self) -> float:
        return self.omega * self.r2

    @property
    def hub_tip_ratio(self) -> float:
        return self.r1_hub / max(self.r1_shroud, 1e-9)

    def to_dict(self):
        d = asdict(self)
        d["wrap_mode"] = self.wrap_mode.value
        d["thickness_law"] = self.thickness_law.value
        return d

    @staticmethod
    def from_dict(d):
        d = dict(d)
        d["wrap_mode"] = WrapMode(d.get("wrap_mode", "derived"))
        d["thickness_law"] = ThicknessLaw(d.get("thickness_law", "parabolic"))
        return Design(**d)


PRESETS = {
    "baseline_compressor": dict(name='Baseline Compressor', archetype='baseline_compressor', rpm=22000, p01=101325.0, T01=288.15, mdot=2.5, fluid_kind='air', r1_hub=0.020829, r1_shroud=0.074389, r2=0.163674, b2=0.011638, axial_length=0.090021, exit_pitch_deg=0.0, hub_fillet=0.001964, n_main=9, n_splitter=9, splitter_start_frac=0.38, beta1_hub_deg=18.453391, beta1_shroud_deg=50.0, beta2_hub_deg=32, beta2_shroud_deg=32, t_le=0.001309, t_max=0.002455, t_te=0.001637, diffuser_ratio=1.55, diffuser_vanes=17, volute_exit_d=0.098204, volute_area_exponent=1.0, diffuser_turn_deg=12.0, target_pressure_ratio=2.2, target_head_m=40.0),
    "turbocharger": dict(name='Turbocharger Compressor', archetype='turbocharger', rpm=115000, p01=101325.0, T01=288.15, mdot=0.12, fluid_kind='air', r1_hub=0.004391, r1_shroud=0.015681, r2=0.033937, b2=0.002486, axial_length=0.018665, exit_pitch_deg=0.0, hub_fillet=0.000407, n_main=6, n_splitter=6, splitter_start_frac=0.35, beta1_hub_deg=18.453391, beta1_shroud_deg=50.0, beta2_hub_deg=40, beta2_shroud_deg=40, t_le=0.000271, t_max=0.000509, t_te=0.000339, diffuser_ratio=1.55, diffuser_vanes=17, volute_exit_d=0.020362, volute_area_exponent=1.0, diffuser_turn_deg=12.0, target_pressure_ratio=2.2, target_head_m=40.0),
    "pump": dict(name='Centrifugal Pump', archetype='pump', rpm=2950, p01=200000.0, T01=293.15, mdot=25.0, fluid_kind='water', r1_hub=0.015046, r1_shroud=0.037615, r2=0.106242, b2=0.006904, axial_length=0.058433, exit_pitch_deg=0.0, hub_fillet=0.001381, n_main=6, n_splitter=0, splitter_start_frac=0.35, beta1_hub_deg=34.715004, beta1_shroud_deg=60.0, beta2_hub_deg=25, beta2_shroud_deg=25, t_le=0.002125, t_max=0.0034, t_te=0.00255, diffuser_ratio=1.55, diffuser_vanes=17, volute_exit_d=0.063745, volute_area_exponent=1.0, diffuser_turn_deg=12.0, target_pressure_ratio=1.0, target_head_m=60.0),
    "mixed_flow_fan": dict(name='Mixed-Flow Fan', archetype='mixed_flow_fan', rpm=5200, p01=101325.0, T01=288.15, mdot=1.1, fluid_kind='air', r1_hub=0.053946, r1_shroud=0.107891, r2=0.137604, b2=0.043537, axial_length=0.075682, exit_pitch_deg=42, hub_fillet=0.001651, n_main=11, n_splitter=0, splitter_start_frac=0.35, beta1_hub_deg=40.893395, beta1_shroud_deg=60.0, beta2_hub_deg=45, beta2_shroud_deg=45, t_le=0.001101, t_max=0.002064, t_te=0.001376, diffuser_ratio=1.55, diffuser_vanes=17, volute_exit_d=0.082562, volute_area_exponent=1.0, diffuser_turn_deg=12.0, target_pressure_ratio=1.025, target_head_m=40.0),
}


def make_preset(key: str) -> Design:
    return Design(**PRESETS[key])


# --------------------------------------------------------------------------
# Validation -- non-blocking, visually flagged (spec Section 9)
# --------------------------------------------------------------------------

@dataclass
class Issue:
    level: str      # "warn" | "error"
    field: str
    message: str


def validate(d: Design, channel=None) -> list[Issue]:
    out: list[Issue] = []

    def warn(f, m): out.append(Issue("warn", f, m))
    def err(f, m): out.append(Issue("error", f, m))

    if d.r1_shroud <= d.r1_hub:
        err("r1_shroud", "Inlet shroud radius must exceed hub radius "
                         "(annulus height would be zero or negative).")
    else:
        htr = d.hub_tip_ratio
        if not (0.15 <= htr <= 0.75):
            warn("r1_hub", f"Hub-tip ratio {htr:.2f} is outside the usual "
                           "0.25-0.65 band for this class of machine.")
    if d.r2 <= d.r1_shroud:
        err("r2", "Exit radius must exceed inlet shroud radius.")
    if d.b2 <= 0:
        err("b2", "Exit blade height must be positive.")
    elif d.b2 / max(d.r2, 1e-9) > 0.35:
        warn("b2", "Exit height/radius > 0.35 is unusually wide.")
    if d.axial_length <= 0:
        err("axial_length", "Axial length must be positive.")

    # FAILURE MODE 10: blade blockage / self-intersection at the inducer.
    # Tangential thickness must not consume the blade pitch.
    z_eff = d.n_main + d.n_splitter
    if z_eff > 0 and d.r1_shroud > 0:
        pitch = 2 * math.pi * d.r1_hub / max(d.n_main, 1)
        beta_in = math.radians(max(d.beta1_hub_deg, 0.0))
        # The root fillet adds 2*r_fillet of lateral width at the hub, so it
        # consumes pitch exactly like thickness does and belongs in this check.
        t_tan = (d.t_le + 2.0 * d.hub_fillet) / max(math.cos(beta_in), 0.15)
        block = t_tan / max(pitch, 1e-9)
        if block >= 1.0:
            err("n_main", f"Blades self-intersect at the hub leading edge: "
                          f"tangential thickness plus root fillet is {block:.2f}x "
                          "the blade pitch. Reduce blade count, LE thickness, "
                          "fillet radius, or beta1.")
        elif block > 0.45:
            warn("n_main", f"Inducer blockage {block*100:.0f}% of pitch -- "
                           "geometry is valid but heavily blocked.")
    if d.n_splitter and d.n_main and d.n_splitter % d.n_main:
        warn("n_splitter", "Splitter count is not a multiple of main blade "
                           "count; splitters will be unevenly spaced.")
    if not (0.05 <= d.splitter_start_frac <= 0.9) and d.n_splitter:
        warn("splitter_start_frac", "Splitter start should be 5-90% of the "
                                    "meridional length.")
    if d.t_max < max(d.t_le, d.t_te):
        warn("t_max", "Max thickness is below LE/TE thickness; the "
                      "distribution will be non-physical.")
    if abs(d.beta2_hub_deg) > 65:
        warn("beta2_hub_deg", "Backsweep beyond ~60 deg is outside normal "
                              "design practice.")
    if d.hub_fillet > 0.5 * d.b2:
        warn("hub_fillet", "Fillet radius exceeds half the exit blade height; "
                           "the fillet operation may fail at export.")
    # Choke margin. The mass-flux function is flat near M=1, so a transonic
    # inducer has very little flow left before it chokes -- at M1_rel = 0.7 only
    # about 9% more. That is real for a high-speed wheel, so this warns rather
    # than errors, but silence would hide a design sitting on its choke line.
    if d.fluid_kind == "air" or (d.fluid_kind == "custom"
                                 and d.custom_fluid.get("compressible", True)):
        try:
            from .performance import choke_mass_flow
            from .exporters import fluid_for
            mc = choke_mass_flow(d, fluid_for(d))
            if mc:
                margin = mc / max(d.mdot, 1e-9)
                if margin <= 1.0:
                    err("mdot", f"Design flow is past the estimated choke limit "
                                f"({mc:.4g} kg/s) -- the wheel cannot pass it.")
                elif margin < 1.06:
                    warn("mdot", f"Only {(margin-1)*100:.0f}% choke margin "
                                 f"(choke at {mc:.4g} kg/s). Normal for a "
                                 "transonic inducer, but there is no room to "
                                 "increase flow.")
        except Exception:
            pass

    if d.fluid_kind == "water" and d.target_pressure_ratio > 1.0001:
        warn("target_pressure_ratio", "Liquid selected -- use target head "
                                      "instead of pressure ratio.")
    return out
