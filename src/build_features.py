#!/usr/bin/env python3
"""Build stable ML feature windows from the latest approved collection.

Copyright © 2026 Ahmed Mekky. All rights reserved.
Use, modification, and redistribution are governed by the LICENSE file.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_ENV = Path("/etc/Graphana_Proping/cloud-read.env")
DEFAULT_TARGETS = Path("/etc/Graphana_Proping/targets.json")
DEFAULT_DATA_ROOT = Path("/data/Graphana_Proping")

EXIT_CONFIG = 10
EXIT_NO_DATA = 40
EXIT_FEATURE = 50
EXIT_LOCAL = 60

COLUMNS = (
    "window_start_utc", "window_end_utc", "target_id", "job", "check_type",
    "probe", "probe_type", "probe_location", "probe_provider", "success_rate",
    "failure_count", "consecutive_failure_max", "duration_avg_ms", "duration_p50_ms",
    "duration_p95_ms", "duration_p99_ms", "dns_lookup_avg_ms", "dns_lookup_p95_ms",
    "dns_resolve_avg_ms", "dns_connect_avg_ms", "dns_request_avg_ms",
    "http_resolve_avg_ms", "http_connect_avg_ms", "http_tls_avg_ms",
    "http_processing_avg_ms", "http_transfer_avg_ms", "http_status_mode",
    "http_4xx_rate", "http_5xx_rate", "timeout_rate",
    "http_content_length_avg_bytes", "dns_answer_rrs_avg", "dns_authority_rrs_avg",
    "dns_additional_rrs_avg", "tls_days_remaining_min", "samples_expected",
    "samples_received", "missing_data_flag",
)


class FeatureError(Exception):
    def __init__(self, exit_code: int, cause: str, action: str):
        super().__init__(cause)
        self.exit_code = exit_code
        self.cause = cause
        self.action = action


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise FeatureError(EXIT_CONFIG, f"Cannot read configuration: {path}", "Check the installed configuration path and permissions.") from exc
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            raise FeatureError(EXIT_CONFIG, f"Invalid environment line {line_number}.", "Run installer repair mode.")
        values[key.strip()] = value.strip()
    return values


def load_feature_config(path: Path) -> tuple[int, dict, dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FeatureError(EXIT_CONFIG, f"Cannot read valid feature configuration: {path}", "Restore targets.json or run installer repair mode.") from exc

    if payload.get("schema_version") != 1:
        raise FeatureError(EXIT_CONFIG, "Unsupported targets.json schema version.", "Use the configuration supplied with this release.")
    window_seconds = payload.get("window_seconds")
    jobs = payload.get("jobs")
    probes = payload.get("probes")
    if not isinstance(window_seconds, int) or window_seconds <= 0:
        raise FeatureError(EXIT_CONFIG, "window_seconds must be a positive integer.", "Correct targets.json.")
    if not isinstance(jobs, dict) or not jobs or not isinstance(probes, dict) or not probes:
        raise FeatureError(EXIT_CONFIG, "At least one job and one probe are required.", "Correct targets.json.")

    for job_name, details in jobs.items():
        if not isinstance(details, dict):
            raise FeatureError(EXIT_CONFIG, f"Job configuration is invalid: {job_name}", "Correct targets.json.")
        frequency = details.get("frequency_seconds")
        if not details.get("target_id") or details.get("check_type") not in {"http", "dns", "ping", "tcp", "traceroute", "multihttp", "scripted"}:
            raise FeatureError(EXIT_CONFIG, f"Job metadata is invalid: {job_name}", "Set target_id and a supported check_type.")
        if not isinstance(frequency, int) or frequency <= 0 or window_seconds % frequency:
            raise FeatureError(
                EXIT_CONFIG,
                f"window_seconds={window_seconds} is not divisible by {job_name} frequency_seconds={frequency}",
                "Change the external frequency mapping or choose a compatible feature window.",
            )
    for probe_name, details in probes.items():
        if not isinstance(details, dict) or not all(details.get(name) for name in ("probe_type", "probe_location", "probe_provider")):
            raise FeatureError(EXIT_CONFIG, f"Probe metadata is invalid: {probe_name}", "Correct targets.json.")
    return window_seconds, jobs, probes


def utc_string(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def finite_values(values):
    return [value for value in values if value is not None and math.isfinite(value)]


def average(values):
    cleaned = finite_values(values)
    return statistics.fmean(cleaned) if cleaned else None


def percentile(values, fraction):
    cleaned = sorted(finite_values(values))
    if not cleaned:
        return None
    position = (len(cleaned) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return cleaned[lower]
    return cleaned[lower] * (upper - position) + cleaned[upper] * (position - lower)


def rounded(value, digits=6):
    return "" if value is None else round(value, digits)


def milliseconds(values, statistic=average):
    value = statistic(values)
    return rounded(value * 1000, 3) if value is not None else ""


def longest_failure_sequence(samples):
    longest = current = 0
    for _, value in sorted(samples):
        if value < 0.5:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def mode_integer(values):
    integers = [int(round(value)) for value in finite_values(values)]
    return Counter(integers).most_common(1)[0][0] if integers else ""


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=COLUMNS, extrasaction="raise")
            writer.writeheader()
            writer.writerows(rows)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def build_rows(payload: dict, window_seconds: int, jobs: dict, probes: dict) -> list[dict]:
    series_by_key = defaultdict(list)
    all_timestamps: list[float] = []
    observed_probes: set[str] = set()
    wildcard_probe_details = probes.get("*")
    for series in payload.get("data", {}).get("result", []):
        labels = series.get("metric", {})
        metric_name = labels.get("__name__")
        job = labels.get("job")
        probe = labels.get("probe")
        phase = labels.get("phase", "")
        if not metric_name or job not in jobs or not probe:
            continue
        if wildcard_probe_details is None and probe not in probes:
            continue
        parsed = []
        for timestamp_text, value_text in series.get("values", []):
            try:
                timestamp = float(timestamp_text)
                value = float(value_text)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(timestamp) or not math.isfinite(value):
                continue
            parsed.append((timestamp, value))
            all_timestamps.append(timestamp)
        series_by_key[(job, probe, metric_name, phase)].extend(parsed)
        observed_probes.add(probe)

    if not all_timestamps:
        raise FeatureError(EXIT_NO_DATA, "No supported probe samples were found.", "Check the selector, jobs, probes, and latest collection.")

    first_complete = math.ceil(min(all_timestamps) / window_seconds) * window_seconds
    last_complete = math.floor(max(all_timestamps) / window_seconds) * window_seconds
    windows = range(int(first_complete), int(last_complete), window_seconds)
    if not windows:
        raise FeatureError(EXIT_NO_DATA, "No complete feature window exists in the collection.", "Increase lookback or wait for a complete configured window.")

    def values(job, probe, metric_name, start, end, phase=""):
        return [value for timestamp, value in series_by_key[(job, probe, metric_name, phase)] if start <= timestamp < end]

    def samples(job, probe, metric_name, start, end, phase=""):
        return [(timestamp, value) for timestamp, value in series_by_key[(job, probe, metric_name, phase)] if start <= timestamp < end]

    active_probes = {name: details for name, details in probes.items() if name != "*"}
    if wildcard_probe_details is not None:
        for probe_name in observed_probes:
            active_probes.setdefault(probe_name, wildcard_probe_details)

    rows: list[dict] = []
    for start in windows:
        end = start + window_seconds
        for job, job_details in jobs.items():
            for probe, probe_details in active_probes.items():
                success_samples = samples(job, probe, "probe_success", start, end)
                successes = [value for _, value in success_samples]
                expected = window_seconds // job_details["frequency_seconds"]
                received = len(successes)
                status_codes = values(job, probe, "probe_http_status_code", start, end)
                # Use only an explicit timeout metric. Regex failures are not timeouts.
                timeout_values = values(job, probe, "probe_timeout", start, end)
                expiry = values(job, probe, "probe_ssl_earliest_cert_expiry", start, end)
                rows.append({
                    "window_start_utc": utc_string(start),
                    "window_end_utc": utc_string(end),
                    "target_id": job_details["target_id"],
                    "job": job,
                    "check_type": job_details["check_type"],
                    "probe": probe,
                    "probe_type": probe_details["probe_type"],
                    "probe_location": probe_details["probe_location"],
                    "probe_provider": probe_details["probe_provider"],
                    "success_rate": rounded(average(successes), 4),
                    "failure_count": sum(value < 0.5 for value in successes),
                    "consecutive_failure_max": longest_failure_sequence(success_samples),
                    "duration_avg_ms": milliseconds(values(job, probe, "probe_duration_seconds", start, end)),
                    "duration_p50_ms": milliseconds(values(job, probe, "probe_duration_seconds", start, end), lambda x: percentile(x, 0.50)),
                    "duration_p95_ms": milliseconds(values(job, probe, "probe_duration_seconds", start, end), lambda x: percentile(x, 0.95)),
                    "duration_p99_ms": milliseconds(values(job, probe, "probe_duration_seconds", start, end), lambda x: percentile(x, 0.99)),
                    "dns_lookup_avg_ms": milliseconds(values(job, probe, "probe_dns_lookup_time_seconds", start, end)),
                    "dns_lookup_p95_ms": milliseconds(values(job, probe, "probe_dns_lookup_time_seconds", start, end), lambda x: percentile(x, 0.95)),
                    "dns_resolve_avg_ms": milliseconds(values(job, probe, "probe_dns_duration_seconds", start, end, "resolve")),
                    "dns_connect_avg_ms": milliseconds(values(job, probe, "probe_dns_duration_seconds", start, end, "connect")),
                    "dns_request_avg_ms": milliseconds(values(job, probe, "probe_dns_duration_seconds", start, end, "request")),
                    "http_resolve_avg_ms": milliseconds(values(job, probe, "probe_http_duration_seconds", start, end, "resolve")),
                    "http_connect_avg_ms": milliseconds(values(job, probe, "probe_http_duration_seconds", start, end, "connect")),
                    "http_tls_avg_ms": milliseconds(values(job, probe, "probe_http_duration_seconds", start, end, "tls")),
                    "http_processing_avg_ms": milliseconds(values(job, probe, "probe_http_duration_seconds", start, end, "processing")),
                    "http_transfer_avg_ms": milliseconds(values(job, probe, "probe_http_duration_seconds", start, end, "transfer")),
                    "http_status_mode": mode_integer(status_codes),
                    "http_4xx_rate": rounded(average([400 <= value < 500 for value in status_codes]), 4),
                    "http_5xx_rate": rounded(average([500 <= value < 600 for value in status_codes]), 4),
                    "timeout_rate": rounded(average(timeout_values), 4),
                    "http_content_length_avg_bytes": rounded(average(values(job, probe, "probe_http_content_length", start, end)), 2),
                    "dns_answer_rrs_avg": rounded(average(values(job, probe, "probe_dns_answer_rrs", start, end)), 3),
                    "dns_authority_rrs_avg": rounded(average(values(job, probe, "probe_dns_authority_rrs", start, end)), 3),
                    "dns_additional_rrs_avg": rounded(average(values(job, probe, "probe_dns_additional_rrs", start, end)), 3),
                    "tls_days_remaining_min": rounded((min(expiry) - end) / 86400, 2) if expiry else "",
                    "samples_expected": expected,
                    "samples_received": received,
                    "missing_data_flag": int(received < expected),
                })
    rows.sort(key=lambda row: (row["window_start_utc"], row["target_id"], row["job"], row["probe"]))
    return rows


def update_history(history_file: Path, rows: list[dict]) -> list[dict]:
    history: dict[tuple[str, str, str, str], dict] = {}
    if history_file.exists():
        with history_file.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            if tuple(reader.fieldnames or ()) != COLUMNS:
                raise FeatureError(EXIT_CONFIG, "Existing history CSV schema does not match the 38-column contract.", "Back up the file and migrate it before continuing.")
            for row in reader:
                key = (row["window_start_utc"], row["target_id"], row["job"], row["probe"])
                history[key] = row
    for row in rows:
        key = (row["window_start_utc"], row["target_id"], row["job"], row["probe"])
        history[key] = row
    return sorted(history.values(), key=lambda row: (row["window_start_utc"], row["target_id"], row["job"], row["probe"]))


def run(arguments: argparse.Namespace) -> tuple[int, int]:
    environment = load_env_file(arguments.environment)
    feature_config_path = arguments.feature_config or Path(environment.get("FEATURE_CONFIG", str(DEFAULT_TARGETS)))
    data_root = Path(environment.get("DATA_ROOT", str(DEFAULT_DATA_ROOT)))
    window_seconds, jobs, probes = load_feature_config(feature_config_path)
    state_file = data_root / "state" / "last_collection.json"
    try:
        manifest = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FeatureError(EXIT_CONFIG, "Latest collection manifest is missing or invalid.", "Run a successful collection before feature generation.") from exc
    if manifest.get("status") != "success" or not manifest.get("prometheus_file"):
        raise FeatureError(EXIT_FEATURE, "Latest collection did not finish successfully.", "Fix collection and rerun the complete service.")
    try:
        with gzip.open(Path(manifest["prometheus_file"]), "rt", encoding="utf-8") as source:
            payload = json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise FeatureError(EXIT_FEATURE, "Latest Prometheus evidence is missing or invalid.", "Restore the raw snapshot or run collection again.") from exc

    rows = build_rows(payload, window_seconds, jobs, probes)
    feature_dir = data_root / "features"
    current_file = feature_dir / "probe_features_current.csv"
    history_file = feature_dir / "probe_features_history.csv"
    history_rows = update_history(history_file, rows)
    try:
        write_csv(current_file, rows)
        write_csv(history_file, history_rows)
    except OSError as exc:
        raise FeatureError(EXIT_LOCAL, "Cannot publish feature CSV files.", "Check ownership, free space, and filesystem health.") from exc
    print(f"[OK] ML features: current_rows={len(rows)} history_rows={len(history_rows)} columns={len(COLUMNS)}")
    print(f"[OK] Current CSV: {current_file}")
    print(f"[OK] History CSV: {history_file}")
    return len(rows), len(history_rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--feature-config", type=Path)
    return parser


def main() -> int:
    try:
        run(build_parser().parse_args())
        return 0
    except FeatureError as exc:
        print(f"[ERROR] code={exc.exit_code} cause={exc.cause} action={exc.action}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        print(f"[ERROR] code={EXIT_FEATURE} cause=Unexpected feature-build failure. action=Review the service journal. detail={type(exc).__name__}", file=sys.stderr)
        return EXIT_FEATURE


if __name__ == "__main__":
    raise SystemExit(main())
