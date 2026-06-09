"""Менеджер бота: запуск/остановка/перезапуск потока трейдера, смена режима
(тест ↔ боевой) с закрытием позиций, доступ к балансам/позициям/ордерам.

Используется приложением (app.py). Дашборд обращается к синглтону `instance`.
"""
from __future__ import annotations

import logging
import threading

import settings_store
from config import Config
from main import create_trader

log = logging.getLogger("bot.manager")


class BotManager:
    def __init__(self):
        self._lock = threading.RLock()
        self.cfg: Config | None = None
        self.trader = None
        self.thread: threading.Thread | None = None
        self.stop_event: threading.Event | None = None
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    # ── Жизненный цикл ─────────────────────────────────────────────────
    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            try:
                self.cfg = Config.load()
                self.trader = create_trader(self.cfg, log)
                self.error = None
            except Exception as exc:  # noqa: BLE001 — показываем причину в окне
                self.error = str(exc)
                self.trader = None
                log.error("Старт бота не удался: %s", exc)
                return
            self.stop_event = threading.Event()
            self.thread = threading.Thread(
                target=self.trader.run, args=(self.stop_event,), daemon=True)
            self.thread.start()
            log.info("Бот запущен (режим: %s)", self.mode)

    def stop(self) -> None:
        with self._lock:
            if self.stop_event:
                self.stop_event.set()
            t = self.thread
        if t:
            t.join(timeout=15)
        with self._lock:
            self.thread = None

    def restart(self) -> None:
        self.stop()
        self.start()

    # ── Действия панели ────────────────────────────────────────────────
    def flatten(self) -> int:
        with self._lock:
            if self.trader:
                return self.trader.close_all_positions()
            return 0

    def switch_mode(self, target: str) -> dict:
        """target: 'test' (testnet) или 'live' (боевой). Перед уходом в тест
        закрываем открытые боевые позиции."""
        if target not in ("test", "live"):
            return {"ok": False, "error": "неизвестный режим"}
        going_to_test = target == "test"
        with self._lock:
            currently_live = self.cfg is not None and not self.cfg.testnet and not self.cfg.dry_run
        closed = 0
        if going_to_test and currently_live:
            try:
                closed = self.flatten()
            except Exception as exc:  # noqa: BLE001
                log.error("Не удалось закрыть позиции перед сменой режима: %s", exc)
                return {"ok": False, "error": f"закрытие позиций: {exc}"}
        settings_store.set_value("TESTNET", "true" if going_to_test else "false")
        settings_store.set_value("DRY_RUN", "false")
        self.restart()
        return {"ok": True, "closed": closed, "mode": self.mode, "error": self.error}

    def apply_settings(self, values: dict) -> dict:
        changed = settings_store.save_settings(values)
        self.restart()
        return {"ok": True, "changed": changed, "error": self.error}

    # ── Чтение состояния ───────────────────────────────────────────────
    @property
    def mode(self) -> str:
        if self.cfg is None:
            return "—"
        if self.cfg.dry_run:
            return "dry"
        return "test" if self.cfg.testnet else "live"

    def info(self) -> dict:
        return {
            "running": self.running,
            "mode": self.mode,
            "strategy": self.cfg.strategy if self.cfg else None,
            "symbols": self.cfg.symbols if self.cfg else [],
            "error": self.error,
        }

    def positions(self) -> list[dict]:
        with self._lock:
            if self.trader and hasattr(self.trader, "snapshot"):
                try:
                    return self.trader.snapshot()
                except Exception as exc:  # noqa: BLE001
                    log.error("Не удалось получить позиции: %s", exc)
            return []

    def balances(self) -> dict:
        with self._lock:
            if self.trader:
                try:
                    return self.trader.ex.balances()
                except Exception as exc:  # noqa: BLE001
                    log.error("Не удалось получить балансы: %s", exc)
            return {}

    def open_orders(self) -> list:
        with self._lock:
            if self.trader:
                try:
                    return self.trader.ex.open_orders()
                except Exception as exc:  # noqa: BLE001
                    log.error("Не удалось получить ордера: %s", exc)
            return []

    def deposit_address(self, coin: str, network: str | None) -> dict:
        with self._lock:
            if self.trader:
                try:
                    return self.trader.ex.deposit_address(coin, network)
                except Exception as exc:  # noqa: BLE001
                    return {"address": "", "note": f"ошибка: {exc}"}
            return {"address": "", "note": "бот не запущен"}


# Синглтон, к которому обращается дашборд.
instance = BotManager()
