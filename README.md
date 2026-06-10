# Kochetova Watercolour — website

Static website for artist **Julia Kochetova** and the **Step by Step**
international contemporary watercolour project (a clean, maintainable rebuild
of `jkochetova.com`).

## Editing the site
**You do not need to know how to code.** Just tell Claude in chat what you want
changed. Full plain-language guide (in Russian):
**[`КАК-РЕДАКТИРОВАТЬ-САЙТ.md`](./КАК-РЕДАКТИРОВАТЬ-САЙТ.md)**.

## How it's built
- Plain HTML + CSS + a tiny bit of JavaScript — **no build step**, nothing to install.
- Each page is one `.html` file. The whole look (colours, fonts) lives in
  `assets/css/style.css`.
- Photos go in `assets/images/`.

## Pages (match the original site menu)
| Page | File |
|------|------|
| Home | `index.html` |
| About | `about.html` |
| Step by Step | `step-by-step.html` |
| — How to apply | `how-to-apply.html` |
| — Jury | `jury.html` |
| — Programme | `programme.html` |
| — Past winners | `past-winners.html` |
| — Festival 2024 | `festival.html` |
| Blog | `blog.html` |
| Works | `works.html` |
| Projects | `projects.html` |
| — IWET · Our Wonderful World | `project-iwet.html` |
| — Christmas Light | `project-christmas-light.html` |
| — Gold Edition | `gold-edition.html` |
| Contact | `contact.html` |

The look (paper `#faf7f2`, slate `#31312f`, teal `#2e6e8e`, script logo, Cormorant
Garamond + Inter fonts) is taken from the original jkochetova.com and lives in
`assets/css/style.css`. Real homepage text and the portrait photo are already in
place; pages marked with a yellow `ЗАМЕНИТЬ` tag still need their content.

## Hosting (free)
The site is ready for **GitHub Pages**. Enable it once under
*Settings → Pages → Deploy from a branch*. Step-by-step instructions (incl.
connecting the `jkochetova.com` domain) are in the editing guide above.

> ℹ️ The real texts and photos still need to be filled in — every spot marked
> with a yellow `ЗАМЕНИТЬ` tag. Send them to Claude in chat and they'll be
> placed for you. (The live Wix site could not be auto-copied from the build
> environment — Wix blocks automated access — so the content is added manually.)

---

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
