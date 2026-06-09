#!/bin/bash
# Создаёт приложение TradingBot.app на рабочем столе — запуск двойным кликом,
# без терминала. Внутри: бот + дашборд в одном окне.
set -e

DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/Desktop/TradingBot.app"

echo "Папка бота: $DIR"

# 1) venv + зависимости (включая оконные).
if [ ! -d "$DIR/.venv" ]; then
  python3 -m venv "$DIR/.venv"
fi
# shellcheck disable=SC1091
source "$DIR/.venv/bin/activate"
echo "Ставлю зависимости (может занять минуту)…"
pip install -q --upgrade pip
pip install -q -r "$DIR/requirements.txt" -r "$DIR/requirements-app.txt"

# 2) Проверим, что .env есть.
if [ ! -f "$DIR/.env" ]; then
  echo "ВНИМАНИЕ: нет $DIR/.env — скопируй .env.example в .env и впиши ключи."
fi

# 3) Собираем .app-бандл.
mkdir -p "$APP/Contents/MacOS"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Trading Bot</string>
    <key>CFBundleDisplayName</key><string>Trading Bot</string>
    <key>CFBundleIdentifier</key><string>com.tradingbot.app</string>
    <key>CFBundleVersion</key><string>1.0</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleExecutable</key><string>TradingBot</string>
</dict>
</plist>
PLIST

# Запускающий скрипт внутри бандла (путь к репозиторию вшит абсолютно).
cat > "$APP/Contents/MacOS/TradingBot" <<LAUNCH
#!/bin/bash
cd "$DIR"
source .venv/bin/activate
# caffeinate не даёт Mac уснуть, пока приложение открыто.
exec caffeinate -ims python app.py
LAUNCH
chmod +x "$APP/Contents/MacOS/TradingBot"

echo
echo "✅ Готово! На рабочем столе появилось приложение TradingBot — запускай двойным кликом."
echo "   Первый раз macOS может спросить подтверждение: правый клик по иконке → Open."
echo "   Закрыть приложение = закрыть его окно."
