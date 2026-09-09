#!/bin/bash
# Синхронизация бота с локальной машины на сервер по ssh (rsync).
# Тащит код + .env (ключи Binance идут по шифрованному ssh, не через git).
# НЕ тащит: venv, кэш, логи, локальное состояние (на сервере состояние своё).
#
# Использование:
#   ./deploy/sync-to-server.sh root@138.199.235.135
set -euo pipefail

TARGET="${1:?Укажи цель: ./deploy/sync-to-server.sh root@<IP>}"
DEST="${2:-/opt/trading-bot}"

SRC="$(cd "$(dirname "$0")/.." && pwd)/"

ssh "$TARGET" "mkdir -p $DEST"

rsync -avz --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'logs/' \
  --exclude '*.log' \
  --exclude '.bot.lock' \
  --exclude '.git' \
  --exclude '.DS_Store' \
  --exclude 'dca_state*.json' \
  --exclude 'withdraw_state.json' \
  --exclude 'status.json' \
  --exclude 'adaptive_state.json' \
  --exclude 'trades.csv' \
  --exclude 'equity.csv' \
  "$SRC" "$TARGET:$DEST/"

echo "Синхронизировано в $TARGET:$DEST"
