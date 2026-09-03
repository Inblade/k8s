"""Обёртка над Binance API. Изолирует весь сетевой код и поддерживает DRY_RUN."""
from __future__ import annotations

import logging
import time
from decimal import ROUND_DOWN, Decimal

from binance.client import Client

log = logging.getLogger("bot.exchange")


class SuspectPrice(RuntimeError):
    """Тик слишком далеко от предыдущего, чтобы ему верить.

    Настоящая цена в этот момент неизвестна, поэтому её не подменяют и не
    сглаживают: шаг просто пропускается, как при обрыве связи. Через минуту
    придёт следующий тик, и если движение реальное — оно подтвердится.
    """

    def __init__(self, symbol: str, price: float, ref: float):
        self.symbol, self.price, self.ref = symbol, price, ref
        # ref нулевой, когда сравнивать было не с чем и цена сама по себе мусор.
        deviation = f" ({(price / ref - 1) * 100:+.1f}%)" if ref > 0 else ""
        super().__init__(f"{symbol}: тик {price:.2f} против {ref:.2f}{deviation}")


def is_network_error(exc: BaseException) -> bool:
    """Сбой связи (сон ноутбука, пропавший Wi-Fi, таймаут биржи), а не баг в коде.

    Ловим по имени класса, чтобы не тащить requests/urllib3 в импорты и не
    зависеть от того, во что именно python-binance завернул ошибку.
    """
    seen = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        name = type(cur).__name__
        if name in {"ConnectionError", "ConnectTimeout", "ReadTimeout", "Timeout",
                    "TimeoutError", "ConnectionResetError", "ConnectionAbortedError",
                    "ConnectionRefusedError", "NameResolutionError", "NewConnectionError",
                    "MaxRetryError", "ProtocolError", "SSLError", "SSLEOFError",
                    "ChunkedEncodingError", "RequestException", "gaierror", "OSError"}:
            return True
        # Биржа отдала HTML вместо JSON (заглушка Cloudflare/техработы).
        if name == "BinanceAPIException" and "Invalid JSON" in str(cur):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def _short_error(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    return text[:160] + "…" if len(text) > 160 else text


class Exchange:
    def __init__(self, api_key: str, api_secret: str, testnet: bool, dry_run: bool,
                 max_jump_pct: float = 5.0, confirm_ticks: int = 2,
                 stale_seconds: float = 600.0):
        self.dry_run = dry_run
        self.testnet = testnet
        # Для DRY_RUN без ключей всё равно нужен клиент для чтения свечей (публичные данные).
        self.client = Client(api_key or None, api_secret or None, testnet=testnet)
        self._info_cache: dict[str, dict] = {}

        # Защита от выброса в ленте цен. 0 = выключена.
        self.max_jump_pct = max_jump_pct
        self.confirm_ticks = confirm_ticks
        self.stale_seconds = stale_seconds
        self._last: dict[str, tuple[float, float]] = {}   # символ -> (цена, момент)
        self._rejected: dict[str, int] = {}               # подряд отвергнутых тиков

    # ── Информация о паре (фильтры, базовая валюта) ───────────────────
    def _symbol_info(self, symbol: str) -> dict:
        if symbol not in self._info_cache:
            self._info_cache[symbol] = self.client.get_symbol_info(symbol)
        return self._info_cache[symbol]

    def _symbol_filters(self, symbol: str) -> dict:
        return {f["filterType"]: f for f in self._symbol_info(symbol)["filters"]}

    def base_asset(self, symbol: str) -> str:
        return self._symbol_info(symbol)["baseAsset"]

    def quote_asset(self, symbol: str) -> str:
        return self._symbol_info(symbol)["quoteAsset"]

    # ── Проверка доступа при старте ────────────────────────────────────
    def verify_credentials(self, expect_withdraw: bool = False) -> dict:
        """Проверяет, что ключи валидны и права соответствуют ожиданиям.

        Если expect_withdraw=False — требует, чтобы право вывода было ВЫКЛЮЧЕНО
        (безопасный режим). Если True (включён автовывод прибыли) — наоборот,
        требует наличие права вывода и громко предупреждает о рисках.
        """
        self.client.ping()  # связь с биржей
        account = self.client.get_account()  # подпись ключа верна?

        # Проверка прав доступна только на боевой сети (на testnet эндпоинта нет).
        if not self.testnet:
            perms = self.client.get_account_api_permissions()
            has_withdraw = bool(perms.get("enableWithdrawals"))
            if not expect_withdraw and has_withdraw:
                raise PermissionError(
                    "ОПАСНО: у ключа включено право вывода (Withdrawals), но автовывод "
                    "выключен. Отключи право вывода у ключа, либо включи WITHDRAW_ENABLED."
                )
            if expect_withdraw and not has_withdraw:
                raise PermissionError(
                    "WITHDRAW_ENABLED=true, но у ключа НЕТ права вывода. Включи "
                    "'Enable Withdrawals' у API-ключа (желательно с белым списком адресов)."
                )
            if expect_withdraw and not perms.get("ipRestrict"):
                log.warning("ВНИМАНИЕ: у ключа с правом вывода НЕ включено ограничение по IP. "
                            "Очень желательно включить белый список адресов вывода на Binance.")
            if not perms.get("enableSpotAndMarginTrading"):
                raise PermissionError(
                    "У ключа нет права спот-торговли. Включи 'Enable Spot & Margin Trading'."
                )

        balances = {b["asset"]: float(b["free"]) for b in account.get("balances", [])
                    if float(b["free"]) > 0}
        return {"can_trade": account.get("canTrade"), "balances": balances}

    # ── Рыночные данные ────────────────────────────────────────────────
    def get_closes(self, symbol: str, interval: str, limit: int) -> list[float]:
        klines = self.client.get_klines(symbol=symbol, interval=interval, limit=limit)
        # Индекс 4 — цена закрытия свечи.
        return [float(k[4]) for k in klines]

    def get_price(self, symbol: str) -> float:
        """Текущая цена, прошедшая проверку на выброс.

        Бросает SuspectPrice, если тик неправдоподобно далёк от предыдущего.
        """
        raw = float(self.client.get_symbol_ticker(symbol=symbol)["price"])
        return self._checked(symbol, raw, time.monotonic())

    def _checked(self, symbol: str, price: float, now: float) -> float:
        """Пропускает цену или бракует её как выброс.

        Одиночный тик мимо коридора отвергается, но если следующие тики
        подтверждают тот же уровень, движение признаётся настоящим: иначе
        обвал рынка навсегда заблокировал бы торговлю.
        """
        prev = self._last.get(symbol)

        # Ноль или минус — это не цена. Такой тик нельзя ни отдать наверх, ни
        # запомнить как опору: опора с нулём обрушила бы следующее сравнение.
        if price <= 0:
            log.warning("%s: биржа вернула цену %.2f — тик отброшен", symbol, price)
            raise SuspectPrice(symbol, price, prev[0] if prev else 0.0)

        # Сравнивать не с чем: первый тик, выключенная защита или слишком
        # давняя точка отсчёта (за десять минут рынок уходит куда угодно).
        if (prev is None or self.max_jump_pct <= 0
                or now - prev[1] > self.stale_seconds):
            self._accept(symbol, price, now)
            return price

        ref = prev[0]
        if abs(price - ref) / ref * 100 <= self.max_jump_pct:
            self._accept(symbol, price, now)
            return price

        seen = self._rejected.get(symbol, 0) + 1
        if seen >= self.confirm_ticks:
            log.warning("%s: движение на %+.1f%% подтвердилось за %d тик(ов) — "
                        "принимаем %.2f как настоящую цену",
                        symbol, (price / ref - 1) * 100, seen, price)
            self._accept(symbol, price, now)
            return price

        self._rejected[symbol] = seen
        log.warning("%s: тик %.2f отклонён как выброс (%+.1f%% от %.2f) — шаг пропущен",
                    symbol, price, (price / ref - 1) * 100, ref)
        raise SuspectPrice(symbol, price, ref)

    def _accept(self, symbol: str, price: float, now: float) -> None:
        self._last[symbol] = (price, now)
        self._rejected.pop(symbol, None)

    # ── Счёт ───────────────────────────────────────────────────────────
    def get_free_balance(self, asset: str) -> float:
        if self.dry_run:
            return 0.0
        bal = self.client.get_asset_balance(asset=asset)
        return float(bal["free"]) if bal else 0.0

    def balances(self) -> dict[str, float]:
        """Все ненулевые свободные балансы {актив: количество}."""
        if self.dry_run:
            return {}
        acct = self.client.get_account()
        return {b["asset"]: float(b["free"]) for b in acct.get("balances", [])
                if float(b["free"]) > 0}

    def open_orders(self, symbol: str | None = None) -> list[dict]:
        if self.dry_run:
            return []
        return self.client.get_open_orders(symbol=symbol) if symbol \
            else self.client.get_open_orders()

    def deposit_address(self, coin: str, network: str | None = None) -> dict:
        """Адрес для пополнения. На testnet/dry недоступно."""
        if self.dry_run or self.testnet:
            return {"address": "", "note": "Адрес депозита доступен только в боевом режиме"}
        return self.client.get_deposit_address(coin=coin, network=network)

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
        if self.dry_run:
            price = self.get_price(symbol)
            qty = self.round_qty(symbol, qty)
            log.info("[DRY_RUN] SELL %s кол-во %.8f (по цене %.2f)", symbol, qty, price)
            return {"dry_run": True, "side": "SELL", "price": price, "qty": qty}
        # Из-за комиссии в монете реальный баланс может быть чуть меньше учтённого —
        # продаём не больше, чем реально есть на споте, иначе ордер отклонят.
        free = self.get_free_balance(self.base_asset(symbol))
        qty = self.round_qty(symbol, min(qty, free))
        if qty <= 0:
            log.warning("SELL %s пропущен: нечего продавать (баланс %.8f)", symbol, free)
            return {"skipped": True, "qty": 0.0}
        order = self.client.order_market_sell(symbol=symbol, quantity=qty)
        log.info("SELL исполнен: %s", order.get("orderId"))
        return order

    # ── Вывод средств ──────────────────────────────────────────────────
    def withdraw(self, asset: str, network: str, address: str, amount: float) -> dict:
        """Вывод `amount` `asset` на внешний `address` в сети `network`."""
        if self.dry_run:
            log.info("[DRY_RUN] WITHDRAW %.2f %s -> %s (%s)", amount, asset, address, network)
            return {"dry_run": True, "id": "dry-run"}
        result = self.client.withdraw(
            coin=asset, network=network, address=address, amount=round(amount, 8)
        )
        log.info("Запрос на вывод отправлен: id=%s", result.get("id"))
        return result
