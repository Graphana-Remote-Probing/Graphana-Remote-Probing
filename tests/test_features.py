#!/usr/bin/env python3
"""Standard-library tests for the 38-column feature contract."""

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "src" / "build_features.py"
SPEC = importlib.util.spec_from_file_location("build_features", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "synthetic_prometheus.json"


class FeatureBuilderTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.jobs = {
            "target-http": {
                "target_id": "monitored_service",
                "check_type": "http",
                "frequency_seconds": 120,
            }
        }
        self.probes = {
            "test-probe": {
                "probe_type": "test",
                "probe_location": "lab",
                "probe_provider": "synthetic fixture",
            }
        }

    def test_feature_contract_and_expected_samples(self):
        rows = MODULE.build_rows(self.payload, 600, self.jobs, self.probes)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(MODULE.COLUMNS), 38)
        self.assertEqual(tuple(rows[0].keys()), MODULE.COLUMNS)
        self.assertEqual(rows[0]["samples_expected"], 5)
        self.assertEqual(rows[0]["samples_received"], 5)
        self.assertEqual(rows[1]["failure_count"], 1)
        self.assertEqual(rows[1]["http_5xx_rate"], 0.2)

    def test_history_upsert_is_idempotent(self):
        rows = MODULE.build_rows(self.payload, 600, self.jobs, self.probes)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.csv"
            MODULE.write_csv(path, rows)
            first = MODULE.update_history(path, rows)
            MODULE.write_csv(path, first)
            second = MODULE.update_history(path, rows)
            self.assertEqual(len(second), len(rows))
            with path.open(newline="", encoding="utf-8") as source:
                self.assertEqual(tuple(csv.DictReader(source).fieldnames), MODULE.COLUMNS)

    def test_wildcard_probe_discovers_probe_without_embedding_its_name(self):
        wildcard = {
            "*": {
                "probe_type": "unclassified",
                "probe_location": "not-configured",
                "probe_provider": "not-configured",
            }
        }
        rows = MODULE.build_rows(self.payload, 600, self.jobs, wildcard)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["probe"] for row in rows}, {"test-probe"})


if __name__ == "__main__":
    unittest.main()
