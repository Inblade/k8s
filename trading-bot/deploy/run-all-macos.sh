#!/bin/bash
# Открывает ДВА окна Terminal на macOS: в одном бот, в другом дашборд.
# Запуск:  ./deploy/run-all-macos.sh
set -e

DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Команда активации venv (если есть) + запуск.
activate="cd '$DIR'; [ -f .venv/bin/activate ] && source .venv/bin/activate; "

osascript <<EOF
tell application "Terminal"
    activate
    do script "${activate}echo '=== БОТ ==='; python main.py"
    delay 1
    do script "${activate}echo '=== ДАШБОРД http://localhost:8000 ==='; python dashboard.py"
end tell
EOF

echo "Открыты два окна: бот и дашборд."
echo "Дашборд: http://localhost:8000"
echo "Логи пишутся в $DIR/logs/<дата>/<час>.log"
