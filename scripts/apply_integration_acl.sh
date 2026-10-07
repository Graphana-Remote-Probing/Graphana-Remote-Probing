#!/usr/bin/env bash
# Reapply read-only access for the configured remote DDoS-ML integration user.
# Copyright © 2026 Ahmed Mekky. All rights reserved.

set -Eeuo pipefail

CONFIG_FILE=/etc/Graphana_Proping/integration-read-user
DATA_ROOT=/data/Graphana_Proping
FEATURE_DIR=$DATA_ROOT/features
EXPORT_FILE=$FEATURE_DIR/probe_features_current.csv

[[ -r "$CONFIG_FILE" ]] || { printf '[ERROR] integration username file is missing or unreadable: %s\n' "$CONFIG_FILE" >&2; exit 60; }
IFS= read -r integration_user < "$CONFIG_FILE"
[[ "$integration_user" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || { printf '[ERROR] invalid integration username in %s\n' "$CONFIG_FILE" >&2; exit 60; }
id "$integration_user" >/dev/null 2>&1 || { printf '[ERROR] configured integration user does not exist: %s\n' "$integration_user" >&2; exit 60; }
command -v setfacl >/dev/null 2>&1 || { printf '[ERROR] setfacl is unavailable; install the acl package\n' >&2; exit 60; }

# Directory execute permission allows traversal without granting directory listing.
setfacl -m "u:${integration_user}:--x" "$DATA_ROOT"
setfacl -m "u:${integration_user}:--x" "$FEATURE_DIR"

# The current feature export is readable but not writable. The history file is not granted here.
if [[ -e "$EXPORT_FILE" ]]; then
    setfacl -m "u:${integration_user}:r--" "$EXPORT_FILE"
fi

printf '[OK] persistent read-only ACL applied: user=%s file=%s\n' "$integration_user" "$EXPORT_FILE"
