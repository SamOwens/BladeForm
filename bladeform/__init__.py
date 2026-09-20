"""BladeForm — parametric turbomachinery impeller design.

Read STATUS.md before trusting any number: it states exactly what is verified,
what is a first-order estimate, and what does not work.

    from bladeform import make_preset, air, evaluate, export_step

    d = make_preset("turbocharger")
    op = evaluate(d, air())
    export_step(d, "wheel.step")

Performance figures come from a 1D mean-line model (Euler work, Wiesner slip,
an Oh/Jansen/Coppage-type loss set). They are estimates for navigating a design
space, not predictions of a machine.
"""
__version__ = "1.0.0"

from .params import Design, make_preset, validate, PRESETS, Issue
from .fluids import air, water, custom, IncompressiblePropertyError
from .geometry import (MeridionalChannel, WrapMode, ThicknessLaw,
                       solve_camber, build_blade, fillet_width)
from .performance import (evaluate, choke_mass_flow, optimal_beta1,
                          wiesner_slip, size_from_duty, OperatingPoint)
from .cmap import generate_map, map_to_csv, plot_map
from .mesh import build_scene
from .exporters import (export_stl, export_report, save_project, load_project,
                        fluid_for)
from .units import SI, IMPERIAL, to_display, from_display, unit_label

__all__ = [
    "Design", "make_preset", "validate", "PRESETS", "Issue",
    "air", "water", "custom", "IncompressiblePropertyError",
    "MeridionalChannel", "WrapMode", "ThicknessLaw", "solve_camber",
    "build_blade", "fillet_width",
    "evaluate", "choke_mass_flow", "optimal_beta1", "wiesner_slip",
    "size_from_duty", "OperatingPoint",
    "generate_map", "map_to_csv", "plot_map", "build_scene",
    "export_stl", "export_report", "save_project", "load_project", "fluid_for",
    "SI", "IMPERIAL", "to_display", "from_display", "unit_label",
    "export_step", "verify_step", "__version__",
]


def __getattr__(name):
    """STEP helpers are imported lazily so the package works without a CAD
    kernel installed — everything except STEP export does."""
    if name == "export_step":
        from .step_export import export_step as f
        return f
    if name == "verify_step":
        from .step_verify import verify as f
        return f
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
