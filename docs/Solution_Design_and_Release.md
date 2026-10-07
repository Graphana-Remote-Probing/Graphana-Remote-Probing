# Graphana_Proping Version 1 Solution Design and Release Document

## 1. Executive summary

Graphana_Proping is the Grafana remote-probing staging layer for DDoS-ML. It makes read-only HTTPS queries to an existing Grafana Cloud stack, preserves bounded raw evidence, and converts approved synthetic-monitoring series into a deterministic 38-column CSV contract. It does not create probes and does not train an ML model.

## 2. Approved purpose

- Defensive monitoring and availability analysis.
- DDoS anomaly-detection feature preparation.
- Authorized security testing and operational research.

Unauthorized interception, scanning, probing, monitoring, traffic generation, or attack simulation is outside scope.

## 3. Architecture

```text
Existing Grafana checks/probes
          |
          | HTTPS 443
          v
Grafana Cloud Prometheus + Loki
          |
          | read-only token
          v
collect_grafana.py -- atomic JSON.gz + manifest
          |
          v
build_features.py -- 38-column current/history CSVs
          |
          v
Approved DDoS-ML read-only consumer
```

## 4. Timing contract

| Control | Default | Configuration | Purpose |
|---|---:|---|---|
| HTTP cloud check | 120 seconds | Grafana Cloud and `targets.json` | Target execution and expected samples |
| DNS cloud check | 600 seconds | Grafana Cloud and `targets.json` | Target execution and expected samples |
| Collector timer | 5 minutes | systemd timer | Local refresh cadence |
| Collector lookback | 30 minutes | environment/service option | Delivery tolerance and source window |
| Feature window | 600 seconds | `targets.json` | One ML aggregation interval |
| Token warnings | 30 and 7 days | environment | Rotation notification |

Cloud frequency and local expected-frequency mapping must change together. Collector cadence is independent.

## 5. Configuration contract

`cloud-read.env` contains non-secret endpoints, usernames, selector, paths, expiry metadata, limits, and timeouts. `cloud-read.token` contains only the token. `targets.json` contains jobs, optional probe metadata, feature window, and expected frequencies. The sanitized default discovers probe labels dynamically and assigns neutral metadata until an authorized operator explicitly configures it.

No frequency, endpoint, username, or token is embedded in Python source.

## 6. Security design

- Dedicated token with `metrics:read` and `logs:read` only.
- HTTPS-only endpoints with no URL-embedded credentials.
- Protected token outside source control.
- Non-login system user and least-privilege systemd sandbox.
- Atomic writes prevent consumers from reading partial evidence or CSVs.
- A success manifest is published only after both cloud payloads are durable.
- Failures return nonzero codes and remain visible in the system journal.
- The timer is enabled only after preflight and the first complete pipeline run pass.

## 7. Diagnostic contract

The same categories apply during installation, scheduled collection, and health checking: configuration (`10`), network (`20`), TLS (`21`), authentication (`30`), authorization (`31`), expiry (`32`), missing data (`40`), pipeline (`50`), and local filesystem/permissions (`60`). Messages never include token values or authorization headers.

## 8. Feature outputs

- `probe_features_current.csv`: atomic snapshot of the newest complete windows for near-live inference.
- `probe_features_history.csv`: idempotent upsert keyed by window, target, job, and probe for training/backtesting.

Both contain the same 38 ordered columns. History is the training source; current is the inference source. Neither contains model predictions or ground-truth DDoS labels.

## 9. Free-tier and licensing limitations

The project depends on Grafana Cloud Free availability and open-source/system components. Every selected probe executes each selected check and therefore increases usage. The operator must review the Grafana usage calculator before adding checks, probes, targets, or frequency. Cloud retention is finite, so long-term ML history must be maintained locally. The private probe may be open source, but its deployment and the Grafana platform are outside this package.

Open-source availability of the probe agent does not make Grafana Cloud executions unlimited or remove Free-tier restrictions. Conversely, this project's release-candidate license is an all-rights-reserved legal-review draft and must not be described as open source. Python's standard library and Ubuntu system components remain subject to their own upstream licenses.

The 38-column contract retains `timeout_rate`, but Version 1 fills it only when an explicit `probe_timeout` metric exists. It intentionally does not treat `probe_failed_due_to_regex` as a timeout. Loki-derived timeout classification is deferred until a separately tested parser is approved.

Official terms and current limits must be revalidated before approval:

- https://grafana.com/pricing/
- https://grafana.com/docs/grafana-cloud/platform/pricing-and-usage/synthetic-monitoring/
- https://grafana.com/docs/grafana-cloud/observe-and-act/testing/synthetic-monitoring/introduction/

## 10. Token lifecycle

The operator records `TOKEN_EXPIRY_DATE` as `YYYY-MM-DD` or `none`. The software warns at 30 and 7 days and fails closed when the recorded date is reached. Rotation procedure:

1. Create a replacement token under the dedicated access policy.
2. Run the installer again and enter the replacement token.
3. Require successful preflight and first collection.
4. Revoke the old token after successful overlap validation.

## 11. Files and ownership

```text
/opt/Graphana_Proping/       root:graphana-proping; executable source read-only to service
/etc/Graphana_Proping/       root:graphana-proping; protected configuration and token
/data/Graphana_Proping/raw/  graphana-proping:graphana-proping; raw evidence
/data/Graphana_Proping/state graphana-proping:graphana-proping; success manifest
/data/Graphana_Proping/features graphana-proping:<consumer-group>; read-only ML exports
```

The feature directory uses SGID so atomic replacements retain the approved consumer group. Version `1.0.0` also records one existing unprivileged SSH integration username and grants it traversal-only directory ACLs plus a read-only ACL on `probe_features_current.csv`. The collector reapplies access synchronously after each feature build, while a systemd path watcher covers other atomic replacements. No password is requested or stored.

## 12. Release status

Version `1.0.0` is privately staged for final public release. It includes a clean-VM acceptance command, but formal execution evidence from an authorized Ubuntu VM, approvals, public visibility, and the final immutable tag remain pending. Any byte change after approval requires a new version and new hashes.
