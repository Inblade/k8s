#!/bin/bash
# Установка торгового бота на чистый Ubuntu/Debian сервер (Hetzner CX/CPX).
# Запускать НА СЕРВЕРЕ от root, из каталога /opt/trading-bot, куда предварительно
# синхронизирован код (см. deploy/sync-to-server.sh).
set -euo pipefail

DIR=/opt/trading-bot
cd "$DIR"

echo "==> apt: python venv/pip/git"
apt-get update -qq
apt-get install -y python3-venv python3-pip

echo "==> venv + зависимости"
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

if [ ! -f .env ]; then
  echo "!! .env не найден. Скопируй его с локальной машины (sync-to-server.sh) или создай из .env.example." >&2
fi

echo "==> systemd unit"
cp deploy/trading-bot.service /etc/systemd/system/trading-bot.service
systemctl daemon-reload
systemctl enable trading-bot

echo
echo "Готово. Дальше:"
echo "  systemctl start trading-bot         # запустить"
echo "  systemctl status trading-bot        # статус"
echo "  journalctl -u trading-bot -f        # логи systemd"
echo "  tail -f /opt/trading-bot/bot.log    # логи бота"
echo "  Дашборд: ssh -L 8000:localhost:8000 root@<IP>  затем http://localhost:8000"
