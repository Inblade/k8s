#!/bin/bash
# Запуск бота под caffeinate, чтобы Mac не засыпал во время работы.
# Используется launchd-агентом (см. deploy/com.tradingbot.plist).
set -e

# Каталог trading-bot (на уровень выше этого скрипта).
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

# bot.log — это перехваченный launchd вывод. Подрезать его можно только здесь,
# до запуска python, и только СОХРАНЯЯ inode.
#
# launchd открывает StandardOutPath раньше, чем запускает этот скрипт. Прежний
# «tail > tmp && mv tmp bot.log» подменял inode, и stdout процесса оставался
# привязан к старому файлу, у которого уже не было имени: bot.log на диске не
# получал больше ни строчки, а осиротевший inode держал место до конца работы
# бота. Поэтому усекаем существующий файл на месте через «cat > bot.log».
#
# Чистка случается один раз за весь аптайм, а бот работает неделями — значит
# порог должен быть низким. Прежние 10 МБ не сработали ни разу за месяц. В фоне
# консоль пишет только WARNING+ (см. app.py), так что 2 МБ — это уже месяцы
# аварийных сообщений.
if [ -f bot.log ] && [ "$(wc -c < bot.log)" -gt 2097152 ]; then
  tail -c 262144 bot.log > bot.log.tmp
  cat bot.log.tmp > bot.log   # O_TRUNC по тому же inode — fd launchd остаётся жив
  rm -f bot.log.tmp
fi

# Логи старше 60 дней не нужны — чистим, чтобы папка не росла бесконечно.
find logs -mindepth 1 -maxdepth 1 -type d -mtime +60 -exec rm -rf {} + 2>/dev/null || true

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
