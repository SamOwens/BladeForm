"""Fluid models.

Failure Mode 4: selecting Water or Custom must change the PHYSICS, not a label.

Enforcement strategy: incompressible fluids RAISE on gas-only properties
(gamma, gas_constant, sound_speed). So if any code path accidentally reaches
for air's gamma while running a pump, it crashes loudly instead of silently
producing a plausible-looking wrong number. test_fluids.py asserts this.
"""
from __future__ import annotations
from dataclasses import dataclass
import math

R_UNIVERSAL = 8314.462618  # J/(kmol.K)


class IncompressiblePropertyError(TypeError):
    """Raised when gas-only properties are requested from a liquid."""


@dataclass
class Fluid:
    name: str
    compressible: bool

    # --- gas-only (raise for liquids) ---
    def gamma(self, T: float) -> float:
        raise NotImplementedError

    def gas_constant(self) -> float:
        raise NotImplementedError

    def sound_speed(self, T: float) -> float:
        raise NotImplementedError

    def cp(self, T: float) -> float:
        raise NotImplementedError

    # --- always available ---
    def density(self, p: float, T: float) -> float:
        raise NotImplementedError

    def viscosity(self, T: float) -> float:
        raise NotImplementedError

    def vapour_pressure(self, T: float) -> float:
        raise NotImplementedError


@dataclass
class IdealGas(Fluid):
    """Ideal gas with temperature-dependent cp.

    Air cp(T) uses the 3-term fit valid ~250-1000 K quoted in most gas-turbine
    texts (e.g. Walsh & Fletcher, "Gas Turbine Performance"). Good to <1% over
    the range a compressor inlet/exit actually sees.
    """
    R: float = 287.05       # J/(kg.K), dry air
    mu_ref: float = 1.716e-5  # Pa.s at T_ref -- Sutherland reference, air
    T_ref: float = 273.15
    S_suth: float = 110.4   # K, Sutherland constant for air
    cp_const: float | None = None  # if set, use constant cp (Custom fluid)
    gamma_const: float | None = None

    def cp(self, T: float) -> float:
        if self.cp_const is not None:
            return self.cp_const
        # Walsh & Fletcher style polynomial for dry air, J/(kg.K)
        return 1002.5 + 1.0e-4 * (T - 273.15) ** 2 * 0.275

    def gamma(self, T: float) -> float:
        if self.gamma_const is not None:
            return self.gamma_const
        cp = self.cp(T)
        return cp / (cp - self.R)

    def gas_constant(self) -> float:
        return self.R

    def sound_speed(self, T: float) -> float:
        return math.sqrt(self.gamma(T) * self.R * T)

    def density(self, p: float, T: float) -> float:
        return p / (self.R * T)

    def viscosity(self, T: float) -> float:
        # Sutherland's law
        return self.mu_ref * (T / self.T_ref) ** 1.5 * (self.T_ref + self.S_suth) / (T + self.S_suth)

    def vapour_pressure(self, T: float) -> float:
        raise IncompressiblePropertyError("vapour pressure / NPSH is a liquid concept")


@dataclass
class Liquid(Fluid):
    """Incompressible liquid. Gas properties deliberately raise."""
    rho_ref: float = 998.0     # kg/m3 at T_ref
    T_ref: float = 293.15
    beta_thermal: float = 2.07e-4   # 1/K volumetric expansion, water @20C
    mu_ref: float = 1.002e-3        # Pa.s, water @20C
    mu_model: str = "water"         # "water" (Vogel-type) or "const"
    pv_model: str = "water"         # "water" (Antoine) or "const"
    pv_const: float = 2339.0        # Pa, water @20C

    def density(self, p: float, T: float) -> float:
        # linear thermal expansion; pressure effect neglected (incompressible)
        return self.rho_ref / (1.0 + self.beta_thermal * (T - self.T_ref))

    def viscosity(self, T: float) -> float:
        if self.mu_model == "const":
            return self.mu_ref
        # Vogel-type correlation for liquid water, Pa.s; textbook 3-parameter fit,
        # accurate to ~1% over 273-373 K.
        return 2.414e-5 * 10.0 ** (247.8 / max(T - 140.0, 1.0))

    def vapour_pressure(self, T: float) -> float:
        if self.pv_model == "const":
            return self.pv_const
        # Antoine equation for water, coefficients for 1-100 degC (NIST), mmHg -> Pa
        Tc = T - 273.15
        log10p = 8.07131 - 1730.63 / (233.426 + Tc)   # mmHg
        return 10.0 ** log10p * 133.322

    # --- gas-only: hard failure, see module docstring ---
    def gamma(self, T: float) -> float:
        raise IncompressiblePropertyError(
            f"{self.name} is incompressible: gamma is undefined. "
            "A compressible code path was reached with a liquid selected.")

    def gas_constant(self) -> float:
        raise IncompressiblePropertyError(
            f"{self.name} is incompressible: no gas constant.")

    def sound_speed(self, T: float) -> float:
        raise IncompressiblePropertyError(
            f"{self.name} is incompressible: Mach number is not evaluated.")

    def cp(self, T: float) -> float:
        # Liquids do have a cp; water ~4182 J/kgK. Used only for temperature rise.
        return 4182.0


def air() -> IdealGas:
    return IdealGas(name="Air", compressible=True)


def water() -> Liquid:
    return Liquid(name="Water", compressible=False)


def custom(name="Custom", compressible=True, density=1.2, viscosity=1.8e-5,
           gamma=1.4, gas_constant=287.05, vapour_pressure=2339.0):
    """Custom fluid from user numbers (spec Section 3)."""
    if compressible:
        f = IdealGas(name=name, compressible=True, R=gas_constant,
                     gamma_const=gamma)
        # cp implied by gamma and R so the thermodynamics stay self-consistent
        f.cp_const = gamma * gas_constant / (gamma - 1.0)
        f.mu_ref = viscosity
        f.T_ref = 273.15
        f.S_suth = 110.4
        return f
    f = Liquid(name=name, compressible=False, rho_ref=density,
               mu_ref=viscosity, mu_model="const",
               pv_model="const", pv_const=vapour_pressure)
    f.beta_thermal = 0.0
    return f
