"""Живой торговый цикл для DCA-стратегии. Поддерживает несколько монет сразу."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import journal
from adaptive import AdaptiveController
from config import Config
from dca import Action, DcaEngine, DcaParams
from exchange import Exchange
from withdrawal import ProfitWithdrawer

log = logging.getLogger("bot.dca")

DIR = Path(__file__).parent
STATUS_FILE = DIR / "status.json"


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


def _state_file(symbol: str) -> Path:
    return DIR / f"dca_state_{symbol}.json"


class DcaTrader:
    def __init__(self, cfg: Config, exchange: Exchange):
        self.cfg = cfg
        self.ex = exchange
        params = params_from_config(cfg)
        # Отдельный движок и файл состояния на каждую монету.
        self.engines: dict[str, DcaEngine] = {}
        for sym in cfg.symbols:
            sf = _state_file(sym)
            if sf.exists():
                self.engines[sym] = DcaEngine.from_state_dict(params, json.loads(sf.read_text()))
            else:
                self.engines[sym] = DcaEngine(params)
        self.withdrawer = ProfitWithdrawer(cfg, exchange)
        self.controller = AdaptiveController(cfg, exchange) if cfg.adaptive_enabled else None

    def _save(self, symbol: str) -> None:
        _state_file(symbol).write_text(json.dumps(self.engines[symbol].state_dict()))

    # ── Обработка одной монеты ─────────────────────────────────────────
    def _process_symbol(self, symbol: str, price: float, allow_new_entry: bool = True) -> None:
        engine = self.engines[symbol]
        s = engine.state
        if not s.in_position and not allow_new_entry:
            log.info("[%s] Цена=%.2f вход на паузе (режим рынка не благоприятен)",
                     symbol, price)
            return
        if s.in_position:
            log.info("[%s] Цена=%.2f средняя=%.2f объём=%.8f safety=%d/%d след.докупка<=%.2f",
                     symbol, price, s.avg_entry, s.qty, s.safety_filled,
                     self.cfg.dca_max_safety_orders, s.next_safety_price)
        else:
            log.info("[%s] Цена=%.2f вне позиции (ждём базовый ордер)", symbol, price)

        order = engine.decide(price)
        if order is None:
            return

        if order.action == Action.BUY:
            result = self.ex.market_buy_quote(symbol, order.quote)
            qty = float(result.get("qty") or result.get("executedQty", 0.0))
            spent = float(result.get("cummulativeQuoteQty") or order.quote)
            engine.apply_buy(price, spent, qty)
            avg = engine.state.avg_entry
            log.info("[%s] >>> ПОКУПКА (%s): +%.8f за %.2f USDT | средняя=%.2f",
                     symbol, order.reason, qty, spent, avg)
            journal.record_trade(symbol, "BUY", order.reason, price, qty, spent, avg)
        elif order.action == Action.SELL_ALL:
            proceeds = s.qty * price * (1 - self.cfg.fee_pct / 100)
            realized = proceeds - s.spent
            pnl_pct = (price / s.avg_entry - 1) * 100 if s.avg_entry else 0
            self.ex.market_sell_qty(symbol, s.qty)
            log.info("[%s] <<< ПРОДАЖА (%s): %.8f по ~%.2f | P&L=%.2f%% (%.2f USDT)",
                     symbol, order.reason, s.qty, price, pnl_pct, realized)
            journal.record_trade(symbol, "SELL", order.reason, price, s.qty,
                                 proceeds, s.avg_entry, realized)
            engine.apply_sell_all()
            self.withdrawer.on_realized_profit(realized)
        self._save(symbol)

    # ── Снимок суммарного капитала по всем монетам ─────────────────────
    def _record_equity(self, prices: dict[str, float]) -> None:
        total_value = 0.0
        total_spent = 0.0
        for sym, engine in self.engines.items():
            st = engine.state
            if st.in_position:
                total_value += st.qty * prices[sym]
                total_spent += st.spent
        realized = self.withdrawer.state.realized_pnl_total
        unrealized = total_value - total_spent
        equity = self.cfg.trade_quote_amount + realized + unrealized
        # В колонку price пишем цену первой (основной) монеты — для графика цены.
        journal.record_equity(
            price=prices[self.cfg.symbol], position_qty=0.0, position_value=total_value,
            unrealized_pnl=unrealized, realized_pnl=realized, equity=equity,
            withdrawn=self.withdrawer.state.withdrawn_total,
            reserve=self.withdrawer.state.reserve,
        )

    def _write_status(self, statuses: dict) -> None:
        from datetime import datetime, timezone
        STATUS_FILE.write_text(json.dumps({
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "adaptive": True,
            "symbols": statuses,
        }))

    def step(self) -> None:
        # Цены берём один раз за шаг, чтобы не дёргать API повторно.
        prices = {sym: self.ex.get_price(sym) for sym in self.cfg.symbols}
        statuses: dict = {}
        for sym in self.cfg.symbols:
            allow = True
            if self.controller is not None:
                closes = self.ex.get_closes(sym, self.cfg.regime_interval,
                                            self.cfg.regime_lookback)
                decision = self.controller.update(sym, closes)
                self.engines[sym].p = decision.params  # применяем адаптацию
                allow = decision.allow_new_entry
                info = decision.info
                log.info("[%s] Режим: %s (наклон %.2f%%, волат. %.2f%%) | TP=%.1f%% | входы: %s",
                         sym, info.regime.value, info.slope_pct, info.volatility_pct,
                         decision.params.take_profit_pct, "да" if allow else "ПАУЗА")
                statuses[sym] = {
                    "regime": info.regime.value,
                    "slope_pct": round(info.slope_pct, 2),
                    "volatility_pct": round(info.volatility_pct, 2),
                    "take_profit_pct": round(decision.params.take_profit_pct, 2),
                    "deviation_pct": round(decision.params.price_deviation_pct, 2),
                    "max_safety": decision.params.max_safety_orders,
                    "allow_new_entry": allow,
                }
            self._process_symbol(sym, prices[sym], allow)
        self._record_equity(prices)
        if self.controller is not None:
            self._write_status(statuses)

    def run(self) -> None:
        log.info(
            "Старт DCA | монеты: %s | DRY_RUN=%s TESTNET=%s | база=%.0f safety=%.0f x%d "
            "дев=%.1f%% TP=%.1f%% | бюджет/монета=%.0f, всего=%.0f USDT",
            ", ".join(self.cfg.symbols), self.ex.dry_run, self.ex.testnet,
            self.cfg.dca_base_order, self.cfg.dca_safety_order,
            self.cfg.dca_max_safety_orders, self.cfg.dca_price_deviation_pct,
            self.cfg.dca_take_profit_pct, self.cfg.max_dca_budget(),
            self.cfg.max_dca_budget() * len(self.cfg.symbols),
        )
        if self.controller is not None:
            log.info("Адаптивный режим ВКЛ: определение тренда/боковика на %s + "
                     "оптимизация параметров каждые %d шагов (optimize=%s)",
                     self.cfg.regime_interval, self.cfg.reoptimize_every,
                     self.cfg.adaptive_optimize)
        while True:
            try:
                self.step()
            except Exception as exc:  # noqa: BLE001 — бот не должен падать из-за разовой ошибки
                log.exception("Ошибка в цикле DCA: %s", exc)
            time.sleep(self.cfg.poll_interval_seconds)
