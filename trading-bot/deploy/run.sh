#!/bin/bash
# Запуск бота под caffeinate, чтобы Mac не засыпал во время работы.
# Используется launchd-агентом (см. deploy/com.tradingbot.plist).
set -e

# Каталог trading-bot (на уровень выше этого скрипта).
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

# Активируем виртуальное окружение, если оно есть.
if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
  PY="python"
else
  PY="python3"
fi

# caffeinate флаги: -i не спать в простое, -m диски не спят, -s не спать на питании.
# exec — чтобы launchd следил именно за этим процессом.
# --headless: без окна (окно под launchd переоткрывалось бы после каждого закрытия);
# дашборд при этом доступен в браузере на http://localhost:8000
exec caffeinate -ims "$PY" app.py --headless
