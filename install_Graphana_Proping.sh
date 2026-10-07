#!/usr/bin/env bash
# Install the Graphana_Proping collector/staging layer only.
# Copyright © 2026 Ahmed Mekky. All rights reserved.

set -Eeuo pipefail

PACKAGE_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
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
INTEGRATION_USER_FILE=$CONFIG_ROOT/integration-read-user
ADVANCED=0
TIMER_ENABLED=0
ACL_WATCHER_ENABLED=0
TEMP_ROOT=""

usage() {
    printf 'Usage: sudo bash %s [--advanced]\n' "$(basename "$0")"
}

if [[ "${1:-}" == "--advanced" ]]; then
    ADVANCED=1
elif [[ -n "${1:-}" ]]; then
    usage >&2
    exit 10
fi

cleanup() {
    if [[ -n "$TEMP_ROOT" && -d "$TEMP_ROOT" ]]; then
        rm -rf -- "$TEMP_ROOT"
    fi
}

fail_trap() {
    status=$?
    line=$1
    if (( TIMER_ENABLED == 1 )); then
        systemctl disable --now "$TIMER_NAME" >/dev/null 2>&1 || true
    fi
    if (( ACL_WATCHER_ENABLED == 1 )); then
        systemctl disable --now "$ACL_PATH_NAME" >/dev/null 2>&1 || true
    fi
    printf '[ERROR] installation failed at line %s with status %s; the timer was not left enabled\n' "$line" "$status" >&2
    exit "$status"
}

trap cleanup EXIT
trap 'fail_trap $LINENO' ERR

ok() { printf '[OK] %s\n' "$*"; }
info() { printf '[INFO] %s\n' "$*"; }
die() { printf '[ERROR] %s\n' "$1" >&2; exit "${2:-10}"; }

[[ $EUID -eq 0 ]] || die "Run with sudo: sudo bash $(basename "$0")" 10
[[ -r /etc/os-release ]] || die "Cannot identify the operating system." 10
# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || die "This release candidate supports Ubuntu only." 10
case "${VERSION_ID:-}" in
    22.04|24.04) ;;
    *) die "Supported Ubuntu versions are 22.04 and 24.04; found ${VERSION_ID:-unknown}." 10 ;;
esac
[[ -d /run/systemd/system ]] || die "systemd is required and must be PID 1." 10

prompt_required() {
    local variable_name=$1
    local prompt_text=$2
    local value=""
    while [[ -z "$value" ]]; do
        read -r -p "$prompt_text: " value
    done
    printf -v "$variable_name" '%s' "$value"
}

printf '\nGraphana_Proping 1.0.0 staging-only installer\n'
printf 'No Grafana probe, Docker container, GUI, database, or ML model will be installed.\n\n'
printf 'Before setup begins, the installer will request:\n'
printf '  - Grafana Prometheus and Loki query URLs and usernames\n'
printf '  - one dedicated read token and its recorded expiry date\n'
printf '  - approved HTTP and DNS Synthetic Monitoring job names\n'
printf '  - the Unix group allowed to read the staged ML feature files\n'
printf '  - an existing unprivileged Linux username used by the remote DDoS-ML SSH integration\n\n'

prompt_required prom_url "1/10 Grafana Prometheus query URL"
prompt_required prom_user "2/10 Prometheus username or instance ID"
prompt_required loki_url "3/10 Grafana Loki query URL"
prompt_required loki_user "4/10 Loki username or instance ID"

token=""
while [[ -z "$token" ]]; do
    read -r -s -p "5/10 Dedicated Grafana Cloud read token (hidden): " token
    printf '\n'
done

read -r -p "6/10 Token expiry date YYYY-MM-DD, or none [none]: " token_expiry
token_expiry=${token_expiry:-none}
if [[ "$token_expiry" != "none" ]]; then
    date -u -d "$token_expiry" +%F >/dev/null 2>&1 || die "Token expiry must be YYYY-MM-DD or none." 10
fi

prompt_required http_job "7/10 Approved Grafana HTTP job name"
prompt_required dns_job "8/10 Approved Grafana DNS job name"
[[ "$http_job" =~ ^[A-Za-z0-9_-]+$ ]] || die "HTTP job name may contain only letters, numbers, underscores, and hyphens." 10
[[ "$dns_job" =~ ^[A-Za-z0-9_-]+$ ]] || die "DNS job name may contain only letters, numbers, underscores, and hyphens." 10
[[ "$http_job" != "$dns_job" ]] || die "HTTP and DNS job names must be different." 10

read -r -p "9/10 DDoS-ML consumer Unix group [ddos-ml-readers]: " consumer_group
consumer_group=${consumer_group:-ddos-ml-readers}
[[ "$consumer_group" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || die "Consumer group name is invalid." 10

prompt_required integration_user "10/10 Existing remote-integration Linux username (for example, tempadmin)"
[[ "$integration_user" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || die "Remote-integration username is invalid." 10
getent passwd "$integration_user" >/dev/null || die "Remote-integration user '$integration_user' does not exist. Create the account first, then rerun the installer." 10
[[ "$integration_user" != "root" ]] || die "The remote-integration account must be unprivileged; root is not allowed." 10
[[ "$integration_user" != "$SERVICE_USER" ]] || die "The collector service account cannot be used for remote SSH integration." 10

selector="{job=~\"^(${http_job}|${dns_job})$\"}"
lookback_minutes=30
timer_minutes=5
window_seconds=600
http_frequency=120
dns_frequency=600

if (( ADVANCED == 1 )); then
    info "Advanced configuration selected. Press Enter to keep each approved default."
    read -r -p "Approved Grafana selector [$selector]: " answer
    selector=${answer:-$selector}
    read -r -p "Collector lookback minutes [$lookback_minutes]: " answer
    lookback_minutes=${answer:-$lookback_minutes}
    read -r -p "Collector timer minutes [$timer_minutes]: " answer
    timer_minutes=${answer:-$timer_minutes}
    read -r -p "Feature window seconds [$window_seconds]: " answer
    window_seconds=${answer:-$window_seconds}
    read -r -p "HTTP check frequency seconds [$http_frequency]: " answer
    http_frequency=${answer:-$http_frequency}
    read -r -p "DNS check frequency seconds [$dns_frequency]: " answer
    dns_frequency=${answer:-$dns_frequency}
fi

for number in "$lookback_minutes" "$timer_minutes" "$window_seconds" "$http_frequency" "$dns_frequency"; do
    [[ "$number" =~ ^[1-9][0-9]*$ ]] || die "Advanced timing values must be positive integers." 10
done
(( window_seconds % http_frequency == 0 )) || die "Feature window must be divisible by the HTTP frequency." 10
(( window_seconds % dns_frequency == 0 )) || die "Feature window must be divisible by the DNS frequency." 10
(( lookback_minutes * 60 >= window_seconds * 2 )) || die "Lookback must cover at least two feature windows." 10

printf '\nConfiguration summary\n'
printf '  Prometheus URL: %s\n' "$prom_url"
printf '  Prometheus user: %s\n' "$prom_user"
printf '  Loki URL: %s\n' "$loki_url"
printf '  Loki user: %s\n' "$loki_user"
printf '  Token: [REDACTED]\n'
printf '  Token expiry: %s\n' "$token_expiry"
printf '  HTTP/DNS jobs: %s | %s\n' "$http_job" "$dns_job"
printf '  Selector: %s\n' "$selector"
printf '  Collector timer/lookback: %sm / %sm\n' "$timer_minutes" "$lookback_minutes"
printf '  Feature window: %ss; HTTP/DNS frequencies: %ss/%ss\n' "$window_seconds" "$http_frequency" "$dns_frequency"
printf '  Install/config/data: %s | %s | %s\n' "$INSTALL_ROOT" "$CONFIG_ROOT" "$DATA_ROOT"
printf '  Service/consumer groups: %s | %s\n' "$SERVICE_GROUP" "$consumer_group"
printf '  Remote integration user: %s (read-only current CSV; no password requested or stored)\n' "$integration_user"
read -r -p "Proceed with prerequisite installation, live preflight, and setup? [y/N]: " confirmation
[[ "$confirmation" =~ ^[Yy]$ ]] || die "Installation cancelled before system changes." 10

TEMP_ROOT=$(mktemp -d)
chmod 0700 "$TEMP_ROOT"
temp_env="$TEMP_ROOT/cloud-read.env"
temp_token="$TEMP_ROOT/cloud-read.token"
temp_targets="$TEMP_ROOT/targets.json"
temp_integration_user="$TEMP_ROOT/integration-read-user"

missing_packages=()
for package_name in python3 ca-certificates acl; do
    if ! dpkg-query -W -f='${Status}' "$package_name" 2>/dev/null | grep -qx 'install ok installed'; then
        missing_packages+=("$package_name")
    fi
done
if (( ${#missing_packages[@]} > 0 )); then
    info "Installing required Ubuntu packages: ${missing_packages[*]}"
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${missing_packages[@]}"
fi
command -v python3 >/dev/null 2>&1 || die "Python 3 is unavailable after prerequisite installation." 10
command -v setfacl >/dev/null 2>&1 || die "The acl package did not provide setfacl." 10

PYTHONPYCACHEPREFIX="$TEMP_ROOT/pycache" python3 -m py_compile \
    "$PACKAGE_ROOT/src/collect_grafana.py" "$PACKAGE_ROOT/src/build_features.py"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "$PACKAGE_ROOT/tests" -p 'test_*.py'
ok "package syntax and unit tests passed"

umask 077
printf '%s\n' \
    "GRAFANA_PROM_URL=$prom_url" \
    "GRAFANA_PROM_USER=$prom_user" \
    "GRAFANA_LOKI_URL=$loki_url" \
    "GRAFANA_LOKI_USER=$loki_user" \
    "GRAFANA_SELECTOR=$selector" \
    "DATA_ROOT=$DATA_ROOT" \
    "FEATURE_CONFIG=$CONFIG_ROOT/targets.json" \
    "TOKEN_EXPIRY_DATE=$token_expiry" \
    "TOKEN_WARN_DAYS=30,7" \
    "HTTP_TIMEOUT_SECONDS=30" \
    "LOOKBACK_MINUTES=$lookback_minutes" \
    "LOG_LIMIT=5000" > "$temp_env"
printf '%s\n' "$token" > "$temp_token"
unset token
printf '%s\n' "$integration_user" > "$temp_integration_user"

printf '%s\n' \
    '{' \
    '  "schema_version": 1,' \
    "  \"window_seconds\": $window_seconds," \
    '  "jobs": {' \
    "    \"$http_job\": {" \
    "      \"target_id\": \"monitored_service\", \"check_type\": \"http\", \"frequency_seconds\": $http_frequency" \
    '    },' \
    "    \"$dns_job\": {" \
    "      \"target_id\": \"monitored_service\", \"check_type\": \"dns\", \"frequency_seconds\": $dns_frequency" \
    '    }' \
    '  },' \
    '  "probes": {' \
    '    "*": {"probe_type": "unclassified", "probe_location": "not-configured", "probe_provider": "not-configured"}' \
    '  }' \
    '}' > "$temp_targets"

python3 -m json.tool "$temp_targets" >/dev/null

info "Running fail-closed Grafana integration preflight before installation."
python3 "$PACKAGE_ROOT/src/collect_grafana.py" \
    --config "$temp_env" \
    --token-file "$temp_token" \
    --lookback-minutes "$lookback_minutes" \
    --preflight --no-write
ok "Grafana endpoints, token, scopes, selector, and recent data passed preflight"

if ! getent group "$SERVICE_GROUP" >/dev/null; then
    groupadd --system "$SERVICE_GROUP"
fi
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --gid "$SERVICE_GROUP" --home-dir "$STATE_ROOT" --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi
if ! getent group "$consumer_group" >/dev/null; then
    groupadd --system "$consumer_group"
fi
usermod -a -G "$consumer_group" "$SERVICE_USER"

install -d -o root -g "$SERVICE_GROUP" -m 0750 "$INSTALL_ROOT" "$INSTALL_ROOT/src" "$INSTALL_ROOT/scripts"
install -d -o root -g "$SERVICE_GROUP" -m 0710 "$CONFIG_ROOT"
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0750 "$DATA_ROOT"
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0750 "$DATA_ROOT/raw/prometheus" "$DATA_ROOT/raw/loki" "$DATA_ROOT/state"
install -d -o "$SERVICE_USER" -g "$consumer_group" -m 2750 "$DATA_ROOT/features"
install -d -o root -g "$SERVICE_GROUP" -m 0750 "$STATE_ROOT"

install -o root -g "$SERVICE_GROUP" -m 0750 "$PACKAGE_ROOT/src/collect_grafana.py" "$INSTALL_ROOT/src/collect_grafana.py"
install -o root -g "$SERVICE_GROUP" -m 0750 "$PACKAGE_ROOT/src/build_features.py" "$INSTALL_ROOT/src/build_features.py"
install -o root -g "$SERVICE_GROUP" -m 0750 "$PACKAGE_ROOT/scripts/health_check.sh" "$INSTALL_ROOT/scripts/health_check.sh"
install -o root -g "$SERVICE_GROUP" -m 0750 "$PACKAGE_ROOT/scripts/apply_integration_acl.sh" "$INSTALL_ROOT/scripts/apply_integration_acl.sh"
install -o root -g "$SERVICE_GROUP" -m 0640 "$temp_env" "$CONFIG_ROOT/cloud-read.env"
install -o root -g "$SERVICE_GROUP" -m 0640 "$temp_token" "$CONFIG_ROOT/cloud-read.token"
install -o root -g "$SERVICE_GROUP" -m 0640 "$temp_targets" "$CONFIG_ROOT/targets.json"
install -o root -g "$SERVICE_GROUP" -m 0640 "$temp_integration_user" "$INTEGRATION_USER_FILE"

service_temp="$TEMP_ROOT/$SERVICE_NAME"
timer_temp="$TEMP_ROOT/$TIMER_NAME"
sed "s/--lookback-minutes 30/--lookback-minutes $lookback_minutes/" "$PACKAGE_ROOT/systemd/$SERVICE_NAME" > "$service_temp"
sed "s/OnCalendar=\*:0\/5/OnCalendar=*:0\/$timer_minutes/" "$PACKAGE_ROOT/systemd/$TIMER_NAME" > "$timer_temp"
install -o root -g root -m 0644 "$service_temp" "/etc/systemd/system/$SERVICE_NAME"
install -o root -g root -m 0644 "$timer_temp" "/etc/systemd/system/$TIMER_NAME"
install -o root -g root -m 0644 "$PACKAGE_ROOT/systemd/$ACL_SERVICE_NAME" "/etc/systemd/system/$ACL_SERVICE_NAME"
install -o root -g root -m 0644 "$PACKAGE_ROOT/systemd/$ACL_PATH_NAME" "/etc/systemd/system/$ACL_PATH_NAME"

python3 -m py_compile "$INSTALL_ROOT/src/collect_grafana.py" "$INSTALL_ROOT/src/build_features.py"
systemd-analyze verify "/etc/systemd/system/$SERVICE_NAME" "/etc/systemd/system/$TIMER_NAME" \
    "/etc/systemd/system/$ACL_SERVICE_NAME" "/etc/systemd/system/$ACL_PATH_NAME"
systemctl daemon-reload

info "Running the first collection and feature build."
systemctl start "$SERVICE_NAME"
systemctl is-failed --quiet "$SERVICE_NAME" && die "First collection failed. Review: journalctl -u $SERVICE_NAME -n 80 --no-pager" 50

current_file="$DATA_ROOT/features/probe_features_current.csv"
history_file="$DATA_ROOT/features/probe_features_history.csv"
[[ -s "$current_file" && -s "$history_file" ]] || die "Feature files were not created." 50
chown "$SERVICE_USER:$consumer_group" "$current_file" "$history_file"
chmod 0640 "$current_file" "$history_file"
systemctl start "$ACL_SERVICE_NAME"
systemctl enable --now "$ACL_PATH_NAME"
ACL_WATCHER_ENABLED=1

systemctl enable --now "$TIMER_NAME"
TIMER_ENABLED=1
"$INSTALL_ROOT/scripts/health_check.sh" --live

report="$STATE_ROOT/install-report.txt"
installed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
printf '%s\n' \
    "product=Graphana_Proping" \
    "version=1.0.0" \
    "installed_at_utc=$installed_at" \
    "ubuntu_version=${VERSION_ID:-unknown}" \
    "install_root=$INSTALL_ROOT" \
    "config_root=$CONFIG_ROOT" \
    "data_root=$DATA_ROOT" \
    "service=$SERVICE_NAME" \
    "timer=$TIMER_NAME" \
    "timer_minutes=$timer_minutes" \
    "lookback_minutes=$lookback_minutes" \
    "window_seconds=$window_seconds" \
    "token_expiry=$token_expiry" \
    "consumer_group=$consumer_group" \
    "integration_user=$integration_user" \
    "integration_access=read-only-current-csv" \
    "integration_acl_watcher=$ACL_PATH_NAME" \
    "preflight=passed" \
    "first_collection=passed" > "$report"
chown root:"$SERVICE_GROUP" "$report"
chmod 0640 "$report"

ok "Graphana_Proping installation completed"
printf 'Health check: sudo %s/scripts/health_check.sh --live\n' "$INSTALL_ROOT"
printf 'Service logs: sudo journalctl -u %s -n 80 --no-pager\n' "$SERVICE_NAME"
printf 'Feature files: %s/features/\n' "$DATA_ROOT"
printf 'Remote integration access: user=%s file=%s (read-only, persistent ACL watcher enabled)\n' "$integration_user" "$current_file"
