#!/bin/bash
# Создаёт на рабочем столе иконку «TradingBot» — двойной клик открывает дашборд
# работающего бота в браузере (и поднимает агент 24/7, если тот остановлен).
#
# Это НЕ второй экземпляр бота: сам бот работает в фоне под launchd
# (см. install-macos.sh), иконка только показывает его панель.
set -e

DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/Desktop/TradingBot.app"

mkdir -p "$APP/Contents/MacOS"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Trading Bot</string>
    <key>CFBundleDisplayName</key><string>Trading Bot</string>
    <key>CFBundleIdentifier</key><string>com.tradingbot.dashboard</string>
    <key>CFBundleVersion</key><string>2.0</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleExecutable</key><string>TradingBot</string>
    <!-- Не держим иконку в Dock: это просто «открывашка» дашборда. -->
    <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/TradingBot" <<LAUNCH
#!/bin/bash
exec "$DIR/deploy/open-dashboard.sh"
LAUNCH
chmod +x "$APP/Contents/MacOS/TradingBot"

echo "✅ Иконка TradingBot на рабочем столе обновлена."
echo "   Двойной клик → открывает дашборд бота в браузере."
echo "   Сам бот работает в фоне 24/7 (агент launchd), от иконки не зависит."
echo
echo "Если агент 24/7 ещё не установлен — сначала: ./deploy/install-macos.sh"
