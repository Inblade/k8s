"""Брокер Alpaca (акции) с тем же интерфейсом, что и Binance Exchange.

Благодаря единому интерфейсу DCA-движок работает поверх обоих брокеров без
изменений. paper-режим Alpaca играет роль «теста» (как Binance testnet).

Клиенты можно подменить в конструкторе (trading_client/data_client) — это
используется в тестах, чтобы не ходить в сеть.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest

log = logging.getLogger("bot.alpaca")

_CASH = {"USD", "USDT", "USDC", "CASH"}


class AlpacaBroker:
    def __init__(self, api_key: str, api_secret: str, paper: bool = True,
                 trading_client=None, data_client=None):
        # У Alpaca нет «сухого» прогона: paper уже песочница. dry_run всегда False,
        # а paper отображаем как testnet-семантику для единообразия с Binance.
        self.dry_run = False
        self.paper = paper
        self.testnet = paper
        self._tc = trading_client or TradingClient(api_key, api_secret, paper=paper)
        self._dc = data_client or StockHistoricalDataClient(api_key, api_secret)

    # ── Проверка доступа ───────────────────────────────────────────────
    def verify_credentials(self, expect_withdraw: bool = False) -> dict:
        acct = self._tc.get_account()
        cash = float(acct.cash)
        return {"can_trade": not getattr(acct, "trading_blocked", False),
                "balances": {"USD": cash} if cash else {}}

    def market_open(self) -> bool:
        """Открыт ли рынок акций (Alpaca отклоняет ордера в нерабочее время)."""
        try:
            return bool(self._tc.get_clock().is_open)
        except Exception as exc:  # noqa: BLE001
            log.warning("Не удалось получить часы рынка: %s", exc)
            return False

    # ── Рыночные данные ────────────────────────────────────────────────
    @staticmethod
    def _timeframe(interval: str) -> TimeFrame:
        """'15m'/'1h'/'1d'/'1w' (стиль Binance) → alpaca TimeFrame."""
        interval = interval.strip().lower()
        num = int("".join(c for c in interval if c.isdigit()) or "1")
        unit = interval[-1]
        mapping = {"m": TimeFrameUnit.Minute, "h": TimeFrameUnit.Hour,
                   "d": TimeFrameUnit.Day, "w": TimeFrameUnit.Week}
        return TimeFrame(num, mapping.get(unit, TimeFrameUnit.Hour))

    @staticmethod
    def _start_for(interval: str, limit: int) -> datetime:
        """Дата начала окна, чтобы вернулось ~limit баров (с запасом на выходные/
        праздники). Без start Alpaca отдаёт почти пустой ответ."""
        interval = interval.strip().lower()
        num = int("".join(c for c in interval if c.isdigit()) or "1")
        unit = interval[-1]
        if unit == "d":
            days = limit * 1.7
        elif unit == "w":
            days = limit * 7 + 14
        elif unit == "h":
            days = (limit / 6.5) * 1.7          # ~6.5 торговых часов в день
        else:                                    # минуты
            days = (limit / (390 / num)) * 1.7   # 390 торговых минут в день
        return datetime.now(timezone.utc) - timedelta(days=int(days) + 10)

    def get_closes(self, symbol: str, interval: str, limit: int) -> list[float]:
        req = StockBarsRequest(symbol_or_symbols=symbol,
                               timeframe=self._timeframe(interval), limit=limit,
                               start=self._start_for(interval, limit), feed=DataFeed.IEX)
        bars = self._dc.get_stock_bars(req)
        return [float(b.close) for b in bars.data.get(symbol, [])]

    def get_price(self, symbol: str) -> float:
        r = self._dc.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=symbol))
        return float(r[symbol].price)

    # ── Счёт ───────────────────────────────────────────────────────────
    def quote_asset(self, symbol: str) -> str:
        return "USD"

    def base_asset(self, symbol: str) -> str:
        return symbol

    def get_free_balance(self, asset: str) -> float:
        if asset.upper() in _CASH:
            return float(self._tc.get_account().cash)
        try:
            pos = self._tc.get_open_position(asset)
            return float(getattr(pos, "qty_available", None) or pos.qty)
        except Exception:  # noqa: BLE001 — нет позиции
            return 0.0

    def balances(self) -> dict[str, float]:
        acct = self._tc.get_account()
        out: dict[str, float] = {"USD": float(acct.cash)}
        try:
            for p in self._tc.get_all_positions():
                out[p.symbol] = float(p.qty)
        except Exception as exc:  # noqa: BLE001
            log.warning("Позиции Alpaca недоступны: %s", exc)
        return out

    def open_orders(self, symbol: str | None = None) -> list[dict]:
        req = GetOrdersRequest(status=QueryOrderStatus.OPEN,
                               symbols=[symbol] if symbol else None)
        orders = self._tc.get_orders(req)
        return [{
            "symbol": o.symbol,
            "side": o.side.value.upper() if hasattr(o.side, "value") else str(o.side),
            "type": o.order_type.value if hasattr(o.order_type, "value") else str(o.order_type),
            "price": str(o.limit_price or o.filled_avg_price or ""),
            "origQty": str(o.qty or o.notional or ""),
        } for o in orders]

    def deposit_address(self, coin: str, network: str | None = None) -> dict:
        return {"address": "", "note": "Счёт акций пополняется банковским переводом "
                                        "на сайте Alpaca (ACH/wire), не криптой."}

    def withdraw(self, asset: str, network: str, address: str, amount: float) -> dict:
        log.info("Вывод по акциям не поддерживается ботом (делается на сайте Alpaca).")
        return {"skipped": True, "note": "вывод по акциям — вручную на Alpaca"}

    # ── Округление / минимумы ──────────────────────────────────────────
    def round_qty(self, symbol: str, qty: float) -> float:
        # Alpaca поддерживает дробные акции; округляем вниз до 9 знаков.
        q = Decimal(str(qty)).quantize(Decimal("1.000000000"), rounding=ROUND_DOWN)
        return float(q)

    def min_notional(self, symbol: str) -> float:
        return 1.0  # минимальный ордер Alpaca — $1 (дробные акции)

    # ── Ордера ─────────────────────────────────────────────────────────
    def _await_fill(self, order_id, tries: int = 12, delay: float = 0.5):
        order = self._tc.get_order_by_id(order_id)
        for _ in range(tries):
            if float(order.filled_qty or 0) > 0:
                return order
            time.sleep(delay)
            order = self._tc.get_order_by_id(order_id)
        return order

    def market_buy_quote(self, symbol: str, quote_amount: float) -> dict:
        req = MarketOrderRequest(symbol=symbol, notional=round(quote_amount, 2),
                                 side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
        o = self._await_fill(self._tc.submit_order(req).id)
        qty = float(o.filled_qty or 0)
        avg = float(o.filled_avg_price or 0)
        log.info("BUY %s на $%.2f → %.6f шт по %.2f", symbol, quote_amount, qty, avg)
        return {"orderId": str(o.id), "qty": qty, "cummulativeQuoteQty": qty * avg, "price": avg}

    def market_sell_qty(self, symbol: str, qty: float) -> dict:
        qty = self.round_qty(symbol, min(qty, self.get_free_balance(symbol)))
        if qty <= 0:
            log.warning("SELL %s пропущен: нет позиции", symbol)
            return {"skipped": True, "qty": 0.0}
        req = MarketOrderRequest(symbol=symbol, qty=qty,
                                 side=OrderSide.SELL, time_in_force=TimeInForce.DAY)
        o = self._await_fill(self._tc.submit_order(req).id)
        log.info("SELL %s %.6f шт исполнен", symbol, qty)
        return {"orderId": str(o.id), "qty": float(o.filled_qty or qty)}
