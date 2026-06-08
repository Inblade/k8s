"""Главный торговый цикл: связывает данные, стратегию, риск-менеджмент и биржу."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from config import Config
from exchange import Exchange
from strategy import Signal, compute_indicators, decide

log = logging.getLogger("bot.trader")

STATE_FILE = Path(__file__).with_name("state.json")


@dataclass
class Position:
    """Открытая позиция. Если qty == 0 — мы вне рынка."""
    qty: float = 0.0
    entry_price: float = 0.0

    @property
    def is_open(self) -> bool:
        return self.qty > 0


class Trader:
    def __init__(self, cfg: Config, exchange: Exchange):
        self.cfg = cfg
        self.ex = exchange
        self.position = self._load_state()

    # ── Состояние ──────────────────────────────────────────────────────
    def _load_state(self) -> Position:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text())
            return Position(**data)
        return Position()

    def _save_state(self) -> None:
        STATE_FILE.write_text(json.dumps(asdict(self.position)))

    # ── Один шаг цикла ─────────────────────────────────────────────────
    def step(self) -> None:
        cfg = self.cfg
        # Нужно достаточно свечей под самый длинный индикатор + запас.
        need = max(cfg.slow_ma, cfg.rsi_period) + 5
        closes = self.ex.get_closes(cfg.symbol, cfg.interval, limit=need + 50)
        ind = compute_indicators(closes, cfg.fast_ma, cfg.slow_ma, cfg.rsi_period)
        price = ind.last_price

        log.info(
            "Цена=%.2f  fastMA=%.2f  slowMA=%.2f  RSI=%.1f  %s",
            price, ind.fast_ma, ind.slow_ma, ind.rsi,
            "В ПОЗИЦИИ" if self.position.is_open else "вне рынка",
        )

        if self.position.is_open:
            # 1) Риск-менеджмент имеет приоритет над сигналами стратегии.
            if self._check_risk_exit(price):
                return
            # 2) Сигнал стратегии на выход.
            if decide(ind, cfg.rsi_overbought, cfg.rsi_oversold) == Signal.SELL:
                self._exit("сигнал SELL (пересечение MA)", price)
        else:
            if decide(ind, cfg.rsi_overbought, cfg.rsi_oversold) == Signal.BUY:
                self._enter(price)

    def _check_risk_exit(self, price: float) -> bool:
        entry = self.position.entry_price
        sl = entry * (1 - self.cfg.stop_loss_pct / 100)
        tp = entry * (1 + self.cfg.take_profit_pct / 100)
        if price <= sl:
            self._exit(f"СТОП-ЛОСС ({self.cfg.stop_loss_pct}%)", price)
            return True
        if price >= tp:
            self._exit(f"ТЕЙК-ПРОФИТ ({self.cfg.take_profit_pct}%)", price)
            return True
        return False

    # ── Вход / выход ───────────────────────────────────────────────────
    def _enter(self, price: float) -> None:
        amount = self.cfg.trade_quote_amount
        min_notional = self.ex.min_notional(self.cfg.symbol) if not self.ex.dry_run else 0
        if amount < min_notional:
            log.warning("Сумма %.2f меньше минимальной %.2f — пропускаю покупку",
                        amount, min_notional)
            return
        order = self.ex.market_buy_quote(self.cfg.symbol, amount)
        qty = float(order.get("qty") or self._executed_qty(order))
        self.position = Position(qty=qty, entry_price=price)
        self._save_state()
        log.info(">>> ВХОД: куплено %.8f по ~%.2f", qty, price)

    def _exit(self, reason: str, price: float) -> None:
        self.ex.market_sell_qty(self.cfg.symbol, self.position.qty)
        pnl_pct = (price / self.position.entry_price - 1) * 100 if self.position.entry_price else 0
        log.info("<<< ВЫХОД (%s): продано %.8f по ~%.2f | P&L=%.2f%%",
                 reason, self.position.qty, price, pnl_pct)
        self.position = Position()
        self._save_state()

    @staticmethod
    def _executed_qty(order: dict) -> float:
        # Для реальных ордеров Binance возвращает executedQty.
        return float(order.get("executedQty", 0.0))

    # ── Запуск ─────────────────────────────────────────────────────────
    def run(self) -> None:
        log.info(
            "Старт бота | %s %s | DRY_RUN=%s TESTNET=%s | сумма сделки=%.2f USDT",
            self.cfg.symbol, self.cfg.interval, self.ex.dry_run, self.ex.testnet,
            self.cfg.trade_quote_amount,
        )
        while True:
            try:
                self.step()
            except Exception as exc:  # noqa: BLE001 — бот не должен падать из-за разовой ошибки
                log.exception("Ошибка в цикле: %s", exc)
            time.sleep(self.cfg.poll_interval_seconds)
