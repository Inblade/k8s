#!/bin/bash
# Healthcheck торгового бота. Шлёт алерт в Telegram, если:
#   1) systemd-сервis trading-bot не active (упал), или
#   2) пульс завис — equity.csv не обновлялся дольше STALE_MIN минут
#      (бот пишет строку раз в минуту; тишина = завис или умер).
# Алертит ТОЛЬКО на переходе healthy->problem и обратно (без спама).
# Запускается systemd-таймером trading-bot-alert.timer раз в 5 минут.
#
# Активация доставки: в /opt/trading-bot/.env добавить
#   TELEGRAM_BOT_TOKEN=... (от @BotFather)
#   TELEGRAM_CHAT_ID=...    (свой chat id)
# Без них скрипт просто пишет в syslog и ничего не шлёт.
set -uo pipefail

DIR=/opt/trading-bot
FLAG=/tmp/trading-bot-alert.flag
STALE_MIN=5

TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '"'"'"' ')
CHAT=$(grep -E '^TELEGRAM_CHAT_ID=' "$DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '"'"'"' ')

send() {
  local msg="$1"
  logger -t trading-bot-alert "$msg"
  if [ -z "$TOKEN" ] || [ -z "$CHAT" ]; then
    logger -t trading-bot-alert "нет TELEGRAM_BOT_TOKEN/CHAT_ID в .env — в Telegram не отправлено"
    return
  fi
  curl -s -m 15 "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${CHAT}" \
    --data-urlencode "text=🤖 trading-bot ($(hostname)): ${msg}" >/dev/null || true
}

problem=""
if ! systemctl is-active --quiet trading-bot; then
  problem="сервис НЕ active (упал)"
else
  hb="$DIR/equity.csv"
  if [ -f "$hb" ]; then
    age=$(( ( $(date +%s) - $(stat -c %Y "$hb") ) / 60 ))
    if [ "$age" -ge "$STALE_MIN" ]; then
      problem="пульс завис: equity.csv не обновлялся ${age} мин"
    fi
  fi
fi

if [ -n "$problem" ]; then
  if [ ! -f "$FLAG" ]; then
    send "ПРОБЛЕМА: $problem"
    touch "$FLAG"
  fi
else
  if [ -f "$FLAG" ]; then
    send "восстановлен: снова работает"
    rm -f "$FLAG"
  fi
fi
