#!/usr/bin/env python3
"""Standard-library unit tests for collector validation behavior."""

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError


SOURCE = Path(__file__).resolve().parents[1] / "src" / "collect_grafana.py"
SPEC = importlib.util.spec_from_file_location("collect_grafana", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CollectorValidationTests(unittest.TestCase):
    def test_https_url_accepts_grafana_endpoint(self):
        self.assertEqual(
            MODULE.validate_https_url("https://example.grafana.net/api/prom/", "Prometheus URL"),
            "https://example.grafana.net/api/prom",
        )

    def test_url_rejects_embedded_credentials(self):
        unsafe_url = "https://" + "user" + ":" + "placeholder" + "@example.net"
        with self.assertRaises(MODULE.DiagnosticError) as context:
            MODULE.validate_https_url(unsafe_url, "Prometheus URL")
        self.assertEqual(context.exception.exit_code, MODULE.EXIT_CONFIG)

    def test_expired_token_metadata_uses_stable_code(self):
        with self.assertRaises(MODULE.DiagnosticError) as context:
            MODULE.check_token_expiry({"TOKEN_EXPIRY_DATE": "2026-09-27"}, today=date(2026, 9, 28))
        self.assertEqual(context.exception.exit_code, MODULE.EXIT_EXPIRED)

    def test_seven_day_warning_does_not_fail(self):
        output = io.StringIO()
        with redirect_stdout(output):
            MODULE.check_token_expiry(
                {"TOKEN_EXPIRY_DATE": "2026-10-05", "TOKEN_WARN_DAYS": "30,7"},
                today=date(2026, 9, 28),
            )
        self.assertIn("[WARNING]", output.getvalue())

    def test_prometheus_sample_count(self):
        payload = {"data": {"result": [{"values": [[1, "1"], [2, "1"]]}, {"values": [[3, "1"]]}]}}
        self.assertEqual(MODULE.count_prometheus_samples(payload), 3)

    def test_http_401_maps_to_authentication_code(self):
        error = HTTPError("https://example.net", 401, "Unauthorized", {}, None)
        with mock.patch.object(MODULE.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(MODULE.DiagnosticError) as context:
                MODULE.api_get("https://example.net", "/api/v1/query", "1", "secret", {}, "Prometheus", 5)
        self.assertEqual(context.exception.exit_code, MODULE.EXIT_AUTH)

    def test_http_403_maps_to_authorization_code(self):
        error = HTTPError("https://example.net", 403, "Forbidden", {}, None)
        with mock.patch.object(MODULE.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(MODULE.DiagnosticError) as context:
                MODULE.api_get("https://example.net", "/api/v1/query", "1", "secret", {}, "Prometheus", 5)
        self.assertEqual(context.exception.exit_code, MODULE.EXIT_FORBIDDEN)


if __name__ == "__main__":
    unittest.main()
