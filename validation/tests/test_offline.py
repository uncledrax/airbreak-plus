import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation/tools"))

from audit import air10_defaults, plus_preset, audit
from scenarios import TICK_S, generate

class SourceAuditTests(unittest.TestCase):
    def test_patch_defaults_read_by_ast(self):
        defaults = air10_defaults()
        self.assertIn("patch-extra-modes", defaults)
        self.assertIsInstance(defaults["patch-extra-modes"], bool)

    def test_plus_preset_parsed(self):
        self.assertIn("patch-fw-asv-wrapper", plus_preset())

    def test_findings_have_provenance_and_status(self):
        for item in audit():
            self.assertTrue(item["id"].startswith("AB-AUD-"))
            self.assertTrue(item["location"])
            self.assertIn(item["classification"], {
                "CONFIRMED_CONFIGURATION", "SOURCE_DEFECT_INDICATOR",
                "PROPOSED_REQUIREMENT_CONFLICT", "AUDIT_INCOMPLETE",
                "EQUIVALENCE_UNPROVEN",
                "DOCUMENTATION_MISMATCH",
            })

class SyntheticSignalTests(unittest.TestCase):
    def test_exact_100_hz_grid(self):
        rows = generate(seconds=2, event_start=0, event_end=0)
        self.assertEqual(len(rows), 200)
        self.assertAlmostEqual(rows[1]["time_s"] - rows[0]["time_s"], TICK_S)
        self.assertAlmostEqual(rows[-1]["time_s"], 1.99)

    def test_central_vs_obstructive_effort(self):
        central = generate(event="central")
        obstructive = generate(event="obstructive")
        active = range(1000, 2000)
        self.assertTrue(all(central[i]["patient_flow_lpm"] == 0 for i in active))
        self.assertTrue(all(central[i]["respiratory_effort_au"] == 0 for i in active))
        self.assertTrue(all(obstructive[i]["patient_flow_lpm"] == 0 for i in active))
        self.assertTrue(any(abs(obstructive[i]["respiratory_effort_au"]) > 0.1 for i in active))

    def test_leak_is_additive(self):
        rows = generate(seconds=1, leak_lpm=18, event_start=0, event_end=0)
        self.assertTrue(all(abs(r["measured_flow_lpm"] -
                                r["patient_flow_lpm"] - 18) < 0.000001
                            for r in rows))

    def test_invalid_parameters_rejected(self):
        with self.assertRaises(ValueError):
            generate(rate_bpm=0)
        with self.assertRaises(ValueError):
            generate(event="sleep apnea")

if __name__ == "__main__":
    unittest.main()
