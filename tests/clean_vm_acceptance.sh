#!/usr/bin/env bash
# Clean Ubuntu VM installation and acceptance test for Graphana_Proping.
# Copyright © 2026 Ahmed Mekky. All rights reserved.

set -Eeuo pipefail

PACKAGE_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
INSTALL_ROOT=/opt/Graphana_Proping
CONFIG_ROOT=/etc/Graphana_Proping
DATA_ROOT=/data/Graphana_Proping
STATE_ROOT=/var/lib/Graphana_Proping
SERVICE_USER=graphana-proping
SERVICE_GROUP=graphana-proping
SERVICE_NAME=graphana-proping-collector.service
TIMER_NAME=graphana-proping-collector.timer
ACL_SERVICE_NAME=graphana-proping-export-acl.service
ACL_PATH_NAME=graphana-proping-export-acl.path
REPORT_FILE="$STATE_ROOT/clean-vm-acceptance.txt"

ok() { printf '[OK] %s\n' "$*"; }
info() { printf '[INFO] %s\n' "$*"; }
die() { printf '[ERROR] %s\n' "$1" >&2; exit "${2:-60}"; }

on_error() {
    status=$?
    line=$1
    printf '[ERROR] clean-VM acceptance failed at line %s with status %s\n' "$line" "$status" >&2
    printf '[INFO] Review: sudo journalctl -u %s -n 100 --no-pager\n' "$SERVICE_NAME" >&2
    exit "$status"
}
trap 'on_error $LINENO' ERR

[[ $EUID -eq 0 ]] || die "Run with sudo: sudo bash tests/clean_vm_acceptance.sh" 10
[[ -r /etc/os-release ]] || die "Cannot identify the operating system." 10
# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || die "Acceptance testing supports Ubuntu only." 10
case "${VERSION_ID:-}" in
    22.04|24.04) ;;
    *) die "Supported Ubuntu versions are 22.04 and 24.04; found ${VERSION_ID:-unknown}." 10 ;;
esac
[[ -d /run/systemd/system ]] || die "systemd must be PID 1 on the clean VM." 10
[[ "$PACKAGE_ROOT" != "$INSTALL_ROOT" ]] || die "Run the source package from a temporary or home directory, not $INSTALL_ROOT." 10

existing=()
for path in \
    "$CONFIG_ROOT" \
    "$DATA_ROOT" \
    "$STATE_ROOT" \
    "/etc/systemd/system/$SERVICE_NAME" \
    "/etc/systemd/system/$TIMER_NAME" \
    "/etc/systemd/system/$ACL_SERVICE_NAME" \
    "/etc/systemd/system/$ACL_PATH_NAME"; do
    [[ -e "$path" ]] && existing+=("$path")
done
id "$SERVICE_USER" >/dev/null 2>&1 && existing+=("user:$SERVICE_USER")
if (( ${#existing[@]} > 0 )); then
    printf '[ERROR] This is not a clean Graphana_Proping VM. Existing items:\n' >&2
    printf '  - %s\n' "${existing[@]}" >&2
    die "Use a fresh Ubuntu VM or perform a separately approved uninstall; this test never deletes existing data." 60
fi
ok "clean baseline confirmed"

info "Validating the release package before installation."
bash -n "$PACKAGE_ROOT/install_Graphana_Proping.sh" "$PACKAGE_ROOT/scripts/health_check.sh" "$PACKAGE_ROOT/tests/clean_vm_acceptance.sh"
(cd "$PACKAGE_ROOT" && sha256sum -c release/SHA256SUMS.txt)
if command -v python3 >/dev/null 2>&1; then
    python3 -m json.tool "$PACKAGE_ROOT/config/targets.json" >/dev/null
    python3 -m json.tool "$PACKAGE_ROOT/tests/fixtures/synthetic_prometheus.json" >/dev/null
    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "$PACKAGE_ROOT/tests" -p 'test_*.py'
else
    info "Python validation is deferred; the installer will install Python before running it."
fi
ok "release package validation passed"

printf '\nThe installer questionnaire will start now.\n'
printf 'Prepare the Prometheus/Loki endpoints and usernames, dedicated read token,\n'
printf 'token expiry, approved HTTP/DNS job names, ML consumer group, and an existing\n'
printf 'unprivileged Linux username for the remote DDoS-ML SSH integration.\n\n'
bash "$PACKAGE_ROOT/install_Graphana_Proping.sh"

info "Running post-install acceptance checks."
python3 -m json.tool "$PACKAGE_ROOT/config/targets.json" >/dev/null
python3 -m json.tool "$PACKAGE_ROOT/tests/fixtures/synthetic_prometheus.json" >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "$PACKAGE_ROOT/tests" -p 'test_*.py'
id "$SERVICE_USER" >/dev/null 2>&1 || die "Service account was not created." 60
getent group "$SERVICE_GROUP" >/dev/null || die "Service group was not created." 60
[[ -x "$INSTALL_ROOT/src/collect_grafana.py" ]] || die "Installed collector is missing or not executable." 60
[[ -x "$INSTALL_ROOT/src/build_features.py" ]] || die "Installed feature builder is missing or not executable." 60
[[ -x "$INSTALL_ROOT/scripts/health_check.sh" ]] || die "Installed health check is missing or not executable." 60
[[ -x "$INSTALL_ROOT/scripts/apply_integration_acl.sh" ]] || die "Installed ACL helper is missing or not executable." 60
[[ "$(stat -c '%a' "$CONFIG_ROOT")" == "710" ]] || die "Configuration directory mode is not 0710." 60
[[ "$(stat -c '%a' "$CONFIG_ROOT/cloud-read.token")" == "640" ]] || die "Token file mode is not 0640." 60
[[ "$(stat -c '%U:%G' "$CONFIG_ROOT/cloud-read.token")" == "root:$SERVICE_GROUP" ]] || die "Token ownership is incorrect." 60

systemd-analyze verify "/etc/systemd/system/$SERVICE_NAME" "/etc/systemd/system/$TIMER_NAME" \
    "/etc/systemd/system/$ACL_SERVICE_NAME" "/etc/systemd/system/$ACL_PATH_NAME"
systemctl is-enabled --quiet "$TIMER_NAME" || die "Collector timer is not enabled." 60
systemctl is-active --quiet "$TIMER_NAME" || die "Collector timer is not active." 60
systemctl is-enabled --quiet "$ACL_PATH_NAME" || die "Persistent ACL watcher is not enabled." 60
systemctl is-active --quiet "$ACL_PATH_NAME" || die "Persistent ACL watcher is not active." 60
if systemctl is-failed --quiet "$SERVICE_NAME"; then
    die "Collector service is in a failed state." 50
fi

systemctl start "$SERVICE_NAME"
[[ "$(systemctl show -p Result --value "$SERVICE_NAME")" == "success" ]] || die "Repeated collector execution did not finish successfully." 50
"$INSTALL_ROOT/scripts/health_check.sh" --live

current_file="$DATA_ROOT/features/probe_features_current.csv"
history_file="$DATA_ROOT/features/probe_features_history.csv"
[[ -s "$current_file" ]] || die "Current feature CSV is missing or empty." 50
[[ -s "$history_file" ]] || die "History feature CSV is missing or empty." 50

integration_user=$(<"$CONFIG_ROOT/integration-read-user")
getent passwd "$integration_user" >/dev/null || die "Configured integration user no longer exists." 60
getfacl -cp "$DATA_ROOT" | grep -Fqx "user:$integration_user:--x" || die "Integration user lacks data-root traversal ACL." 60
getfacl -cp "$DATA_ROOT/features" | grep -Fqx "user:$integration_user:--x" || die "Integration user lacks feature-directory traversal ACL." 60
getfacl -cp "$current_file" | grep -Fqx "user:$integration_user:r--" || die "Integration user lacks current-CSV read ACL." 60
runuser -u "$integration_user" -- head -n 1 "$current_file" >/dev/null || die "Integration user cannot read the current CSV." 60
if runuser -u "$integration_user" -- test -w "$current_file"; then
    die "Integration user unexpectedly has write access to the current CSV." 60
fi

read -r column_count current_rows history_rows < <(python3 - "$current_file" "$history_file" <<'PY'
import csv
import sys
from pathlib import Path

def dimensions(name):
    with Path(name).open(newline="", encoding="utf-8") as source:
        reader = csv.reader(source)
        header = next(reader)
        rows = sum(1 for _ in reader)
    return len(header), rows

current_columns, current_rows = dimensions(sys.argv[1])
history_columns, history_rows = dimensions(sys.argv[2])
if current_columns != history_columns:
    raise SystemExit("CSV schemas differ")
print(current_columns, current_rows, history_rows)
PY
)
[[ "$column_count" == "38" ]] || die "Feature CSV contract has $column_count columns instead of 38." 50
(( current_rows > 0 && history_rows > 0 )) || die "Feature CSV files contain no data rows." 50

accepted_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
install -d -o root -g "$SERVICE_GROUP" -m 0750 "$STATE_ROOT"
printf '%s\n' \
    "product=Graphana_Proping" \
    "version=$(tr -d '[:space:]' < "$PACKAGE_ROOT/VERSION")" \
    "accepted_at_utc=$accepted_at" \
    "ubuntu_version=${VERSION_ID:-unknown}" \
    "package_integrity=passed" \
    "installer=passed" \
    "live_preflight=passed" \
    "repeated_collection=passed" \
    "timer_enabled=passed" \
    "timer_active=passed" \
    "permissions=passed" \
    "persistent_integration_acl=passed" \
    "feature_columns=$column_count" \
    "current_rows=$current_rows" \
    "history_rows=$history_rows" \
    "overall=PASS" > "$REPORT_FILE"
chown root:"$SERVICE_GROUP" "$REPORT_FILE"
chmod 0640 "$REPORT_FILE"

ok "clean Ubuntu VM installation acceptance PASSED"
printf 'Sanitized evidence: %s\n' "$REPORT_FILE"
printf 'Timer schedule:\n'
systemctl list-timers "$TIMER_NAME" --no-pager
