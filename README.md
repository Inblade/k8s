# Kubernetes Certificate Auto-Rotation Script

This script checks the expiration dates of Kubernetes TLS certificates and automatically rotates them when they are about to expire (within 7 days). It supports:
- Auto-renewal via `kubeadm`
- Container runtime detection (`crictl`, `docker`, `containerd`)
- Notification via Slack
- Backup of `admin.conf`

---

## Installation

### 1. Save script

```bash
sudo curl -o /usr/local/bin/rotate-k8s-certs.sh https://your-repo-or-path/rotate-k8s-certs.sh
sudo chmod +x /usr/local/bin/rotate-k8s-certs.sh
```

# Setup Cron Job

```bash
sudo crontab -e
add --> 0 3 * * * /usr/local/bin/rotate-k8s-certs.sh >> /var/log/k8s-cert-rotation.log 2>&1
```

# Requirements
	•	kubeadm
	•	curl
	•	bash
	•	crictl, docker, or containerd
	•	Slack Webhook URL

 # Backups

```bash
 /var/backups/k8s-certs/
```
