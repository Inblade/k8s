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

mkdir -p "$HOME/Library/LaunchAgents"
# Подставляем реальный путь в plist.
sed "s#__BOT_DIR__#$BOT_DIR#g" "$PLIST_SRC" > "$PLIST_DST"

# Перезагружаем агент.
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"

echo "✅ Агент загружен. Бот запущен и будет стартовать при входе в систему."
echo "   Логи:    tail -f \"$BOT_DIR/bot.log\""
echo "   Статус:  launchctl list | grep tradingbot"
echo
echo "ВАЖНО для работы с ЗАКРЫТОЙ крышкой (иначе Mac уснёт и бот встанет):"
echo "   sudo pmset -a disablesleep 1     # разрешить работу с закрытой крышкой"
echo "   (отключить обратно: sudo pmset -a disablesleep 0)"
