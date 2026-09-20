"""BladeForm test suite. Each test names the failure mode it guards."""
import sys, os, math, copy, unittest, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from bladeform import fluids, units
from bladeform.params import make_preset, PRESETS, validate, Design
from bladeform.geometry import (MeridionalChannel, solve_camber, WrapMode,
                                build_blade, thickness_distribution, ThicknessLaw)
from bladeform.performance import evaluate, choke_mass_flow, wiesner_slip
from bladeform.mesh import build_scene
from bladeform.exporters import export_stl, save_project, load_project, export_report


class TestFluids(unittest.TestCase):
    """FAILURE MODE 4: fluid choice must switch the solver, not a label."""

    def test_air_reference_values(self):
        a = fluids.air()
        self.assertAlmostEqual(a.density(101325, 288.15), 1.225, places=3)
        self.assertAlmostEqual(a.sound_speed(288.15), 340.4, delta=0.5)
        self.assertAlmostEqual(a.gamma(288.15), 1.40, delta=0.01)

    def test_water_reference_values(self):
        w = fluids.water()
        self.assertAlmostEqual(w.density(101325, 293.15), 998.0, delta=1.0)
        self.assertAlmostEqual(w.viscosity(293.15), 1.002e-3, delta=2e-5)
        self.assertAlmostEqual(w.vapour_pressure(293.15), 2339.0, delta=20)

    def test_liquid_refuses_gas_properties(self):
        """A liquid must RAISE, so a compressible code path cannot silently
        borrow air's gamma while the UI says 'Water'."""
        w = fluids.water()
        for fn in (lambda: w.gamma(293.15), lambda: w.gas_constant(),
                   lambda: w.sound_speed(293.15)):
            with self.assertRaises(fluids.IncompressiblePropertyError):
                fn()

    def test_custom_fluid_is_self_consistent(self):
        c = fluids.custom("R134a", True, gamma=1.12, gas_constant=81.5)
        self.assertAlmostEqual(c.gamma(300), 1.12, places=6)
        self.assertAlmostEqual(c.cp(300), 1.12 * 81.5 / 0.12, places=3)

    def test_custom_incompressible_uses_given_density(self):
        c = fluids.custom("Oil", False, density=870.0, viscosity=0.08,
                          vapour_pressure=50.0)
        self.assertFalse(c.compressible)
        self.assertAlmostEqual(c.density(1e5, 300.0), 870.0, places=6)
        with self.assertRaises(fluids.IncompressiblePropertyError):
            c.gamma(300.0)

    def test_water_and_air_give_different_physics(self):
        d = make_preset("pump")
        op_w = evaluate(d, fluids.water())
        self.assertIsNone(op_w.pressure_ratio)   # liquid -> head, not PR
        self.assertIsNotNone(op_w.head_m)
        self.assertIsNone(op_w.M1_rel)           # Mach not evaluated for a liquid
        self.assertIsNotNone(op_w.npsh_required)
        # Same GEOMETRY, air instead of water, at a mass flow air can actually
        # pass (25 kg/s of air through a 37 mm inducer has no static solution --
        # the solver correctly refuses, which is itself the right behaviour).
        d2 = copy.copy(d); d2.p01 = 101325.0; d2.T01 = 288.15; d2.mdot = 0.30
        op_a = evaluate(d2, fluids.air())
        self.assertIsNotNone(op_a.pressure_ratio)   # gas -> PR
        self.assertIsNotNone(op_a.M1_rel)           # gas -> Mach evaluated
        self.assertIsNone(op_a.head_m)
        self.assertIsNone(op_a.npsh_required)       # gas -> no cavitation check

    def test_impossible_inlet_is_refused_not_faked(self):
        d = copy.copy(make_preset("pump")); d.p01 = 101325.0
        op = evaluate(d, fluids.air())   # 25 kg/s of air through a 37 mm inducer
        self.assertFalse(op.ok)
        self.assertTrue(op.messages)

    def test_incompressible_path_never_touches_gas_properties(self):
        """Hard proof: make the gas accessors explode and run a pump anyway."""
        d = make_preset("pump")
        w = fluids.water()
        calls = []
        for name in ("gamma", "gas_constant", "sound_speed"):
            def boom(*a, _n=name, **k):
                calls.append(_n); raise AssertionError(f"{_n} used for a liquid")
            setattr(w, name, boom)
        op = evaluate(d, w)          # must not raise
        self.assertEqual(calls, [])
        self.assertTrue(op.head_m > 0)


class TestUnits(unittest.TestCase):
    """FAILURE MODE 9: the toggle must convert, not relabel."""

    def test_round_trip_all_dimensions(self):
        for dim in units._TABLE:
            for v in (0.0, 1.0, 137.24):
                imp = units.to_display(v, dim, units.IMPERIAL)
                back = units.from_display(imp, dim, units.IMPERIAL)
                self.assertAlmostEqual(back, v, places=6, msg=dim)

    def test_values_actually_change(self):
        self.assertAlmostEqual(units.to_display(100.0, "length_mm",
                                                units.IMPERIAL), 3.93701, places=4)
        self.assertAlmostEqual(units.to_display(1.0, "power",
                                                units.IMPERIAL), 1.341022, places=5)

    def test_temperature_has_an_offset(self):
        """K->degF is affine, not a scale factor; a relabel-only toggle fails."""
        self.assertAlmostEqual(units.to_display(273.15, "temperature",
                                                units.IMPERIAL), 32.0, places=3)


class TestWrapAngle(unittest.TestCase):
    """FAILURE MODE 3: no hidden rescaling of a physical quantity."""

    def setUp(self):
        d = make_preset("baseline_compressor")
        ch = MeridionalChannel(d.r1_hub, d.r1_shroud, d.r2, d.b2, d.axial_length)
        self.st = ch.streamline(0.5, 160)

    def test_derived_mode_reports_the_integral(self):
        r = solve_camber(self.st, 50, 32, WrapMode.DERIVED, exponent=1.0)
        self.assertEqual(r.mode, WrapMode.DERIVED)
        self.assertGreater(r.wrap_deg, 0)

    def test_target_mode_preserves_beta_endpoints_exactly(self):
        base = solve_camber(self.st, 50, 32, WrapMode.DERIVED, 1.0)
        tgt = base.wrap_deg * 0.8
        r = solve_camber(self.st, 50, 32, WrapMode.TARGET, target_wrap_deg=tgt)
        self.assertTrue(r.target_met)
        self.assertAlmostEqual(r.wrap_deg, tgt, places=4)
        self.assertAlmostEqual(math.degrees(r.beta_rad[0]), 50.0, places=9)
        self.assertAlmostEqual(math.degrees(r.beta_rad[-1]), 32.0, places=9)

    def test_unreachable_target_is_reported_not_clamped(self):
        r = solve_camber(self.st, 50, 32, WrapMode.TARGET, target_wrap_deg=5000.0)
        self.assertFalse(r.target_met)
        self.assertIn("NOT reachable", r.note)
        self.assertAlmostEqual(math.degrees(r.beta_rad[0]), 50.0, places=9)

    def test_changing_beta_changes_wrap(self):
        """Wrap must respond to blade angles -- proof it is not a free input."""
        a = solve_camber(self.st, 40, 30, WrapMode.DERIVED, 1.0).wrap_deg
        b = solve_camber(self.st, 65, 30, WrapMode.DERIVED, 1.0).wrap_deg
        self.assertGreater(b, a * 1.2)


class TestPerformance(unittest.TestCase):
    def test_wiesner_matches_published_form(self):
        z, b2 = 20, 30.0
        expect = 1 - math.sqrt(math.cos(math.radians(b2))) / z ** 0.7
        self.assertAlmostEqual(wiesner_slip(b2, z, 0.1), expect, places=6)

    def test_all_presets_are_physical(self):
        for k in PRESETS:
            d = make_preset(k)
            fl = fluids.water() if d.fluid_kind == "water" else fluids.air()
            op = evaluate(d, fl)
            self.assertTrue(op.ok, f"{k}: {op.messages}")
            self.assertGreater(op.euler_work, 0, k)
            self.assertTrue(0.3 < op.eta_tt < 0.95, f"{k} eta={op.eta_tt}")
            self.assertTrue(0.2 < op.work_coeff < 1.2, f"{k} psi={op.work_coeff}")

    def test_presets_actually_meet_their_stated_duty(self):
        """Sizing iterates on the efficiency the loss model predicts and on
        blade speed, so a preset must hit the target it advertises. A single
        sizing pass assumed eta=0.78 and left presets ~10% adrift."""
        for k in PRESETS:
            d = make_preset(k)
            fl = fluids.water() if d.fluid_kind == "water" else fluids.air()
            op = evaluate(d, fl)
            if fl.compressible:
                target, achieved, base = d.target_pressure_ratio, op.pressure_ratio, 1.0
            else:
                target, achieved, base = d.target_head_m, op.head_m, 0.0
            err = abs((achieved - base) / (target - base) - 1.0)
            self.assertLess(err, 0.01, f"{k}: {achieved:.4f} vs target {target:.4f}")

    def test_presets_have_choke_margin_and_no_warnings(self):
        for k in PRESETS:
            d = make_preset(k)
            fl = fluids.water() if d.fluid_kind == "water" else fluids.air()
            self.assertEqual([i.field for i in validate(d)], [], k)
            mc = choke_mass_flow(d, fl)
            if mc:
                self.assertGreater(mc / d.mdot, 1.05, f"{k}: sits on its choke line")

    def test_low_choke_margin_is_flagged(self):
        d = make_preset("turbocharger")
        d.mdot *= 1.30                      # push the design point past choke
        fields = [i.field for i in validate(d)]
        self.assertIn("mdot", fields, "a choked design was not flagged")

    def test_passage_geometry_is_physical(self):
        """Blade path must exceed the meridional length (the blade wraps), and
        the hydraulic diameter must fit inside the passage."""
        from bladeform.performance import _passage_geometry
        for k in PRESETS:
            d = make_preset(k)
            Z = d.n_main + d.n_splitter * (1 - d.splitter_start_frac)
            L_b, d_hyd = _passage_geometry(d, Z, d.beta2_hub_deg)
            merid = math.hypot(d.axial_length, d.r2 - d.r1_shroud)
            self.assertGreater(L_b, merid, f"{k}: blade path shorter than meridional")
            self.assertLess(d_hyd, 2 * max(d.b2, d.r1_shroud - d.r1_hub), k)
            self.assertGreater(L_b / d_hyd, 1.0, k)

    def test_inlet_solver_returns_none_rather_than_nan(self):
        """The final evaluation used to skip the static-temperature guard and
        produce a silent NaN."""
        from bladeform.performance import _inlet_compressible
        out = _inlet_compressible(fluids.air(), 101325.0, 288.15,
                                  mdot=500.0, A1=1e-5)   # hopeless duty
        self.assertEqual(out, (None, None, None))

    def test_choke_flow_rises_with_shaft_speed(self):
        d = make_preset("turbocharger"); a = fluids.air()
        lo = choke_mass_flow(d, a, d.rpm * 0.6)
        hi = choke_mass_flow(d, a, d.rpm * 1.1)
        self.assertGreater(hi, lo)

    def test_choke_is_none_for_liquids(self):
        self.assertIsNone(choke_mass_flow(make_preset("pump"), fluids.water()))


class TestValidationAndExtremes(unittest.TestCase):
    """FAILURE MODE 10: sweep parameters to their limits."""

    def test_degenerate_annulus_is_an_error(self):
        d = make_preset("baseline_compressor")
        d.r1_shroud = d.r1_hub * 0.999
        self.assertTrue(any(i.level == "error" and i.field == "r1_shroud"
                            for i in validate(d)))

    def test_blade_self_intersection_is_flagged(self):
        d = make_preset("turbocharger")
        d.n_main, d.t_le = 60, 0.004
        self.assertTrue(any(i.level == "error" for i in validate(d)),
                        "massively over-bladed wheel not flagged")

    def test_parameter_extremes_do_not_crash(self):
        base = make_preset("baseline_compressor")
        sweeps = {
            "n_main": [1, 3, 30], "n_splitter": [0, 9, 18],
            "beta2_hub_deg": [0.0, 45.0, 70.0],
            "beta1_shroud_deg": [5.0, 45.0, 80.0],
            "b2": [base.b2 * 0.05, base.b2 * 3],
            "t_max": [base.t_max * 0.1, base.t_max * 4],
            "hub_fillet": [0.0, base.b2 * 0.9],
            "exit_pitch_deg": [0.0, 60.0],
            "axial_length": [base.axial_length * 0.2, base.axial_length * 3],
            "splitter_start_frac": [0.02, 0.95],
            "lean_deg": [-30.0, 30.0], "inlet_sweep_deg": [-25.0, 25.0],
            "exit_rake_deg": [-20.0, 20.0],
        }
        for field, values in sweeps.items():
            for v in values:
                d = copy.copy(base); setattr(d, field, v)
                validate(d)                      # must not raise
                sc = build_scene(d, lod=0)       # geometry must not raise
                self.assertTrue(np.all(np.isfinite(sc["vertices"])),
                                f"non-finite geometry at {field}={v}")
                op = evaluate(d, fluids.air())
                if op.ok:
                    self.assertTrue(np.isfinite(op.eta_tt), f"{field}={v}")

    def test_near_zero_annulus_geometry_stays_finite(self):
        d = make_preset("baseline_compressor")
        d.r1_hub = d.r1_shroud * 0.999
        sc = build_scene(d, lod=0)
        self.assertTrue(np.all(np.isfinite(sc["vertices"])))


class TestGeometry(unittest.TestCase):
    def test_thickness_laws_hit_their_endpoints(self):
        s = np.linspace(0, 1, 50)
        for law in ThicknessLaw:
            t = thickness_distribution(s, 1.0, 3.0, 2.0, law)
            self.assertAlmostEqual(t[0], 1.0, places=6, msg=law.value)
            self.assertAlmostEqual(t[-1], 2.0, places=6, msg=law.value)
            self.assertTrue(np.all(t > 0))

    def test_meridional_contour_never_overshoots_the_exit_plane(self):
        """Regression: Bezier handles scaled by the diagonal chord put a hub
        control point past the exit plane and flattened the hub into a disc."""
        for k in PRESETS:
            d = make_preset(k)
            ch = MeridionalChannel(d.r1_hub, d.r1_shroud, d.r2, d.b2,
                                   d.axial_length, d.exit_pitch_deg)
            Ph, Ps = ch._control_points()
            self.assertLessEqual(Ph[:, 0].max(), d.axial_length + 1e-9, k)

    def test_splitters_are_shorter_than_main_blades(self):
        d = make_preset("turbocharger")
        ch = MeridionalChannel(d.r1_hub, d.r1_shroud, d.r2, d.b2, d.axial_length)
        main = build_blade(ch, d, 5, 30, 0.0, 0.0)
        split = build_blade(ch, d, 5, 30, 0.0, d.splitter_start_frac)
        lm = np.linalg.norm(np.diff(main.camber[0], axis=0), axis=1).sum()
        ls = np.linalg.norm(np.diff(split.camber[0], axis=0), axis=1).sum()
        self.assertLess(ls, lm)


class TestRootFillet(unittest.TestCase):
    """The hub fillet is a MODELLED blend (BRepFilletAPI could not fillet this
    junction at any radius tested). These check it is real geometry."""

    def test_profile_is_a_circular_arc(self):
        from bladeform.geometry import fillet_width
        R = 2.0
        self.assertAlmostEqual(float(fillet_width(0.0, R)), R, places=12)
        self.assertAlmostEqual(float(fillet_width(R, R)), 0.0, places=12)
        self.assertAlmostEqual(float(fillet_width(2 * R, R)), 0.0, places=12)
        hs = np.linspace(0, R, 40)
        w = fillet_width(hs, R)
        self.assertTrue(np.all(np.diff(w) <= 1e-12), "fillet width must taper monotonically")
        # points must lie on the circle of radius R centred R above the hub
        self.assertTrue(np.allclose((R - w) ** 2 + (R - hs) ** 2, R * R, atol=1e-12))

    def test_zero_radius_changes_nothing(self):
        d = make_preset("pump")
        ch = MeridionalChannel(d.r1_hub, d.r1_shroud, d.r2, d.b2, d.axial_length)
        a = copy.copy(d); a.hub_fillet = 0.0
        b0 = build_blade(ch, a, 9, 30)
        self.assertTrue(np.all(np.isfinite(b0.pressure)))

    def test_fillet_widens_the_root_but_not_midspan(self):
        for k in PRESETS:
            d = make_preset(k)
            a = copy.copy(d); a.hub_fillet = 0.0
            ch = MeridionalChannel(d.r1_hub, d.r1_shroud, d.r2, d.b2,
                                   d.axial_length, d.exit_pitch_deg)
            b0, b1 = build_blade(ch, a, 13, 40), build_blade(ch, d, 13, 40)
            w = lambda b, i: np.linalg.norm(b.pressure[i] - b.suction[i], axis=-1).mean()
            self.assertGreater(w(b1, 0), w(b0, 0) * 1.2, f"{k}: root not widened")
            self.assertAlmostEqual(w(b1, 12), w(b0, 12), places=9,
                                   msg=f"{k}: fillet leaked into the tip section")

    def test_fillet_adds_material(self):
        from bladeform.mesh import blade_mesh, signed_volume
        for k in PRESETS:
            d = make_preset(k)
            a = copy.copy(d); a.hub_fillet = 0.0
            ch = MeridionalChannel(d.r1_hub, d.r1_shroud, d.r2, d.b2,
                                   d.axial_length, d.exit_pitch_deg)
            vols = []
            for dd in (a, d):
                b = build_blade(ch, dd, 13, 60, span_min=-0.04)
                V, F = blade_mesh(b.pressure, b.suction)
                vols.append(signed_volume(V, F))
            grow = (vols[1] - vols[0]) / vols[0]
            self.assertGreater(grow, 0, f"{k}: fillet removed material")
            self.assertLess(grow, 0.6, f"{k}: fillet added {grow:.0%} — loft has folded")

    def test_section_layout_does_not_depend_on_fillet(self):
        """Otherwise a filleted and an unfilleted blade are lofted through
        different section counts and any comparison is meaningless."""
        from bladeform.geometry import span_positions
        self.assertTrue(np.allclose(span_positions(13, -0.04), span_positions(13, -0.04)))
        d = make_preset("pump"); a = copy.copy(d); a.hub_fillet = 0.0
        ch = MeridionalChannel(d.r1_hub, d.r1_shroud, d.r2, d.b2, d.axial_length)
        self.assertEqual(build_blade(ch, a, 13, 30).pressure.shape,
                         build_blade(ch, d, 13, 30).pressure.shape)

    def test_fillet_counts_toward_blade_blockage(self):
        d = make_preset("turbocharger")
        d.hub_fillet = 8 * d.t_le
        self.assertTrue(any(i.level in ("warn", "error") and i.field == "n_main"
                            for i in validate(d)),
                        "a fillet consuming the blade pitch was not flagged")


class TestMeshOrientation(unittest.TestCase):
    """A closed shell with inconsistent winding renders fine under a
    double-sided material but flips STL facet normals."""

    def test_every_edge_is_used_once_each_way(self):
        from collections import Counter
        from bladeform.mesh import blade_mesh
        for k in PRESETS:
            d = make_preset(k)
            ch = MeridionalChannel(d.r1_hub, d.r1_shroud, d.r2, d.b2,
                                   d.axial_length, d.exit_pitch_deg)
            b = build_blade(ch, d, 9, 30)
            V, F = blade_mesh(b.pressure, b.suction)
            dirs = Counter()
            for t in F:
                for a, c in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                    dirs[(a, c)] += 1
            flipped = sum(1 for v in dirs.values() if v > 1)
            self.assertEqual(flipped, 0, f"{k}: {flipped} edges wound the same way on both sides")

    def test_normals_point_outward(self):
        from bladeform.mesh import blade_mesh, signed_volume
        for k in PRESETS:
            d = make_preset(k)
            ch = MeridionalChannel(d.r1_hub, d.r1_shroud, d.r2, d.b2,
                                   d.axial_length, d.exit_pitch_deg)
            b = build_blade(ch, d, 9, 30)
            V, F = blade_mesh(b.pressure, b.suction)
            self.assertGreater(signed_volume(V, F), 0, f"{k}: mesh is inside-out")


class TestExporters(unittest.TestCase):
    def test_project_round_trip(self):
        d = make_preset("mixed_flow_fan")
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "x.bfproj")
            save_project(d, p, snapshots=[{"name": "s1", "design": d.to_dict()}])
            d2, snaps = load_project(p)
            self.assertEqual(len(snaps), 1)
            for f in ("r2", "b2", "beta2_hub_deg", "n_main", "rpm"):
                self.assertEqual(getattr(d2, f), getattr(d, f), f)

    def test_stl_triangle_count_tracks_lod(self):
        """STL IS a mesh, so unlike STEP it SHOULD follow the LOD setting."""
        d = make_preset("baseline_compressor")
        with tempfile.TemporaryDirectory() as td:
            a = export_stl(d, os.path.join(td, "a.stl"), lod=0)
            b = export_stl(d, os.path.join(td, "b.stl"), lod=2)
            self.assertGreater(b["triangles"], a["triangles"] * 3)

    def test_report_contains_estimate_disclaimer(self):
        d = make_preset("pump")
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "r.html")
            export_report(d, p, include_map=False)
            html = open(p).read()
            self.assertIn("first-order estimates", html)
            self.assertIn("NPSH", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
