#!/usr/bin/env python3
"""Collect approved Grafana Cloud Prometheus metrics and Loki logs.

Copyright © 2026 Ahmed Mekky. All rights reserved.
Use, modification, and redistribution are governed by the LICENSE file.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import math
import os
import socket
import ssl
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


DEFAULT_CONFIG = Path("/etc/Graphana_Proping/cloud-read.env")
DEFAULT_TOKEN_FILE = Path("/etc/Graphana_Proping/cloud-read.token")
DEFAULT_DATA_ROOT = Path("/data/Graphana_Proping")

EXIT_CONFIG = 10
EXIT_NETWORK = 20
EXIT_TLS = 21
EXIT_AUTH = 30
EXIT_FORBIDDEN = 31
EXIT_EXPIRED = 32
EXIT_NO_DATA = 40
EXIT_COLLECTION = 50
EXIT_LOCAL = 60


@dataclass
class DiagnosticError(Exception):
    """A safe, actionable error that can be printed without leaking secrets."""

    exit_code: int
    cause: str
    action: str

    def __str__(self) -> str:
        return self.cause


def load_env_file(path: Path) -> dict[str, str]:
    """Read strict KEY=VALUE lines without executing shell code."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DiagnosticError(EXIT_CONFIG, f"Cannot read configuration: {path}", "Check file path and permissions.") from exc

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            raise DiagnosticError(
                EXIT_CONFIG,
                f"Invalid configuration line {line_number} in {path}",
                "Use one KEY=VALUE assignment per line.",
            )
        values[key.strip()] = value.strip()
    return values


def require_config(configuration: dict[str, str], names: tuple[str, ...]) -> None:
    """Require all listed configuration keys to contain values."""
    missing = [name for name in names if not configuration.get(name)]
    if missing:
        raise DiagnosticError(
            EXIT_CONFIG,
            "Missing configuration keys: " + ", ".join(missing),
            "Run the installer repair mode and supply the missing values.",
        )


def validate_https_url(value: str, label: str) -> str:
    """Require an HTTPS URL without embedded credentials."""
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise DiagnosticError(EXIT_CONFIG, f"{label} must be a complete HTTPS URL.", "Recopy the endpoint from Grafana Cloud.")
    if parsed.username or parsed.password:
        raise DiagnosticError(EXIT_CONFIG, f"{label} contains embedded credentials.", "Remove credentials from the URL.")
    if parsed.fragment:
        raise DiagnosticError(EXIT_CONFIG, f"{label} must not contain a fragment.", "Remove the URL fragment.")
    return value.rstrip("/")


def utc_text(value: datetime) -> str:
    """Return an RFC 3339 UTC timestamp."""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def basic_authorization(user: str, token: str) -> str:
    """Build an HTTP Basic authorization header in memory."""
    raw = f"{user}:{token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def check_token_expiry(configuration: dict[str, str], today: date | None = None) -> None:
    """Fail on recorded expiry and warn before it without inspecting the token."""
    expiry_text = configuration.get("TOKEN_EXPIRY_DATE", "none").strip().lower()
    if expiry_text in {"", "none", "no platform expiration"}:
        print("[OK] token_expiry=no-platform-expiration; organization rotation policy still applies")
        return
    try:
        expiry = date.fromisoformat(expiry_text)
    except ValueError as exc:
        raise DiagnosticError(EXIT_CONFIG, "TOKEN_EXPIRY_DATE is invalid.", "Use YYYY-MM-DD or none.") from exc

    current = today or datetime.now(timezone.utc).date()
    days_remaining = (expiry - current).days
    if days_remaining <= 0:
        raise DiagnosticError(EXIT_EXPIRED, f"Recorded token expiry reached: {expiry.isoformat()}", "Rotate the token and rerun preflight.")

    warning_days: list[int] = []
    for item in configuration.get("TOKEN_WARN_DAYS", "30,7").split(","):
        try:
            warning_days.append(int(item.strip()))
        except ValueError as exc:
            raise DiagnosticError(EXIT_CONFIG, "TOKEN_WARN_DAYS is invalid.", "Use comma-separated integers such as 30,7.") from exc
    if any(days_remaining <= threshold for threshold in warning_days):
        print(f"[WARNING] token expires in {days_remaining} day(s) on {expiry.isoformat()}; schedule rotation")
    else:
        print(f"[OK] token expires in {days_remaining} day(s) on {expiry.isoformat()}")


def _network_diagnostic(exc: BaseException, endpoint_name: str) -> DiagnosticError:
    """Map network exceptions to stable, operator-facing diagnostics."""
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, ssl.SSLCertVerificationError) or isinstance(exc, ssl.SSLError):
        return DiagnosticError(EXIT_TLS, f"TLS validation failed for {endpoint_name}.", "Check CA trust, hostname, interception proxy, and NTP.")
    if isinstance(reason, socket.gaierror):
        return DiagnosticError(EXIT_NETWORK, f"DNS resolution failed for {endpoint_name}.", "Check DNS and the configured endpoint hostname.")
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return DiagnosticError(EXIT_NETWORK, f"Connection timed out for {endpoint_name}.", "Check outbound TCP 443, firewall, route, and proxy settings.")
    return DiagnosticError(EXIT_NETWORK, f"Connection failed for {endpoint_name}.", "Check outbound TCP 443, firewall, route, proxy, and endpoint availability.")


def api_get(
    base_url: str,
    api_path: str,
    user: str,
    token: str,
    parameters: dict[str, str | int],
    endpoint_name: str,
    timeout: int,
) -> dict:
    """Call one Grafana query API and return only a successful JSON payload."""
    url = base_url.rstrip("/") + api_path + "?" + urllib.parse.urlencode(parameters)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": basic_authorization(user, token),
            "User-Agent": "Graphana_Proping/1.0.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise DiagnosticError(EXIT_AUTH, f"Authentication failed for {endpoint_name} (HTTP 401).", "Replace an invalid, revoked, or expired token and rerun preflight.") from exc
        if exc.code == 403:
            raise DiagnosticError(EXIT_FORBIDDEN, f"Authorization failed for {endpoint_name} (HTTP 403).", "Grant the required read scope or correct the source-IP restriction.") from exc
        if exc.code == 404:
            raise DiagnosticError(EXIT_CONFIG, f"Endpoint not found for {endpoint_name} (HTTP 404).", "Recopy the endpoint and stack region from Grafana Cloud.") from exc
        if exc.code == 429:
            raise DiagnosticError(EXIT_NETWORK, f"Rate or usage limit reached for {endpoint_name} (HTTP 429).", "Review Grafana usage and reduce request frequency before retrying.") from exc
        if 500 <= exc.code <= 599:
            raise DiagnosticError(EXIT_NETWORK, f"Grafana/provider error for {endpoint_name} (HTTP {exc.code}).", "Retry later with bounded backoff and check provider status.") from exc
        raise DiagnosticError(EXIT_COLLECTION, f"Unexpected HTTP {exc.code} from {endpoint_name}.", "Verify the endpoint and inspect provider status.") from exc
    except (urllib.error.URLError, ssl.SSLError, TimeoutError, socket.timeout) as exc:
        raise _network_diagnostic(exc, endpoint_name) from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DiagnosticError(EXIT_COLLECTION, f"Invalid JSON returned by {endpoint_name}.", "Verify the endpoint and retry after checking provider status.") from exc

    if payload.get("status") != "success":
        raise DiagnosticError(EXIT_COLLECTION, f"Grafana query status was not success for {endpoint_name}.", "Verify the query and provider service.")
    return payload


def atomic_json_gzip(path: Path, payload: dict) -> None:
    """Write compressed JSON durably and atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as raw_output:
            with gzip.GzipFile(fileobj=raw_output, mode="wb") as compressed:
                compressed.write(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
            raw_output.flush()
            os.fsync(raw_output.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def atomic_json(path: Path, payload: dict) -> None:
    """Write a JSON state file durably and atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def count_prometheus_samples(payload: dict) -> int:
    """Count actual samples returned inside all Prometheus range vectors."""
    return sum(len(series.get("values", [])) for series in payload.get("data", {}).get("result", []))


def count_loki_entries(payload: dict) -> int:
    """Count entries returned inside all Loki streams."""
    return sum(len(stream.get("values", [])) for stream in payload.get("data", {}).get("result", []))


def collect(arguments: argparse.Namespace) -> dict:
    """Validate configuration, query both APIs, and optionally publish evidence."""
    configuration = load_env_file(arguments.config)
    require_config(
        configuration,
        ("GRAFANA_PROM_URL", "GRAFANA_PROM_USER", "GRAFANA_LOKI_URL", "GRAFANA_LOKI_USER", "GRAFANA_SELECTOR"),
    )
    check_token_expiry(configuration)

    try:
        token = arguments.token_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise DiagnosticError(EXIT_CONFIG, f"Cannot read token file: {arguments.token_file}", "Check file path, ownership, and mode 0640.") from exc
    if not token:
        raise DiagnosticError(EXIT_CONFIG, "Token file is empty.", "Install a dedicated Grafana Cloud read token.")

    prom_url = validate_https_url(configuration["GRAFANA_PROM_URL"], "Prometheus URL")
    loki_url = validate_https_url(configuration["GRAFANA_LOKI_URL"], "Loki URL")
    timeout = int(configuration.get("HTTP_TIMEOUT_SECONDS", "30"))
    lookback_minutes = arguments.lookback_minutes or int(configuration.get("LOOKBACK_MINUTES", "30"))
    log_limit = arguments.log_limit or int(configuration.get("LOG_LIMIT", "5000"))
    if not 5 <= lookback_minutes <= 10080:
        raise DiagnosticError(EXIT_CONFIG, "Lookback must be between 5 and 10080 minutes.", "Correct LOOKBACK_MINUTES or the command option.")
    if not 1 <= timeout <= 300 or not 1 <= log_limit <= 50000:
        raise DiagnosticError(EXIT_CONFIG, "Timeout or log limit is outside the approved range.", "Use timeout 1-300 and log limit 1-50000.")

    end_time = datetime.now(timezone.utc).replace(microsecond=0)
    start_time = end_time - timedelta(minutes=lookback_minutes)
    selector = configuration["GRAFANA_SELECTOR"]

    prometheus = api_get(
        prom_url,
        "/api/v1/query",
        configuration["GRAFANA_PROM_USER"],
        token,
        {"query": f"{selector}[{lookback_minutes}m]", "time": utc_text(end_time)},
        "Prometheus",
        timeout,
    )
    loki = api_get(
        loki_url,
        "/loki/api/v1/query_range",
        configuration["GRAFANA_LOKI_USER"],
        token,
        {
            "query": selector,
            "start": str(math.floor(start_time.timestamp() * 1_000_000_000)),
            "end": str(math.floor(end_time.timestamp() * 1_000_000_000)),
            "direction": "forward",
            "limit": log_limit,
        },
        "Loki",
        timeout,
    )

    prom_results = prometheus.get("data", {}).get("result", [])
    loki_results = loki.get("data", {}).get("result", [])
    prom_samples = count_prometheus_samples(prometheus)
    loki_entries = count_loki_entries(loki)
    if not prom_results or not prom_samples:
        raise DiagnosticError(EXIT_NO_DATA, "Prometheus query succeeded but returned no approved samples.", "Check the job selector, time range, checks, and probe status.")
    if not loki_results or not loki_entries:
        raise DiagnosticError(EXIT_NO_DATA, "Loki query succeeded but returned no approved log entries.", "Check the job selector, time range, checks, and Loki publishing.")

    data_root = Path(configuration.get("DATA_ROOT", str(DEFAULT_DATA_ROOT)))
    manifest = {
        "schema_version": 1,
        "status": "success",
        "collected_at_utc": utc_text(end_time),
        "window_start_utc": utc_text(start_time),
        "window_end_utc": utc_text(end_time),
        "lookback_minutes": lookback_minutes,
        "prometheus_series": len(prom_results),
        "prometheus_samples": prom_samples,
        "loki_streams": len(loki_results),
        "loki_entries": loki_entries,
    }

    if not arguments.no_write:
        stamp = end_time.strftime("%Y%m%dT%H%M%SZ")
        suffix = f"{stamp}_lookback-{lookback_minutes}m.json.gz"
        prometheus_path = data_root / "raw" / "prometheus" / suffix
        loki_path = data_root / "raw" / "loki" / suffix
        manifest["prometheus_file"] = str(prometheus_path)
        manifest["loki_file"] = str(loki_path)
        try:
            atomic_json_gzip(prometheus_path, prometheus)
            atomic_json_gzip(loki_path, loki)
            atomic_json(data_root / "state" / "last_collection.json", manifest)
        except OSError as exc:
            raise DiagnosticError(EXIT_LOCAL, "Cannot publish local collection files.", "Check data-path ownership, free space, and filesystem health.") from exc

    print(f"[OK] Prometheus: series={manifest['prometheus_series']} samples={prom_samples}")
    print(f"[OK] Loki: streams={manifest['loki_streams']} entries={loki_entries}")
    print(f"[OK] Window: {manifest['window_start_utc']} to {manifest['window_end_utc']}")
    if arguments.preflight:
        print("[OK] preflight passed; endpoints, token, scopes, selector, and recent data are valid")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN_FILE)
    parser.add_argument("--lookback-minutes", type=int)
    parser.add_argument("--log-limit", type=int)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    return parser


def main() -> int:
    try:
        arguments = build_parser().parse_args()
        if arguments.preflight:
            arguments.no_write = True
        collect(arguments)
        return 0
    except DiagnosticError as exc:
        print(f"[ERROR] code={exc.exit_code} cause={exc.cause} action={exc.action}", file=sys.stderr)
        return exc.exit_code
    except (ValueError, KeyError) as exc:
        print(f"[ERROR] code={EXIT_CONFIG} cause=Invalid numeric or structured configuration. action=Run installer repair mode. detail={type(exc).__name__}", file=sys.stderr)
        return EXIT_CONFIG
    except Exception as exc:  # Keep unexpected failures visible but never print secret values.
        print(f"[ERROR] code={EXIT_COLLECTION} cause=Unexpected collector failure. action=Review the service journal. detail={type(exc).__name__}", file=sys.stderr)
        return EXIT_COLLECTION


if __name__ == "__main__":
    raise SystemExit(main())
