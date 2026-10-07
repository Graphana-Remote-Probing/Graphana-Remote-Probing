# Security Policy

## Supported version

Only the latest approved Version 1 release is supported. Version `1.0.0` remains privately staged and is not production-approved until the required reviews and clean-VM acceptance are recorded.

## Secret handling

- Never commit Grafana tokens or populated environment files.
- Enter the read token only through the installer's hidden prompt.
- The installed token must be `root:graphana-proping` mode `0640`.
- Use a dedicated Cloud Access Policy token with only `metrics:read` and `logs:read`.
- Do not reuse the Synthetic Monitoring private-probe token.
- Do not paste credentials into issues, logs, screenshots, or support messages.

## Reporting

Report suspected vulnerabilities privately to the owner listed in `AUTHORS.md`. Include the affected version, reproduction conditions, and impact, but remove credentials and operational telemetry.

## Fail-closed behavior

Installation must stop before enabling the timer when DNS, TLS, authentication, authorization, expiry, or data validation fails. Scheduled failures must return nonzero exit codes and remain visible in the system journal.
