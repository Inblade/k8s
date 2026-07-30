#!/bin/bash
# Устанавливает бота как launchd-агент на macOS: автозапуск при логине
# и автоматический перезапуск при сбое.
set -e

BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_SRC="$BOT_DIR/deploy/com.tradingbot.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.tradingbot.plist"

echo "Каталог бота: $BOT_DIR"

# Проверим, что .env существует.
if [ ! -f "$BOT_DIR/.env" ]; then
  echo "ОШИБКА: нет файла $BOT_DIR/.env — скопируй .env.example в .env и впиши ключи."
  exit 1
fi

# Останавливаем экземпляр, запущенный вручную (иначе два бота на одном счёте).
if pgrep -f "app.py" >/dev/null 2>&1; then
  echo "Останавливаю запущенный вручную экземпляр (app.py)…"
  pkill -f "app.py" || true
  sleep 2
fi

mkdir -p "$HOME/Library/LaunchAgents"
# Подставляем реальный путь в plist.
sed "s#__BOT_DIR__#$BOT_DIR#g" "$PLIST_SRC" > "$PLIST_DST"

# Перезагружаем агент.
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"

echo "✅ Агент загружен. Бот работает 24/7 и стартует при входе в систему,"
echo "   перезапускается сам при сбое."
echo "   Дашборд: http://localhost:$(grep -E '^DASHBOARD_PORT=' "$BOT_DIR/.env" 2>/dev/null | cut -d= -f2 | tr -d ' ' || echo 8000)"
echo "   Логи:    tail -f \"$BOT_DIR/logs/\$(date +%F)/\$(date +%H).log\""
echo "   Статус:  launchctl list | grep tradingbot"
echo "   Стоп:    ./deploy/uninstall-macos.sh"
echo
echo "ПРИМЕЧАНИЕ: бот теперь работает в фоне без окна. Дашборд открывай в браузере"
echo "по адресу выше. Запускать TradingBot.app одновременно НЕ нужно — второй"
echo "экземпляр не стартует (защита от двойной торговли одним счётом)."
echo
echo "ВАЖНО для работы с ЗАКРЫТОЙ крышкой (иначе Mac уснёт и бот встанет):"
echo "   sudo pmset -a disablesleep 1     # разрешить работу с закрытой крышкой"
echo "   (отключить обратно: sudo pmset -a disablesleep 0)"
