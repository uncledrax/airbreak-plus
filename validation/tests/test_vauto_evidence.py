import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validation/tools"))
from vauto_evidence import PRESSURE_FIELDS, evaluate_trace, enforce_selected_max


class VAutoEvidenceTests(unittest.TestCase):
    def evaluate(self, rows, required_scenarios=None):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "vauto-trace.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(("scenario", "tick", "state", *PRESSURE_FIELDS))
                writer.writerows(rows)
            return evaluate_trace(path, required_scenarios)

    def test_selected_max_is_checked_independently_of_harness_status(self):
        report = self.evaluate([
            ("sequence", 0, "ACTIVE", 20, 20, 20, 0),
            ("sequence", 1, "ACTIVE", 20, 23, 20, 3),
            ("sequence", 2, "ACTIVE", 19, 21, 20, 2),
        ])
        self.assertEqual(report["status"], "EXCEEDED_AT_LIMITER_INPUT")
        self.assertEqual(report["exceedance_samples"], 2)
        self.assertEqual(report["max_excess_cmh2o"], 3)
        scenario = report["scenarios"][0]
        self.assertEqual(scenario["stock_exceedance_samples"], 0)
        self.assertEqual(scenario["first_exceedance"]["tick"], 1)
        self.assertEqual(scenario["largest_exceedance"]["wrapper_request_cmh2o"], 23)
        self.assertFalse(enforce_selected_max(report))

    def test_comparison_uses_each_rows_selected_limit_and_tolerance(self):
        report = self.evaluate([
            ("sequence", 0, "ACTIVE", 20, 20.00005, 20, 0.00005),
            ("sequence", 1, "ACTIVE", 18, 18, 18, 0),
        ])
        self.assertEqual(report["status"], "WITHIN_LIMIT_FOR_TESTED_TRACE")
        self.assertTrue(enforce_selected_max(report))

    def test_empty_and_nonfinite_evidence_never_pass(self):
        for rows in ([], [("fault", 0, "ACTIVE", 20, "nan", 20, "nan")],
                     [("fault", 0, "ACTIVE", 20, "inf", 20, "inf")]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.evaluate(rows)
        self.assertFalse(enforce_selected_max({"status": "UNAVAILABLE"}))

    def test_inconsistent_delta_and_malformed_rows_are_rejected(self):
        for row in (("sequence", 0, "ACTIVE", 20, 23, 20, 1),
                    ("sequence", 0, "ACTIVE", 20, 23, 20),
                    ("sequence", -1, "ACTIVE", 20, 20, 20, 0)):
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.evaluate([row])

    def test_missing_columns_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "missing.csv"
            path.write_text("scenario,tick\nsequence,0\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                evaluate_trace(path)

    def test_truncated_or_missing_scenarios_cannot_pass_the_required_coverage(self):
        rows = [("sequence", 0, "ACTIVE", 20, 20, 20, 0)]
        with self.assertRaises(ValueError):
            self.evaluate(rows, {"sequence": 2})
        with self.assertRaises(ValueError):
            self.evaluate(rows, {"missing": 1})
        self.assertTrue(enforce_selected_max(self.evaluate(rows, {"sequence": 1})))

    def test_reordered_ticks_and_unknown_states_are_rejected(self):
        row = ("sequence", 0, "ACTIVE", 20, 20, 20, 0)
        with self.assertRaises(ValueError):
            self.evaluate([row, row])
        with self.assertRaises(ValueError):
            self.evaluate([("sequence", 0, "INVALID", 20, 20, 20, 0)])


if __name__ == "__main__":
    unittest.main()
