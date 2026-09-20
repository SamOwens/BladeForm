"""Unit system handling.

Failure Mode 9: a unit toggle must CONVERT values, not relabel them.
Every quantity carries a dimension tag; display/export go through convert().
Internal storage is ALWAYS SI. Nothing downstream ever sees Imperial.
"""
from __future__ import annotations
from dataclasses import dataclass

SI, IMPERIAL = "SI", "Imperial"

# factor: value_display = value_SI * factor + offset
_TABLE = {
    # dimension:        (SI unit, Imp unit, factor,        offset)
    "length_mm":        ("mm",    "in",     1.0 / 25.4,    0.0),
    "length_m":         ("m",     "ft",     3.280839895,   0.0),
    "pressure":         ("kPa",   "psi",    0.1450377377,  0.0),
    "pressure_pa":      ("Pa",    "psi",    1.450377e-4,   0.0),
    "temperature":      ("K",     "degF",   1.8,           -459.67),
    "massflow":         ("kg/s",  "lbm/s",  2.204622622,   0.0),
    "volflow":          ("m3/s",  "gpm",    15850.32314,   0.0),
    "power":            ("kW",    "hp",     1.34102209,    0.0),
    "speed":            ("m/s",   "ft/s",   3.280839895,   0.0),
    "density":          ("kg/m3", "lbm/ft3",0.06242796,    0.0),
    "head":             ("m",     "ft",     3.280839895,   0.0),
    "rpm":              ("rpm",   "rpm",    1.0,           0.0),
    "angle":            ("deg",   "deg",    1.0,           0.0),
    "ratio":            ("-",     "-",      1.0,           0.0),
    "viscosity":        ("Pa.s",  "lbm/ft/s", 0.671968975, 0.0),
}


def unit_label(dim: str, system: str) -> str:
    si, imp, _, _ = _TABLE[dim]
    return si if system == SI else imp


def to_display(value: float, dim: str, system: str) -> float:
    """SI -> display system."""
    if value is None:
        return None
    _, _, f, o = _TABLE[dim]
    return value * f + o if system == IMPERIAL else value


def from_display(value: float, dim: str, system: str) -> float:
    """display system -> SI. Exact inverse of to_display."""
    if value is None:
        return None
    _, _, f, o = _TABLE[dim]
    return (value - o) / f if system == IMPERIAL else value


@dataclass
class Quantity:
    """A number that knows its dimension, so display and export cannot drift."""
    value: float          # ALWAYS SI
    dim: str

    def display(self, system: str) -> float:
        return to_display(self.value, self.dim, system)

    def label(self, system: str) -> str:
        return unit_label(self.dim, system)

    def formatted(self, system: str, places: int = 3) -> str:
        return f"{self.display(system):.{places}g} {self.label(system)}"
