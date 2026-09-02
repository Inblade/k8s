"""Приложение «как программа»: одно окно с дашбордом, внутри которого работают
и торговый бот, и веб-сервер. Без терминала.

Запуск:
    python app.py              — с окном (двойной клик по TradingBot.app)
    python app.py --headless   — без окна, для работы 24/7 под launchd

Бот крутится в фоновом потоке, дашборд — локальный веб-сервер, а само окно
рисуется нативно через pywebview. Если pywebview не установлен — открываем
дашборд в браузере как запасной вариант.

Одновременно может работать только ОДИН экземпляр (см. applock): два бота
торговали бы одним счётом и перетирали состояние позиций.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time

from werkzeug.serving import make_server

import applock
import dashboard
from logsetup import setup_logging
from manager import instance as manager


def _headless() -> bool:
    """Без окна: флаг --headless или переменная HEADLESS=1."""
    return "--headless" in sys.argv or os.getenv("HEADLESS", "").strip().lower() in {
        "1", "true", "yes", "on"}


def main() -> int:
    # Без окна вывод консоли перехватывает launchd в bot.log, который на ходу
    # не ротируется. Пульс раз в минуту раздувал его на ~700 КБ в сутки, дублируя
    # logs/<дата>/<час>.log. Поэтому в фоне в консоль идут только проблемы.
    setup_logging(console_level=logging.WARNING if _headless() else None)
    log = logging.getLogger("bot")

    # Один экземпляр: иначе два бота дублировали бы ордера на одном счёте.
    try:
        lock = applock.acquire()  # noqa: F841 — держим открытым всё время работы
    except applock.AlreadyRunning as exc:
        log.error("Запуск отменён: %s", exc)
        return 1

    cfg = dashboard.cfg
    url = f"http://127.0.0.1:{cfg.dashboard_port}"

    # 1) Бот под управлением менеджера (режим/настройки меняются из окна).
    manager.start()

    # 2) Веб-сервер дашборда в фоне (без dev-перезагрузчика).
    try:
        server = make_server("127.0.0.1", cfg.dashboard_port, dashboard.app)
    except OSError as exc:
        log.error("Порт %s занят (%s). Останови другой экземпляр: pkill -f app.py",
                  cfg.dashboard_port, exc)
        return 1
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("Дашборд поднят: %s", url)

    # 3) Окно приложения — или бесконечная работа без окна (24/7).
    if _headless():
        # WARNING, а не INFO: это единственная отметка о старте, которая
        # доходит до bot.log при тихой консоли.
        log.warning("Режим без окна: бот работает в фоне, дашборд доступен по %s. "
                    "Подробный лог: logs/<дата>/<час>.log", url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            log.info("Остановлено пользователем.")
        return 0

    try:
        import webview
        webview.create_window("Trading Bot", url, width=1200, height=860)
        webview.start()
    except Exception as exc:  # noqa: BLE001 — нет GUI-движка → запасной браузер
        log.warning("Нативное окно недоступно (%s) — открываю в браузере", exc)
        import webbrowser
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
