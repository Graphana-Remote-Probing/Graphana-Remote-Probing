# Test Evidence — 1.0.0

**Test date:** 2026-10-01  
**Environment:** Isolated build workspace, Python 3.12, Bash syntax checker  
**Status:** Local source validation passed; clean Ubuntu VM acceptance remains pending.

## Completed checks

| Check | Result |
|---|---|
| Collector Python compilation | PASS |
| Feature-builder Python compilation | PASS |
| Installer Bash syntax | PASS |
| Health-check Bash syntax | PASS |
| HTTPS endpoint validation | PASS |
| Embedded URL credential rejection | PASS |
| Token-expiry fail-closed code `32` | PASS |
| Seven-day expiry warning | PASS |
| HTTP `401` to code `30` mapping | PASS |
| HTTP `403` to code `31` mapping | PASS |
| Prometheus sample counting | PASS |
| 38-column feature order | PASS |
| Expected-sample calculation | PASS |
| Failure and HTTP 5xx calculations | PASS |
| History idempotent upsert | PASS |
| Wildcard probe discovery with sanitized metadata | PASS |
| Source credential-pattern scan | PASS |
| Prohibited generated-file scan | PASS after cache cleanup |
| Clean-VM acceptance script Bash syntax | PASS |
| Clean-VM baseline guard design | PASS by source review; live execution pending |

Fourteen standard-library unit tests passed.

## Not yet claimed

The following require an authorized clean Ubuntu VM and real Grafana credentials. They are intentionally not marked complete:

- Live DNS/TLS/Prometheus/Loki preflight.
- Real token, scope, source-IP, and expiry cases.
- First real clean-VM collection and feature publication.
- systemd hardening verification under the target OS.
- Reboot, timer, repair, stale-file, disk-full, and rollback scenarios.
- Behavioral comparison against the current POC server.

No final approval or production-readiness claim is made until these tests are recorded.
