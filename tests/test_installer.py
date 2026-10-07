#!/usr/bin/env python3
"""Static contract tests for the clean-VM installation workflow."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = (ROOT / "install_Graphana_Proping.sh").read_text(encoding="utf-8")
ACCEPTANCE = (ROOT / "tests" / "clean_vm_acceptance.sh").read_text(encoding="utf-8")


class InstallerContractTests(unittest.TestCase):
    def test_questionnaire_and_confirmation_precede_package_changes(self):
        self.assertLess(INSTALLER.index('prompt_required prom_url'), INSTALLER.index('apt-get update'))
        self.assertLess(INSTALLER.index('Proceed with prerequisite installation'), INSTALLER.index('apt-get update'))

    def test_secret_token_input_is_hidden_and_never_in_summary(self):
        self.assertIn('read -r -s -p "5/10 Dedicated Grafana Cloud read token', INSTALLER)
        self.assertIn("Token: [REDACTED]", INSTALLER)

    def test_all_external_integration_inputs_are_requested(self):
        for variable in ("prom_url", "prom_user", "loki_url", "loki_user", "http_job", "dns_job"):
            self.assertIn(f"prompt_required {variable}", INSTALLER)
        self.assertIn("Token expiry date", INSTALLER)
        self.assertIn("DDoS-ML consumer Unix group", INSTALLER)
        self.assertIn("Existing remote-integration Linux username", INSTALLER)
        self.assertIn('getent passwd "$integration_user"', INSTALLER)

    def test_persistent_read_only_integration_acl_is_installed(self):
        self.assertIn("acl", INSTALLER)
        self.assertIn("apply_integration_acl.sh", INSTALLER)
        self.assertIn("graphana-proping-export-acl.path", INSTALLER)
        self.assertIn("integration-read-user", INSTALLER)
        acl_script = (ROOT / "scripts" / "apply_integration_acl.sh").read_text(encoding="utf-8")
        self.assertIn('u:${integration_user}:r--', acl_script)
        self.assertNotIn("password", acl_script.lower())

    def test_acceptance_wrapper_invokes_installer_and_live_health(self):
        self.assertIn('bash "$PACKAGE_ROOT/install_Graphana_Proping.sh"', ACCEPTANCE)
        self.assertIn('"$INSTALL_ROOT/scripts/health_check.sh" --live', ACCEPTANCE)
        self.assertIn('overall=PASS', ACCEPTANCE)


if __name__ == "__main__":
    unittest.main()
