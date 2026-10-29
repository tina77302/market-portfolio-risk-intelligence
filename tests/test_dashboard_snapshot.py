"""Presentation-source checks; never rewrites research data or invokes models."""
import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dashboard_snapshot", ROOT / "frontend/scripts/prepare-dashboard-data.py")
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


class DashboardSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = json.loads((ROOT / "frontend/public/data/global-markets.json").read_text())
        cls.monitor = json.loads((ROOT / "frontend/public/data/korea-monitor.json").read_text())

    def test_korea_display_preserves_exact_monitor_values(self):
        self.assertEqual(len(self.snapshot["korea"]), len(self.monitor["history"]))
        for display, research in zip(self.snapshot["korea"], self.monitor["history"]):
            self.assertEqual(display["date"], research["Date"])
            self.assertEqual(display["risk"], research["Prob_XGBoost"])
            self.assertEqual(display["msi"], research["Korea_MSI"])
            self.assertEqual(display["threshold"], research["Stress_Threshold"])
        self.assertEqual(self.snapshot["asOf"], self.monitor["latest"]["Date"])

    def test_optional_original_project_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            result = bridge.prepare(Path(directory))
        self.assertEqual(result["us"], [])
        self.assertEqual(result["usMetrics"], [])
        self.assertTrue(result["issues"])
        self.assertEqual(result["korea"], self.snapshot["korea"])

    def test_us_exact_dates_and_probability_units(self):
        original = ROOT.parent / "market-stress-early-warning"
        if not original.exists():
            self.skipTest("Original V1 source checkout not present")
        with (original / "data/processed/oos_predictions_10d.csv").open() as handle:
            scores = {row["Date"]: float(row["Prob_XGBoost"]) for row in csv.DictReader(handle)}
        with (original / "data/features/feature_matrix.csv").open() as handle:
            features = {row["Date"]: row for row in csv.DictReader(handle)}
        for row in self.snapshot["us"]:
            self.assertEqual(row["risk"], scores.get(row["date"]))
            self.assertEqual(row["price"], float(features[row["date"]]["SPY"]))
            if row["risk"] is not None:
                self.assertGreaterEqual(row["risk"], 0)
                self.assertLessEqual(row["risk"], 1)
        self.assertTrue(all(row["risk"] is None for row in self.snapshot["us"] if row["date"] > max(scores)))

    def test_stored_metric_precision_is_preserved(self):
        original = ROOT.parent / "market-stress-early-warning"
        path = original / "data/processed/multi_horizon_metrics.csv"
        if not path.exists():
            self.skipTest("Original V1 metrics unavailable")
        with path.open() as handle:
            metrics = {r["Horizon"]: r for r in csv.DictReader(handle) if r["Model"] == "XGBoost"}
        for row in self.snapshot["usMetrics"]:
            stored = metrics[row["horizon"]]
            self.assertEqual(row["auc"], float(stored["ROC_AUC"]))
            self.assertEqual(row["precision"], float(stored["Precision_0.5"]))
            self.assertEqual(row["recall"], float(stored["Recall_0.5"]))
            self.assertEqual(row["f1"], float(stored["F1_0.5"]))

    def test_source_fingerprints_match(self):
        for source in self.snapshot["sources"].values():
            path = ROOT / source["path"]
            if not path.exists():
                path = ROOT.parent / source["path"]
            if not path.exists():
                continue
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), source["sha256"])

    def test_reader_rejects_duplicate_dates_and_percent_units(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text("Date,Prob_XGBoost\n2026-01-01,0.2\n2026-01-01,0.3\n")
            with self.assertRaises(ValueError):
                bridge.read_source(path, ["Prob_XGBoost"], {}, "test", "test")
            path.write_text("Date,Prob_XGBoost\n2026-01-01,52\n")
            with self.assertRaises(ValueError):
                bridge.read_source(path, ["Prob_XGBoost"], {}, "test", "test")


if __name__ == "__main__":
    unittest.main()
