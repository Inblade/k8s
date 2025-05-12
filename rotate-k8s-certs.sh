#!/bin/bash

set -euo pipefail

# === Config ===
THRESHOLD_DAYS=7
ADMIN_KUBECONFIG="/etc/kubernetes/admin.conf"
BACKUP_DIR="/var/backups/k8s-certs"
TMP_DIR="/tmp/k8s-rotate"
SLACK_WEBHOOK_URL="https://hooks.slack.com/services/XXX/YYY/ZZZ"  # <= ЗАМЕНИ НА СВОЙ
HOSTNAME="$(hostname)"
TIMESTAMP="$(date +%F-%H%M%S)"

# Ensure dirs exist
mkdir -p "$BACKUP_DIR" "$TMP_DIR"

# === Slack notify function ===
send_slack_notification() {
  local message="$1"
  curl -s -X POST --data-urlencode \
    "payload={\"text\": \"$message\"}" \
    "$SLACK_WEBHOOK_URL"
}

# === Check expiration ===
EXPIRED=false
echo "[INFO] Checking certificate expiration..."

kubeadm certs check-expiration > "$TMP_DIR/exp_check.txt"

if grep -q 'EXPIRES' "$TMP_DIR/exp_check.txt"; then
    while IFS= read -r line; do
        if [[ "$line" =~ ([A-Za-z0-9\._-]+)[[:space:]]+([A-Za-z]+[[:space:]][0-9]+,[[:space:]][0-9]+) ]]; then
            CERT_NAME="${BASH_REMATCH[1]}"
            EXPIRY_RAW="${BASH_REMATCH[2]}"
            EXPIRY_DATE=$(date -d "$EXPIRY_RAW" +%s)
            NOW_DATE=$(date +%s)
            DAYS_LEFT=$(( (EXPIRY_DATE - NOW_DATE) / 86400 ))

            if (( DAYS_LEFT < THRESHOLD_DAYS )); then
                echo "[WARN] Certificate $CERT_NAME expires in $DAYS_LEFT days!"
                EXPIRED=true
            fi
        fi
    done < <(grep 'EXPIRES' "$TMP_DIR/exp_check.txt")
fi

# === If expiring soon, renew ===
if $EXPIRED; then
    echo "[INFO] Rotating certificates..."
    kubeadm certs renew all

    # Backup and archive new admin.conf
    cp "$ADMIN_KUBECONFIG" "$BACKUP_DIR/admin.conf.bak-$TIMESTAMP"
    tar czf "$TMP_DIR/admin-conf-$TIMESTAMP.tar.gz" -C /etc/kubernetes admin.conf

    # Slack message
    send_slack_notification ":lock: *Kubernetes TLS certs rotated* on *$HOSTNAME* at *$TIMESTAMP*. `admin.conf` updated and backed up."

    # Restart kube components via container runtime
    echo "[INFO] Restarting static pod containers..."
    if command -v crictl &> /dev/null; then
        crictl ps -q | xargs -r crictl stop
    elif command -v docker &> /dev/null; then
        docker ps --filter "name=k8s_" -q | xargs -r docker restart
    elif systemctl is-active --quiet containerd; then
        systemctl restart kubelet
    else
        echo "[ERROR] Unknown container runtime"
        exit 1
    fi

    echo "[INFO] Done. Certificates renewed and containers restarted."
else
    echo "[OK] All certificates are valid for more than $THRESHOLD_DAYS days."
fi

rm -rf "$TMP_DIR"
