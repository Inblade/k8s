"""Обёртка над Binance API. Изолирует весь сетевой код и поддерживает DRY_RUN."""
from __future__ import annotations

import logging
from decimal import ROUND_DOWN, Decimal

from binance.client import Client

log = logging.getLogger("bot.exchange")


class Exchange:
    def __init__(self, api_key: str, api_secret: str, testnet: bool, dry_run: bool):
        self.dry_run = dry_run
        self.testnet = testnet
        # Для DRY_RUN без ключей всё равно нужен клиент для чтения свечей (публичные данные).
        self.client = Client(api_key or None, api_secret or None, testnet=testnet)
        self._filters_cache: dict[str, dict] = {}

    # ── Рыночные данные ────────────────────────────────────────────────
    def get_closes(self, symbol: str, interval: str, limit: int) -> list[float]:
        klines = self.client.get_klines(symbol=symbol, interval=interval, limit=limit)
        # Индекс 4 — цена закрытия свечи.
        return [float(k[4]) for k in klines]

    def get_price(self, symbol: str) -> float:
        return float(self.client.get_symbol_ticker(symbol=symbol)["price"])

    # ── Счёт ───────────────────────────────────────────────────────────
    def get_free_balance(self, asset: str) -> float:
        if self.dry_run:
            return 0.0
        bal = self.client.get_asset_balance(asset=asset)
        return float(bal["free"]) if bal else 0.0

    # ── Биржевые фильтры (минимальный лот, шаг и т.п.) ────────────────
    def _symbol_filters(self, symbol: str) -> dict:
        if symbol not in self._filters_cache:
            info = self.client.get_symbol_info(symbol)
            self._filters_cache[symbol] = {f["filterType"]: f for f in info["filters"]}
        return self._filters_cache[symbol]

    def round_qty(self, symbol: str, qty: float) -> float:
        """Округляет количество вниз до шага LOT_SIZE."""
        step = Decimal(self._symbol_filters(symbol)["LOT_SIZE"]["stepSize"])
        q = (Decimal(str(qty)) / step).to_integral_value(rounding=ROUND_DOWN) * step
        return float(q)

    def min_notional(self, symbol: str) -> float:
        filters = self._symbol_filters(symbol)
        f = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL")
        return float(f["minNotional"]) if f else 0.0

    # ── Ордера ─────────────────────────────────────────────────────────
    def market_buy_quote(self, symbol: str, quote_amount: float) -> dict:
        """Покупка по рынку на сумму `quote_amount` в котируемой валюте (USDT)."""
        if self.dry_run:
            price = self.get_price(symbol)
            qty = quote_amount / price
            log.info("[DRY_RUN] BUY %s на %.2f USDT (~%.8f по цене %.2f)",
                     symbol, quote_amount, qty, price)
            return {"dry_run": True, "side": "BUY", "price": price, "qty": qty}
        order = self.client.order_market_buy(
            symbol=symbol, quoteOrderQty=round(quote_amount, 2)
        )
        log.info("BUY исполнен: %s", order.get("orderId"))
        return order

    def market_sell_qty(self, symbol: str, qty: float) -> dict:
        """Продажа по рынку количества `qty` базовой валюты (BTC)."""
        qty = self.round_qty(symbol, qty)
        if self.dry_run:
            price = self.get_price(symbol)
            log.info("[DRY_RUN] SELL %s кол-во %.8f (по цене %.2f)", symbol, qty, price)
            return {"dry_run": True, "side": "SELL", "price": price, "qty": qty}
        order = self.client.order_market_sell(symbol=symbol, quantity=qty)
        log.info("SELL исполнен: %s", order.get("orderId"))
        return order
