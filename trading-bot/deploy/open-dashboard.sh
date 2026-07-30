#!/bin/bash
# Открывает дашборд бота в браузере. Если бот не работает — поднимает
# launchd-агент и ждёт, пока дашборд ответит.
# Используется иконкой «TradingBot» на рабочем столе.
set -u

DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.tradingbot.plist"

# Порт из .env (по умолчанию 8000).
PORT="$(grep -E '^DASHBOARD_PORT=' "$DIR/.env" 2>/dev/null | cut -d= -f2 | tr -d ' \r')"
PORT="${PORT:-8000}"
URL="http://localhost:$PORT"

alive() { curl -fsS -m 2 "$URL/api/control" >/dev/null 2>&1; }

if ! alive; then
  # Бот не отвечает — пробуем запустить агент 24/7.
  if [ -f "$PLIST" ]; then
    launchctl load "$PLIST" 2>/dev/null || launchctl kickstart -k "gui/$(id -u)/com.tradingbot" 2>/dev/null || true
  else
    osascript -e 'display alert "Trading Bot" message "Агент 24/7 не установлен. Запусти в терминале:\n\ncd '"$DIR"' && ./deploy/install-macos.sh"' >/dev/null 2>&1
    exit 1
  fi
  # Ждём до ~20 секунд, пока поднимется.
  for _ in $(seq 1 20); do
    alive && break
    sleep 1
  done
fi

if alive; then
  open "$URL"
else
  osascript -e 'display alert "Trading Bot" message "Бот не отвечает на '"$URL"'.\n\nПосмотри логи:\ntail -f '"$DIR"'/logs/$(date +%F)/$(date +%H).log"' >/dev/null 2>&1
  exit 1
fi
