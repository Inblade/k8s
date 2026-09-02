#!/bin/bash
# Запуск бота под caffeinate, чтобы Mac не засыпал во время работы.
# Используется launchd-агентом (см. deploy/com.tradingbot.plist).
set -e

# Каталог trading-bot (на уровень выше этого скрипта).
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

# bot.log — это перехваченный launchd вывод; на ходу его не ротировать: файл
# открыт как stdout работающего процесса, и подмена inode увела бы запись в
# никуда. Поэтому чистим только здесь, до запуска python.
#
# Единственная чистка за весь аптайм — значит порог должен быть низким: бот
# работает неделями, и десятимегабайтный порог не срабатывал ни разу. В фоне
# консоль пишет только WARNING+ (см. app.py), так что 2 МБ bot.log — это уже
# месяцы аварийных сообщений, а всё сверх того лишнее.
if [ -f bot.log ] && [ "$(wc -c < bot.log)" -gt 2097152 ]; then
  tail -c 262144 bot.log > bot.log.tmp && mv bot.log.tmp bot.log
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
