"""Менеджер бота: управляет потоками трейдеров сразу нескольких брокеров
(Binance — крипта, Alpaca — акции). Старт/стоп/перезапуск, смена режима
(тест/paper ↔ боевой) с закрытием позиций, доступ к позициям/балансам/ордерам.

Дашборд обращается к синглтону `instance`.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import settings_store
from config import Config
from main import create_traders

log = logging.getLogger("bot.manager")


@dataclass
class Unit:
    name: str
    trader: object
    thread: threading.Thread
    stop_event: threading.Event


def _mode_of(name: str, trader) -> str:
    c = trader.cfg
    if name == "alpaca":
        return "paper" if c.testnet else "live"
    if c.dry_run:
        return "dry"
    return "test" if c.testnet else "live"


class BotManager:
    def __init__(self):
        self._lock = threading.RLock()
        self.cfg: Config | None = None
        self.units: list[Unit] = []
        self.errors: dict[str, str] = {}

    @property
    def running(self) -> bool:
        return any(u.thread.is_alive() for u in self.units)

    @property
    def error(self) -> str | None:
        return "; ".join(f"{k}: {v}" for k, v in self.errors.items()) or None

    def _unit(self, name: str) -> Unit | None:
        return next((u for u in self.units if u.name == name), None)

    # ── Жизненный цикл ─────────────────────────────────────────────────
    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            try:
                self.cfg = Config.load()
            except Exception as exc:  # noqa: BLE001
                self.errors = {"config": str(exc)}
                log.error("Конфиг не загружен: %s", exc)
                return
            built, self.errors = create_traders(self.cfg, log)
            self.units = []
            for name, trader in built:
                ev = threading.Event()
                th = threading.Thread(target=trader.run, args=(ev,), daemon=True)
                th.start()
                self.units.append(Unit(name, trader, th, ev))
                log.info("Брокер %s запущен (режим: %s)", name, _mode_of(name, trader))

    def stop(self) -> None:
        with self._lock:
            units = list(self.units)
            for u in units:
                u.stop_event.set()
        for u in units:
            u.thread.join(timeout=15)
        with self._lock:
            self.units = []

    def restart(self) -> None:
        self.stop()
        self.start()

    # ── Действия панели ────────────────────────────────────────────────
    def flatten(self, broker: str | None = None) -> int:
        with self._lock:
            targets = [u for u in self.units if broker in (None, u.name)]
        closed = 0
        for u in targets:
            try:
                closed += u.trader.close_all_positions()
            except Exception as exc:  # noqa: BLE001
                log.error("Не удалось закрыть позиции (%s): %s", u.name, exc)
        return closed

    def switch_mode(self, broker: str, target: str) -> dict:
        """broker: binance|alpaca. target: для binance test|live, для alpaca paper|live.
        Перед уходом из боевого в тест/paper закрываем открытые боевые позиции."""
        with self._lock:
            unit = self._unit(broker)
            currently_live = unit is not None and _mode_of(broker, unit.trader) == "live"

        if broker == "binance":
            if target not in ("test", "live"):
                return {"ok": False, "error": "режим binance: test|live"}
            going_safe = target == "test"
            env_key, env_val = "TESTNET", "true" if going_safe else "false"
        elif broker == "alpaca":
            if target not in ("paper", "live"):
                return {"ok": False, "error": "режим alpaca: paper|live"}
            going_safe = target == "paper"
            env_key, env_val = "ALPACA_PAPER", "true" if going_safe else "false"
        else:
            return {"ok": False, "error": "неизвестный брокер"}

        closed = 0
        if going_safe and currently_live:
            try:
                closed = self.flatten(broker)
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"закрытие позиций: {exc}"}
        settings_store.set_value(env_key, env_val)
        if broker == "binance":
            settings_store.set_value("DRY_RUN", "false")
        self.restart()
        return {"ok": True, "closed": closed, "error": self.error}

    def apply_settings(self, values: dict) -> dict:
        changed = settings_store.save_settings(values)
        self.restart()
        return {"ok": True, "changed": changed, "error": self.error}

    # ── Чтение состояния ───────────────────────────────────────────────
    def info(self) -> dict:
        with self._lock:
            units = [{
                "name": u.name,
                "mode": _mode_of(u.name, u.trader),
                "running": u.thread.is_alive(),
                "symbols": list(u.trader.cfg.symbols),
            } for u in self.units]
        return {"running": self.running, "units": units, "error": self.error,
                "errors": self.errors}

    def positions(self) -> list[dict]:
        out: list[dict] = []
        with self._lock:
            units = list(self.units)
        for u in units:
            try:
                for p in u.trader.snapshot():
                    out.append({**p, "broker": u.name})
            except Exception as exc:  # noqa: BLE001
                log.error("Позиции (%s) недоступны: %s", u.name, exc)
        return out

    def balances(self) -> dict:
        out: dict = {}
        with self._lock:
            units = list(self.units)
        for u in units:
            try:
                out[u.name] = u.trader.ex.balances()
            except Exception as exc:  # noqa: BLE001
                log.error("Балансы (%s) недоступны: %s", u.name, exc)
        return out

    def open_orders(self) -> list:
        out: list = []
        with self._lock:
            units = list(self.units)
        for u in units:
            try:
                for o in u.trader.ex.open_orders():
                    out.append({**o, "broker": u.name})
            except Exception as exc:  # noqa: BLE001
                log.error("Ордера (%s) недоступны: %s", u.name, exc)
        return out

    def deposit_address(self, coin: str, network: str | None) -> dict:
        with self._lock:
            unit = self._unit("binance")
        if unit is None:
            return {"address": "", "note": "Binance не запущен"}
        try:
            return unit.trader.ex.deposit_address(coin, network)
        except Exception as exc:  # noqa: BLE001
            return {"address": "", "note": f"ошибка: {exc}"}


# Синглтон, к которому обращается дашборд.
instance = BotManager()
