# Freeze Record

| Field | Value |
|---|---|
| Product | Graphana_Proping |
| Candidate version | 1.0.0 |
| Freeze date | 2026-10-05 |
| Behavioral baseline | Graphana_Remote_Probing.pdf Revision 4, pages 40–58 |
| Confirmed live design | Prometheus + Loki, 30-minute lookback, 5-minute collector, 10-minute features |
| Feature contract | 38 ordered columns |
| Python dependencies | Standard library only |
| Development source commit | `0bc819c8033aa565b632f22546124c8cea310c91` |
| Approval | Pending |

The public-release staging tree was exported from the frozen private development commit shown above without copying its `.git` directory or history. It must still pass clean-VM validation before final approval, public visibility, or tag creation.

Functional changes after this freeze require a new candidate version and regenerated SHA-256 records.
