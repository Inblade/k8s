"""Приложение «как программа»: одно окно с дашбордом, внутри которого работают
и торговый бот, и веб-сервер. Без терминала.

Запуск: python app.py  (или двойной клик по TradingBot.app, см. deploy/)

Бот крутится в фоновом потоке, дашборд — локальный веб-сервер, а само окно
рисуется нативно через pywebview. Если pywebview не установлен — открываем
дашборд в браузере как запасной вариант.
"""
from __future__ import annotations

import logging
import threading

from werkzeug.serving import make_server

import dashboard
from logsetup import setup_logging
from main import create_trader


def _run_bot(cfg, log: logging.Logger) -> None:
    try:
        trader = create_trader(cfg, log)
    except Exception as exc:  # noqa: BLE001 — показываем причину в логе/окне
        log.error("Бот не запущен: %s", exc)
        return
    try:
        trader.run()
    except Exception as exc:  # noqa: BLE001
        log.exception("Бот остановлен из-за ошибки: %s", exc)


def main() -> None:
    setup_logging()
    log = logging.getLogger("bot")
    cfg = dashboard.cfg
    url = f"http://127.0.0.1:{cfg.dashboard_port}"

    # 1) Бот в фоне.
    threading.Thread(target=_run_bot, args=(cfg, log), daemon=True).start()

    # 2) Веб-сервер дашборда в фоне (без dev-перезагрузчика).
    server = make_server("127.0.0.1", cfg.dashboard_port, dashboard.app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("Дашборд поднят: %s", url)

    # 3) Нативное окно приложения.
    try:
        import webview
        webview.create_window("Trading Bot", url, width=1200, height=860)
        webview.start()
    except Exception as exc:  # noqa: BLE001 — нет GUI-движка → запасной браузер
        log.warning("Нативное окно недоступно (%s) — открываю в браузере", exc)
        import time
        import webbrowser
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
