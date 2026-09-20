"""STEP export tests -- FAILURE MODES 1 and 11.

Slow (each export runs a boolean), so kept separate from the fast suite.
Uses a single-blade wheel to keep runtime sane on one CPU.
"""
import sys, os, copy, unittest, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bladeform.params import make_preset
from bladeform.mesh import build_scene
import bladeform.step_export as SE
from bladeform.step_verify import verify, compare_face_counts


def one_blade(key="turbocharger"):
    d = copy.copy(make_preset(key)); d.n_main = 1; d.n_splitter = 0
    return d


def full(key="turbocharger"):
    return make_preset(key)


class TestStepIsRealBrep(unittest.TestCase):
    """FAILURE MODE 1: not a triangle soup in a STEP costume."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.d = full()
        cls.path = os.path.join(cls.tmp, "w.step")
        cls.res = SE.export_step(cls.d, cls.path)
        cls.v = verify(cls.path)

    def test_no_triangle_soup_markers(self):
        self.assertNotIn("POLY_LOOP", str(self.v))
        self.assertEqual(self.v["problems"], [], self.v["problems"])

    def test_has_genuine_curved_surfaces(self):
        self.assertTrue(self.v["curved_surfaces"],
                        "no curved surface entities -- looks like a faked mesh")
        self.assertIn("B_SPLINE_SURFACE_WITH_KNOTS", self.v["curved_surfaces"])

    def test_face_count_is_tiny_next_to_the_preview_mesh(self):
        """A faked export has one face per preview triangle (tens of thousands)."""
        tris = build_scene(self.d, lod=2)["tri_count"]
        self.assertLess(self.v["advanced_faces"], tris / 50)

    def test_face_count_is_fully_explained_by_the_surface_definition(self):
        """The strongest form of the Failure Mode 1 check: every face is
        accounted for by N_SECTIONS, not by any tessellation setting.

        Each blade is a ruled loft: 4 lateral patches per section gap, plus 2
        caps. The hub is a revolved profile. If the arithmetic stops matching,
        something is generating faces from a mesh."""
        d = self.d
        per_blade = 4 * (SE.N_SECTIONS - 1) + 2
        n_blades = d.n_main + (d.n_splitter if d.n_main and
                               d.n_splitter // d.n_main else 0)
        hub_faces = SE.count_faces(SE.build_hub_solid(d))
        self.assertEqual(self.v["advanced_faces"],
                         n_blades * per_blade + hub_faces,
                         f"{n_blades} blades x {per_blade} + hub {hub_faces}")

    def test_every_preset_exports_real_brep(self):
        for key in ("turbocharger", "pump", "baseline_compressor",
                    "mixed_flow_fan"):
            with tempfile.TemporaryDirectory() as td:
                pth = os.path.join(td, f"{key}.step")
                SE.export_step(make_preset(key), pth)
                v = verify(pth)
                self.assertEqual(v["problems"], [], f"{key}: {v['problems']}")
                self.assertTrue(v["curved_surfaces"], key)

    def test_is_a_closed_solid(self):
        self.assertGreaterEqual(self.v["closed_shells"], 1)
        self.assertGreaterEqual(self.v["manifold_solids"], 1)


class TestStepIgnoresPreviewLod(unittest.TestCase):
    """FAILURE MODE 1's structural test: turning up viewer detail must NOT
    change the exported face count. If it does, the export is faked."""

    def test_face_count_identical_across_preview_lods(self):
        d = full()
        tmp = tempfile.mkdtemp()
        counts = []
        for lod in (0, 2):
            tris = build_scene(d, lod=lod)["tri_count"]     # drive the preview
            p = os.path.join(tmp, f"lod{lod}.step")
            SE.export_step(d, p)
            counts.append((lod, tris, verify(p)["advanced_faces"]))
        self.assertNotEqual(counts[0][1], counts[1][1],
                            "preview tessellation did not actually change")
        self.assertEqual(counts[0][2], counts[1][2],
                         f"STEP face count changed with preview LOD: {counts}")

    def test_lod_is_not_even_an_input_to_the_exporter(self):
        import inspect
        src = inspect.getsource(SE)
        self.assertNotIn("lod", src.split("FAILURE MODE 1")[-1].split('"""')[-1],
                         "step_export references preview LOD")


class TestDownstreamExport(unittest.TestCase):
    """Section 8: the diffuser and volute must be in the STEP file when enabled."""

    def test_vanes_and_volute_add_solids(self):
        import copy
        base = full("baseline_compressor")
        with tempfile.TemporaryDirectory() as td:
            plain = verify(_ex(base, td, "plain"))
            withd = copy.copy(base); withd.diffuser_on = True
            vaned = verify(_ex(withd, td, "vaned"))
            withv = copy.copy(withd); withv.volute_on = True
            both = verify(_ex(withv, td, "both"))
        self.assertGreater(vaned["manifold_solids"], plain["manifold_solids"],
                           "enabling the diffuser added no solids")
        self.assertGreater(both["manifold_solids"], vaned["manifold_solids"],
                           "enabling the volute added no solids")
        for v in (vaned, both):
            self.assertEqual(v["problems"], [], v["problems"])

    def test_vane_count_matches_the_parameter(self):
        import copy
        d = copy.copy(full("baseline_compressor"))
        d.diffuser_on = True; d.diffuser_vanes = 11
        with tempfile.TemporaryDirectory() as td:
            a = verify(_ex(d, td, "v11"))
            d2 = copy.copy(d); d2.diffuser_vanes = 21
            b = verify(_ex(d2, td, "v21"))
        per_vane = (b["manifold_solids"] - a["manifold_solids"]) / 10
        self.assertAlmostEqual(per_vane, 1.0, places=6,
                               msg="vane count did not drive the solid count")

    def test_vane_angle_follows_the_computed_swirl(self):
        import copy
        d = copy.copy(full("baseline_compressor")); d.diffuser_on = True
        a3_slow, _ = SE.diffuser_vane_angles(d)
        fast = copy.copy(d); fast.rpm = d.rpm * 1.6
        a3_fast, _ = SE.diffuser_vane_angles(fast)
        self.assertNotAlmostEqual(a3_slow, a3_fast, places=2,
                                  msg="vane inlet angle is a fixed stagger, not the real swirl")


def _ex(d, td, name):
    p = os.path.join(td, name + ".step")
    SE.export_step(d, p)
    return p


class TestFilletIsHonest(unittest.TestCase):
    """FAILURE MODE 11: never claim a fillet that did not happen."""

    def test_export_states_the_fillet_is_modelled_not_a_kernel_operation(self):
        d = full(); d.hub_fillet = 0.3 * d.t_le
        with tempfile.TemporaryDirectory() as td:
            res = SE.export_step(d, os.path.join(td, "c.step"))
            note = " ".join(res["notes"])
            self.assertIn("modelled", note)
            self.assertIn("not a kernel fillet", note)

    def test_fused_mode_validates_its_own_output(self):
        """Fused mode must raise rather than write an invalid or empty solid."""
        d = one_blade("mixed_flow_fan"); d.hub_fillet = 0.0
        with tempfile.TemporaryDirectory() as td:
            res = SE.export_step(d, os.path.join(td, "f.step"), mode="fused")
            self.assertGreater(res["faces"], 0)
            v = verify(os.path.join(td, "f.step"))
            self.assertEqual(v["problems"], [])

    def test_failed_fillet_is_reported_not_hidden(self):
        d = one_blade("mixed_flow_fan"); d.hub_fillet = 0.3 * d.t_le
        with tempfile.TemporaryDirectory() as td:
            res = SE.export_step(d, os.path.join(td, "f.step"), mode="fused")
            note = " ".join(res["notes"])
            if res["faces"] == res["faces_before_fillet"]:
                self.assertTrue(any(w in note for w in
                                    ("FAILED", "SKIPPED", "NO NEW FACES")),
                                f"fillet did nothing but notes say: {note}")
            else:
                self.assertIn("applied", note)


if __name__ == "__main__":
    unittest.main(verbosity=2)
