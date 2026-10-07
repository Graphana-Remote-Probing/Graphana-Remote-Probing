# Changelog

## 1.0.0 — 2026-10-05

- Added an installer prompt for an existing unprivileged remote-integration Linux user.
- Added persistent read-only ACL access to `probe_features_current.csv` without requesting or storing a password.
- Added synchronous post-build ACL application plus a systemd path watcher for atomic file replacement.
- Added health and clean-VM acceptance validation for account existence, watcher state, readability, and non-writability.
- Added the Ubuntu `acl` package as the only new prerequisite.

## 1.0.0-rc.3 — 2026-09-29

- Reordered installation so the complete questionnaire and redacted summary occur before system changes.
- Added missing-package detection for Python 3 and CA certificates on clean Ubuntu installations.
- Added a one-command clean Ubuntu VM acceptance test with fail-closed baseline checks.
- Added post-install validation for systemd, permissions, repeated collection, live connectivity, feature outputs, and the 38-column contract.
- Added a sanitized machine-readable acceptance report and complete operator runbook.

## 1.0.0-rc.2 — 2026-09-28

- Removed environment-specific organization, job, target, probe, and location identifiers from source and fixtures.
- Added installer prompts for approved HTTP and DNS job names.
- Added wildcard probe discovery so sanitized source does not embed deployed probe labels.
- Added a regression test for wildcard probe discovery.
- Revalidated the package for secrets, literal IPv4 addresses, syntax, and unit behavior.

## 1.0.0-rc.1 — 2026-09-28

- Created a staging-only release candidate.
- Preserved the documented Prometheus/Loki collection behavior and 38-column feature contract.
- Moved job, probe, frequency, window, and selector settings out of Python source.
- Added token-expiry warnings and actionable network/authentication diagnostics.
- Added a minimal-interaction installer, health check, tests, legal files, and release records.
- Removed Docker, private-probe deployment, GUI, database, ML-model, and unrelated integration components.
