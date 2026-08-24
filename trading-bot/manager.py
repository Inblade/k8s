"""Менеджер бота: управляет потоком трейдера (Binance — крипта).

Старт/стоп/перезапуск, смена режима (testnet ↔ боевой) с закрытием позиций,
доступ к позициям/балансам/ордерам. Дашборд обращается к синглтону `instance`.
"""
from __future__ import annotations

import logging
import threading

import settings_store
from config import Config
from dca_trader import _short_error, is_network_error
from main import create_trader

log = logging.getLogger("bot.manager")


def _log_api_error(what: str, exc: BaseException) -> None:
    """Сбой связи — это шум (дашборд опрашивает биржу каждые несколько секунд),
    поэтому пишем его коротко и как WARNING; всё остальное — как ошибку."""
    if is_network_error(exc):
        log.warning("%s: нет связи с биржей (%s)", what, _short_error(exc))
    else:
        log.error("%s: %s", what, exc)


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

    @property
    def mode(self) -> str:
        """dry — симуляция, test — testnet, live — реальные деньги."""
        if self.cfg is None:
            return "—"
        if self.cfg.dry_run:
            return "dry"
        return "test" if self.cfg.testnet else "live"

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
                log.error("Бот не запущен: %s", exc)
                return
            self.stop_event = threading.Event()
            self.thread = threading.Thread(
                target=self.trader.run, args=(self.stop_event,), daemon=True)
            self.thread.start()
            log.info("Бот запущен (режим: %s, монеты: %s)",
                     self.mode, ", ".join(self.cfg.symbols))

    def stop(self) -> None:
        with self._lock:
            if self.stop_event:
                self.stop_event.set()
            th = self.thread
        if th:
            th.join(timeout=15)
        with self._lock:
            self.thread = None

    def restart(self) -> None:
        self.stop()
        self.start()

    # ── Действия панели ────────────────────────────────────────────────
    def flatten(self) -> int:
        """Закрывает все открытые позиции в рынок. Возвращает число закрытых."""
        with self._lock:
            trader = self.trader
        if trader is None:
            return 0
        try:
            return trader.close_all_positions()
        except Exception as exc:  # noqa: BLE001
            log.error("Не удалось закрыть позиции: %s", exc)
            return 0

    def switch_mode(self, target: str) -> dict:
        """target: 'test' (testnet) или 'live' (реальные деньги).
        Перед уходом из боевого в testnet закрываем открытые позиции."""
        if target not in ("test", "live"):
            return {"ok": False, "error": "режим: test|live"}
        going_safe = target == "test"
        with self._lock:
            currently_live = self.mode == "live"
        closed = 0
        if going_safe and currently_live:
            try:
                closed = self.flatten()
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"закрытие позиций: {exc}"}
        settings_store.set_value("TESTNET", "true" if going_safe else "false")
        settings_store.set_value("DRY_RUN", "false")
        self.restart()
        return {"ok": True, "closed": closed, "mode": self.mode, "error": self.error}

    def apply_settings(self, values: dict) -> dict:
        changed = settings_store.save_settings(values)
        self.restart()
        return {"ok": True, "changed": changed, "error": self.error}

    # ── Чтение состояния ───────────────────────────────────────────────
    def info(self) -> dict:
        with self._lock:
            cfg = self.cfg
        return {
            "running": self.running,
            "mode": self.mode,
            "symbols": list(cfg.symbols) if cfg else [],
            "budget": cfg.trade_quote_amount if cfg else 0.0,
            "strategy": cfg.strategy if cfg else None,
            "error": self.error,
        }

    def positions(self) -> list[dict]:
        with self._lock:
            trader = self.trader
        if trader is None:
            return []
        try:
            return trader.snapshot()
        except Exception as exc:  # noqa: BLE001
            _log_api_error("Позиции недоступны", exc)
            return []

    def balances(self) -> dict:
        with self._lock:
            trader = self.trader
        if trader is None:
            return {}
        try:
            return trader.ex.balances()
        except Exception as exc:  # noqa: BLE001
            _log_api_error("Балансы недоступны", exc)
            return {}

    def open_orders(self) -> list:
        with self._lock:
            trader = self.trader
        if trader is None:
            return []
        try:
            return trader.ex.open_orders()
        except Exception as exc:  # noqa: BLE001
            _log_api_error("Ордера недоступны", exc)
            return []

    def backtest(self, symbol: str, interval: str, limit: int) -> dict:
        """Прогон DCA-стратегии по историческим свечам монеты."""
        from dca import simulate_dca
        from dca_trader import params_from_config
        with self._lock:
            trader = self.trader
        if trader is None:
            return {"error": "бот не запущен"}
        try:
            closes = trader.ex.get_closes(symbol, interval, limit)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"не удалось получить свечи: {exc}"}
        if len(closes) < 2:
            return {"error": "недостаточно исторических данных"}
        cfg = trader.cfg
        res = simulate_dca(closes, params_from_config(cfg),
                           cfg.trade_quote_amount, cfg.fee_pct)
        res.update({"symbol": symbol, "interval": interval, "bars": len(closes),
                    "start_cash": cfg.trade_quote_amount})
        return res

    def deposit_address(self, coin: str, network: str | None) -> dict:
        with self._lock:
            trader = self.trader
        if trader is None:
            return {"address": "", "note": "бот не запущен"}
        try:
            return trader.ex.deposit_address(coin, network)
        except Exception as exc:  # noqa: BLE001
            return {"address": "", "note": f"ошибка: {exc}"}


# Синглтон, к которому обращается дашборд.
instance = BotManager()
