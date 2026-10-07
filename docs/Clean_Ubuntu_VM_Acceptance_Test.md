# Clean Ubuntu VM Installation and Acceptance Test

## Purpose

This procedure proves that the staging layer can be installed from the approved source package on a new Ubuntu VM without copying configuration, credentials, runtime files, or data from the existing POC server.

## Supported baseline

- Ubuntu Server 22.04 LTS or 24.04 LTS.
- `systemd` running as PID 1.
- Working DNS, NTP, package repositories, and outbound HTTPS/TCP 443.
- Source package extracted outside `/opt/Graphana_Proping`.
- No previous Graphana_Proping service user, configuration, data, state, or systemd units.

## Values the operator must prepare

| Input | Source | Security rule |
|---|---|---|
| Prometheus query URL | Grafana Cloud stack details | HTTPS only; do not include credentials in the URL |
| Prometheus username/instance ID | Grafana Cloud stack details | Use the metrics tenant/instance value |
| Loki query URL | Grafana Cloud stack details | HTTPS only; do not include credentials in the URL |
| Loki username/instance ID | Grafana Cloud stack details | Use the logs tenant/instance value |
| Cloud Access Policy token | Dedicated Grafana policy | Only `metrics:read` and `logs:read`; token entry is hidden |
| Token expiry date | Token governance record | `YYYY-MM-DD` or `none` |
| HTTP job name | Grafana Synthetic Monitoring check | Exact job label; no URL or address |
| DNS job name | Grafana Synthetic Monitoring check | Exact job label; no URL or address |
| ML consumer group | Local access design | Defaults to `ddos-ml-readers` |
| Remote-integration Linux user | Existing Ubuntu account | Must be unprivileged; password is never requested or stored |

Do not use a private-probe publishing token as the collector read token.

## One-command clean-VM test

From the extracted repository root, run:

```bash
sudo bash tests/clean_vm_acceptance.sh
```

The command performs this sequence:

1. Confirms supported Ubuntu and a genuinely clean application baseline.
2. Validates Bash, JSON, unit tests, and all release SHA-256 fingerprints.
3. Starts the standard installer questionnaire.
4. Shows a redacted summary and requires confirmation before making system changes.
5. Installs only missing Ubuntu prerequisites.
6. Runs a no-write live Grafana preflight.
7. Creates the least-privilege account, folders, configuration, service, timer, and persistent ACL watcher.
8. Runs the first collection and feature build.
9. Repeats the collection to prove operational execution.
10. Verifies ownership, permissions, timer/watcher state, remote-user read-only access, CSV presence, and the 38-column contract.
11. Writes a sanitized acceptance record.

## Expected success evidence

The final output contains:

```text
[OK] clean Ubuntu VM installation acceptance PASSED
Sanitized evidence: /var/lib/Graphana_Proping/clean-vm-acceptance.txt
```

The report excludes tokens, endpoints, usernames, selectors, job names, target names, and IP addresses.

## Failure behavior

The test fails closed and never deletes an existing installation. Connection, TLS, authentication, authorization, expiry, missing-data, pipeline, and local-permission failures use the stable diagnostic codes documented in `README.md`. Review service failures with:

```bash
sudo journalctl -u graphana-proping-collector.service -n 100 --no-pager
```

After fixing an input such as a URL, username, token, or job name, use a fresh VM snapshot and rerun the same single command so the acceptance evidence remains a clean-install result.

Retain the sanitized acceptance report with the corresponding Git commit and release fingerprints.
