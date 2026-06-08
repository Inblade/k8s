"""Живой торговый цикл для DCA-стратегии."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from config import Config
from dca import Action, DcaEngine, DcaParams
from exchange import Exchange

log = logging.getLogger("bot.dca")

STATE_FILE = Path(__file__).with_name("dca_state.json")


def params_from_config(cfg: Config) -> DcaParams:
    return DcaParams(
        base_order=cfg.dca_base_order,
        safety_order=cfg.dca_safety_order,
        max_safety_orders=cfg.dca_max_safety_orders,
        price_deviation_pct=cfg.dca_price_deviation_pct,
        safety_step_scale=cfg.dca_safety_step_scale,
        safety_volume_scale=cfg.dca_safety_volume_scale,
        take_profit_pct=cfg.dca_take_profit_pct,
    )


class DcaTrader:
    def __init__(self, cfg: Config, exchange: Exchange):
        self.cfg = cfg
        self.ex = exchange
        params = params_from_config(cfg)
        if STATE_FILE.exists():
            self.engine = DcaEngine.from_state_dict(params, json.loads(STATE_FILE.read_text()))
        else:
            self.engine = DcaEngine(params)

    def _save(self) -> None:
        STATE_FILE.write_text(json.dumps(self.engine.state_dict()))

    def step(self) -> None:
        price = self.ex.get_price(self.cfg.symbol)
        s = self.engine.state
        if s.in_position:
            log.info(
                "Цена=%.2f  средняя=%.2f  объём=%.8f  потрачено=%.2f  safety=%d/%d  след.докупка<=%.2f",
                price, s.avg_entry, s.qty, s.spent, s.safety_filled,
                self.cfg.dca_max_safety_orders, s.next_safety_price,
            )
        else:
            log.info("Цена=%.2f  вне позиции (ждём базовый ордер)", price)

        order = self.engine.decide(price)
        if order is None:
            return

        if order.action == Action.BUY:
            result = self.ex.market_buy_quote(self.cfg.symbol, order.quote)
            qty = float(result.get("qty") or result.get("executedQty", 0.0))
            spent = float(result.get("cummulativeQuoteQty") or order.quote)
            self.engine.apply_buy(price, spent, qty)
            log.info(">>> ПОКУПКА (%s): +%.8f за %.2f USDT | новая средняя=%.2f",
                     order.reason, qty, spent, self.engine.state.avg_entry)
        elif order.action == Action.SELL_ALL:
            pnl = (price / s.avg_entry - 1) * 100 if s.avg_entry else 0
            self.ex.market_sell_qty(self.cfg.symbol, s.qty)
            log.info("<<< ПРОДАЖА ВСЕГО (%s): %.8f по ~%.2f | P&L=%.2f%% | цикл завершён",
                     order.reason, s.qty, price, pnl)
            self.engine.apply_sell_all()
        self._save()

    def run(self) -> None:
        log.info(
            "Старт DCA | %s | DRY_RUN=%s TESTNET=%s | база=%.0f safety=%.0f x%d "
            "дев=%.1f%% TP=%.1f%% | макс.бюджет=%.0f USDT",
            self.cfg.symbol, self.ex.dry_run, self.ex.testnet,
            self.cfg.dca_base_order, self.cfg.dca_safety_order,
            self.cfg.dca_max_safety_orders, self.cfg.dca_price_deviation_pct,
            self.cfg.dca_take_profit_pct, self.cfg.max_dca_budget(),
        )
        while True:
            try:
                self.step()
            except Exception as exc:  # noqa: BLE001 — бот не должен падать из-за разовой ошибки
                log.exception("Ошибка в цикле DCA: %s", exc)
            time.sleep(self.cfg.poll_interval_seconds)
