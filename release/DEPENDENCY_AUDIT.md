# Dependency Audit — 1.0.0

## Decision

No `requirements.txt`, virtual environment, or third-party Python package is required.

## Runtime dependencies

| Dependency | Purpose | Provider |
|---|---|---|
| Python 3 standard library | HTTPS queries, JSON/gzip/CSV processing, atomic files, dates, statistics | Ubuntu Python 3 |
| ca-certificates | TLS server validation | Ubuntu |
| systemd | Scheduled oneshot execution and journal | Ubuntu |
| Bash | Installer and health check | Ubuntu |

## Explicitly removed/not included

- Docker and Docker Compose.
- Grafana private-probe agent files.
- `requests`, pandas, NumPy, scikit-learn, and other Python packages.
- Web servers, GUI frameworks, databases, notebooks, and model files.
- OpenCTI and CTI staging files.
- Operational logs, raw downloads, generated CSVs, credentials, and backups.

Any future dependency must identify the importing file, exact function, pinned version, security owner, and removal impact before approval.
