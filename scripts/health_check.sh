#!/usr/bin/env bash
# Copyright © 2026 Ahmed Mekky. All rights reserved.
# Use, modification, and redistribution are governed by the LICENSE file.

set -u

CONFIG_FILE="${GRAPHANA_PROPING_CONFIG:-/etc/Graphana_Proping/cloud-read.env}"
TOKEN_FILE="${GRAPHANA_PROPING_TOKEN:-/etc/Graphana_Proping/cloud-read.token}"
COLLECTOR="${GRAPHANA_PROPING_COLLECTOR:-/opt/Graphana_Proping/src/collect_grafana.py}"
FEATURE_BUILDER="${GRAPHANA_PROPING_FEATURE_BUILDER:-/opt/Graphana_Proping/src/build_features.py}"
INTEGRATION_USER_FILE="${GRAPHANA_PROPING_INTEGRATION_USER_FILE:-/etc/Graphana_Proping/integration-read-user}"
LIVE_CHECK=0
STATUS=0

if [[ "${1:-}" == "--live" ]]; then
    LIVE_CHECK=1
elif [[ -n "${1:-}" ]]; then
    echo "Usage: $0 [--live]" >&2
    exit 10
fi

ok() { printf '[OK] %s\n' "$*"; }
warning() { printf '[WARNING] %s\n' "$*"; }
error() {
    local message=$1
    local code=${2:-60}
    printf '[ERROR] %s\n' "$message" >&2
    if (( STATUS == 0 )); then
        STATUS=$code
    fi
}

if [[ ! -r "$CONFIG_FILE" ]]; then
    error "code=10 configuration is not readable: $CONFIG_FILE" 10
fi
if [[ ! -r "$TOKEN_FILE" ]]; then
    error "code=10 token file is not readable: $TOKEN_FILE" 10
fi
if [[ ! -r "$COLLECTOR" || ! -r "$FEATURE_BUILDER" ]]; then
    error "code=60 installed Python source is missing or unreadable" 60
fi
if (( STATUS != 0 )); then
    exit "$STATUS"
fi

if python3 -m py_compile "$COLLECTOR" "$FEATURE_BUILDER"; then
    ok "Python syntax validation passed"
else
    error "code=50 Python syntax validation failed" 50
fi

token_mode=$(stat -c '%a' "$TOKEN_FILE" 2>/dev/null || true)
if [[ "$token_mode" == "640" ]]; then
    ok "token file has required mode=640"
else
    error "code=60 token file permissions are unsafe or unreadable (mode=${token_mode:-unknown})" 60
fi

data_root=$(awk -F= '$1=="DATA_ROOT" {sub(/^[^=]*=/, ""); print; exit}' "$CONFIG_FILE")
expiry=$(awk -F= '$1=="TOKEN_EXPIRY_DATE" {sub(/^[^=]*=/, ""); print; exit}' "$CONFIG_FILE")
data_root="${data_root:-/data/Graphana_Proping}"
expiry="${expiry:-none}"

if [[ "$expiry" == "none" || "$expiry" == "no platform expiration" ]]; then
    ok "token has no recorded platform expiration; organization rotation still applies"
elif expiry_epoch=$(date -u -d "$expiry" +%s 2>/dev/null); then
    today_epoch=$(date -u -d "$(date -u +%F)" +%s)
    days_remaining=$(( (expiry_epoch - today_epoch) / 86400 ))
    if (( days_remaining <= 0 )); then
        error "code=32 recorded token expiry reached ($expiry); rotate token" 32
    elif (( days_remaining <= 7 )); then
        warning "token expires in $days_remaining day(s) on $expiry; rotate now"
    elif (( days_remaining <= 30 )); then
        warning "token expires in $days_remaining day(s) on $expiry; schedule rotation"
    else
        ok "token expiry metadata is valid ($days_remaining days remaining)"
    fi
else
    error "code=10 TOKEN_EXPIRY_DATE is invalid; use YYYY-MM-DD or none" 10
fi

if command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; then
    if systemctl is-enabled --quiet graphana-proping-collector.timer; then
        ok "collector timer is enabled"
    else
        error "code=60 collector timer is not enabled" 60
    fi
    if systemctl is-active --quiet graphana-proping-collector.timer; then
        ok "collector timer is active"
    else
        error "code=60 collector timer is not active" 60
    fi
    if systemctl is-enabled --quiet graphana-proping-export-acl.path; then
        ok "persistent integration ACL watcher is enabled"
    else
        error "code=60 persistent integration ACL watcher is not enabled" 60
    fi
    if systemctl is-active --quiet graphana-proping-export-acl.path; then
        ok "persistent integration ACL watcher is active"
    else
        error "code=60 persistent integration ACL watcher is not active" 60
    fi
else
    warning "systemd is unavailable in this environment; timer state was not checked"
fi

current_file="$data_root/features/probe_features_current.csv"
history_file="$data_root/features/probe_features_history.csv"
now_epoch=$(date +%s)
for file in "$current_file" "$history_file"; do
    if [[ ! -s "$file" ]]; then
        error "code=60 missing or empty feature file: $file" 60
        continue
    fi
    modified_epoch=$(stat -c '%Y' "$file")
    age_minutes=$(( (now_epoch - modified_epoch) / 60 ))
    if (( age_minutes > 15 )); then
        error "code=60 feature file is stale (${age_minutes}m): $file" 60
    else
        ok "feature file present age=${age_minutes}m path=$file"
    fi
done

if [[ ! -r "$INTEGRATION_USER_FILE" ]]; then
    error "code=60 integration username file is missing or unreadable: $INTEGRATION_USER_FILE" 60
else
    IFS= read -r integration_user < "$INTEGRATION_USER_FILE"
    if ! id "$integration_user" >/dev/null 2>&1; then
        error "code=60 configured integration user does not exist: $integration_user" 60
    elif ! command -v getfacl >/dev/null 2>&1; then
        error "code=60 getfacl is unavailable; install the acl package" 60
    elif ! getfacl -cp "$data_root" 2>/dev/null | grep -Fqx "user:$integration_user:--x"; then
        error "code=60 integration user lacks traversal ACL on $data_root" 60
    elif ! getfacl -cp "$data_root/features" 2>/dev/null | grep -Fqx "user:$integration_user:--x"; then
        error "code=60 integration user lacks traversal ACL on $data_root/features" 60
    elif ! getfacl -cp "$current_file" 2>/dev/null | grep -Fqx "user:$integration_user:r--"; then
        error "code=60 integration user lacks read-only ACL on $current_file" 60
    elif ! runuser -u "$integration_user" -- head -n 1 "$current_file" >/dev/null 2>&1; then
        error "code=60 integration user cannot read $current_file" 60
    elif runuser -u "$integration_user" -- test -w "$current_file"; then
        error "code=60 integration user unexpectedly has write access to $current_file" 60
    else
        ok "remote integration user has persistent read-only current-CSV access"
    fi
fi

if (( LIVE_CHECK == 1 )); then
    "$COLLECTOR" --config "$CONFIG_FILE" --token-file "$TOKEN_FILE" --preflight --no-write
    live_status=$?
    if (( live_status == 0 )); then
        ok "live Grafana integration preflight passed"
    else
        STATUS=$live_status
    fi
fi

if (( STATUS == 0 )); then
    ok "Graphana_Proping health check passed"
else
    printf '[ERROR] health check failed with code=%s\n' "$STATUS" >&2
fi
exit "$STATUS"
