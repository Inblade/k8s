# k8s — TLS certificate auto-rotation for kubeadm clusters

A single-file Bash tool that keeps control-plane certificates on kubeadm-managed clusters from expiring silently — the classic "cluster suddenly unreachable after exactly one year" failure.

Run it from cron on each control-plane node. It checks expiry daily, and only when a certificate is close to expiring does it renew, back up, notify, and restart the affected components.

## What it does

1. **Check** — parses `kubeadm certs check-expiration`; any certificate with fewer than `THRESHOLD_DAYS` (default 7) days left triggers rotation.
2. **Renew** — `kubeadm certs renew all`.
3. **Back up** — copies the fresh `admin.conf` to `/var/backups/k8s-certs/` with a timestamp and keeps a tar.gz archive.
4. **Notify** — posts to a Slack webhook so the rotation never happens invisibly.
5. **Restart** — bounces the control-plane static pods so they pick up the new certs, auto-detecting the runtime: `crictl`, `docker`, or `containerd` (via kubelet restart).

If nothing is close to expiry, the script exits without touching anything.

## Install

```bash
sudo install -m 0755 rotate-k8s-certs.sh /usr/local/bin/rotate-k8s-certs.sh
# set your Slack webhook inside the script first
```

Schedule it daily at a quiet hour:

```cron
0 3 * * * /usr/local/bin/rotate-k8s-certs.sh >> /var/log/k8s-cert-rotation.log 2>&1
```

## Configuration

Edit the variables at the top of the script:

| Variable | Default | Meaning |
|---|---|---|
| `THRESHOLD_DAYS` | `7` | Rotate when any cert has fewer days left than this |
| `ADMIN_KUBECONFIG` | `/etc/kubernetes/admin.conf` | Kubeconfig to back up after renewal |
| `BACKUP_DIR` | `/var/backups/k8s-certs` | Where timestamped backups go |
| `SLACK_WEBHOOK_URL` | placeholder | Incoming webhook for notifications |

## Requirements

`kubeadm`, `bash`, `curl`, and one of `crictl` / `docker` / `containerd`. Must run as root on a control-plane node.

## Notes

- Renewal restarts control-plane containers — schedule it outside peak hours; on multi-master clusters stagger the cron across nodes.
- After rotation, distribute the refreshed `admin.conf` to whoever consumes it (CI, operators' kubeconfigs); backups in `BACKUP_DIR` keep the previous versions.
- `kubeadm certs renew` does not rotate kubelet client certs (kubelet handles its own rotation when `rotateCertificates: true`).
