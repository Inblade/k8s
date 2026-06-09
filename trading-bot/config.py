"""Загрузка и валидация конфигурации из переменных окружения / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    # Пустая строка (например, форма настроек записала "KEY=") = «не задано» → дефолт,
    # иначе включённый по умолчанию брокер молча выключался бы после сохранения.
    if val is None or val.strip() == "":
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val not in (None, "") else default


def _get_float_opt(name: str) -> float | None:
    """Float или None, если переменная не задана (для «наследовать значение»)."""
    val = os.getenv(name)
    return float(val) if val not in (None, "") else None


def _get_int_opt(name: str) -> int | None:
    val = os.getenv(name)
    return int(val) if val not in (None, "") else None


# Разумные дефолты DCA под крупные акции. Они МЕНЕЕ волатильны, чем крипта
# (1–2% в день против 3–8%), поэтому шаг просадки и тейк-профит теснее. Плюс
# страховочный стоп-лосс на цикл — отдельные акции бывают необратимо падают,
# поэтому ограничиваем убыток (для крипты по умолчанию выключен). Перекрываются
# ALPACA_DCA_*.
STOCK_DCA_DEFAULTS = {
    "base_order": 25.0,
    "safety_order": 25.0,
    "max_safety_orders": 4,
    "price_deviation_pct": 1.5,
    "take_profit_pct": 2.0,
    "stop_loss_pct": 12.0,
}


def _get_int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val not in (None, "") else default


def _resolve_keys(testnet: bool) -> tuple[str, str]:
    """Возвращает (api_key, api_secret) под нужную сеть.

    Боевые ключи: BINANCE_API_KEY / BINANCE_API_SECRET.
    Тестовые:     BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET
                  (если пустые — откат на BINANCE_API_KEY для совместимости).
    """
    if testnet:
        key = os.getenv("BINANCE_TESTNET_API_KEY") or os.getenv("BINANCE_API_KEY", "")
        sec = os.getenv("BINANCE_TESTNET_API_SECRET") or os.getenv("BINANCE_API_SECRET", "")
        return key, sec
    return os.getenv("BINANCE_API_KEY", ""), os.getenv("BINANCE_API_SECRET", "")


def _split_csv(raw: str) -> list[str]:
    """Список символов через запятую, в верхнем регистре, без дублей."""
    syms = [s.strip().upper() for s in (raw or "").split(",") if s.strip()]
    seen: set[str] = set()
    return [s for s in syms if not (s in seen or seen.add(s))]


def _get_symbols() -> list[str]:
    """Список пар. SYMBOLS (через запятую) имеет приоритет над SYMBOL."""
    raw = os.getenv("SYMBOLS") or os.getenv("SYMBOL") or "BTCUSDT"
    syms = [s.strip().upper() for s in raw.split(",") if s.strip()]
    # Убираем дубликаты, сохраняя порядок.
    seen: set[str] = set()
    return [s for s in syms if not (s in seen or seen.add(s))]


@dataclass
class Config:
    api_key: str
    api_secret: str
    dry_run: bool
    testnet: bool

    strategy: str  # "swing" или "dca"

    symbols: list[str]  # список торгуемых пар (мульти-монета)
    interval: str
    trade_quote_amount: float

    stop_loss_pct: float
    take_profit_pct: float

    fast_ma: int
    slow_ma: int
    rsi_period: int
    rsi_overbought: float
    rsi_oversold: float

    # Параметры DCA-стратегии
    dca_base_order: float
    dca_safety_order: float
    dca_max_safety_orders: int
    dca_price_deviation_pct: float
    dca_safety_step_scale: float
    dca_safety_volume_scale: float
    dca_take_profit_pct: float

    # Комиссия биржи (для расчёта реализованной прибыли)
    fee_pct: float

    # Вывод части прибыли на внешний кошелёк
    withdraw_enabled: bool
    withdraw_profit_pct: float
    withdraw_min_amount: float
    withdraw_asset: str
    withdraw_network: str
    withdraw_address: str

    # Веб-дашборд
    dashboard_port: int

    # Адаптивный режим: смена поведения под рынок + оптимизация параметров
    adaptive_enabled: bool
    adaptive_optimize: bool
    regime_interval: str
    regime_lookback: int
    reoptimize_every: int
    trend_tp_multiplier: float
    regime_slope_pct: float
    regime_high_vol_pct: float

    poll_interval_seconds: int

    # Стоп-лосс на цикл DCA: продать всю позицию, если цена ниже средней входа на
    # столько %. 0 = выключено. Должен быть ШИРЕ суммарного покрытия докупок.
    dca_stop_loss_pct: float = 0.0

    # ATR-привязка шага/тейк-профита: вместо фиксированных % шаг и цель считаются
    # от недавней волатильности (среднее абсолютное изменение закрытий, %).
    # Работает, только когда адаптивный режим ВЫКЛ. Перекрывает price_deviation/TP.
    dca_atr_enabled: bool = False
    dca_atr_period: int = 14
    dca_atr_step_mult: float = 1.0
    dca_atr_tp_mult: float = 1.5
    dca_atr_min_pct: float = 0.5
    dca_atr_max_pct: float = 8.0

    # Брокеры. Binance — крипта, Alpaca — акции (можно оба сразу).
    binance_enabled: bool = True
    alpaca_enabled: bool = False
    alpaca_paper: bool = True
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_symbols: list[str] = field(default_factory=list)
    alpaca_trade_quote_amount: float = 1000.0
    # Отдельные DCA-параметры под акции (None = наследовать крипто-значение).
    alpaca_dca_base_order: float | None = None
    alpaca_dca_safety_order: float | None = None
    alpaca_dca_max_safety_orders: int | None = None
    alpaca_dca_price_deviation_pct: float | None = None
    alpaca_dca_take_profit_pct: float | None = None
    alpaca_dca_stop_loss_pct: float | None = None

    @classmethod
    def load(cls) -> "Config":
        testnet = _get_bool("TESTNET", True)
        api_key, api_secret = _resolve_keys(testnet)
        cfg = cls(
            api_key=api_key,
            api_secret=api_secret,
            dry_run=_get_bool("DRY_RUN", True),
            testnet=testnet,
            strategy=os.getenv("STRATEGY", "dca").lower(),
            symbols=_get_symbols(),
            interval=os.getenv("INTERVAL", "15m"),
            trade_quote_amount=_get_float("TRADE_QUOTE_AMOUNT", 250.0),
            stop_loss_pct=_get_float("STOP_LOSS_PCT", 2.0),
            take_profit_pct=_get_float("TAKE_PROFIT_PCT", 4.0),
            fast_ma=_get_int("FAST_MA", 9),
            slow_ma=_get_int("SLOW_MA", 21),
            rsi_period=_get_int("RSI_PERIOD", 14),
            rsi_overbought=_get_float("RSI_OVERBOUGHT", 70.0),
            rsi_oversold=_get_float("RSI_OVERSOLD", 30.0),
            dca_base_order=_get_float("DCA_BASE_ORDER", 30.0),
            dca_safety_order=_get_float("DCA_SAFETY_ORDER", 30.0),
            dca_max_safety_orders=_get_int("DCA_MAX_SAFETY_ORDERS", 5),
            dca_price_deviation_pct=_get_float("DCA_PRICE_DEVIATION_PCT", 2.5),
            dca_safety_step_scale=_get_float("DCA_SAFETY_STEP_SCALE", 1.0),
            dca_safety_volume_scale=_get_float("DCA_SAFETY_VOLUME_SCALE", 1.0),
            dca_take_profit_pct=_get_float("DCA_TAKE_PROFIT_PCT", 3.0),
            fee_pct=_get_float("FEE_PCT", 0.1),
            withdraw_enabled=_get_bool("WITHDRAW_ENABLED", False),
            withdraw_profit_pct=_get_float("WITHDRAW_PROFIT_PCT", 10.0),
            withdraw_min_amount=_get_float("WITHDRAW_MIN_AMOUNT", 15.0),
            withdraw_asset=os.getenv("WITHDRAW_ASSET", "USDT").upper(),
            withdraw_network=os.getenv("WITHDRAW_NETWORK", "TRX").upper(),
            withdraw_address=os.getenv("WITHDRAW_ADDRESS", "").strip(),
            dashboard_port=_get_int("DASHBOARD_PORT", 8000),
            adaptive_enabled=_get_bool("ADAPTIVE_ENABLED", False),
            adaptive_optimize=_get_bool("ADAPTIVE_OPTIMIZE", True),
            regime_interval=os.getenv("REGIME_INTERVAL", "1h"),
            regime_lookback=_get_int("REGIME_LOOKBACK", 500),
            reoptimize_every=_get_int("REOPTIMIZE_EVERY", 50),
            trend_tp_multiplier=_get_float("TREND_TP_MULTIPLIER", 1.5),
            regime_slope_pct=_get_float("REGIME_SLOPE_PCT", 0.6),
            regime_high_vol_pct=_get_float("REGIME_HIGH_VOL_PCT", 2.5),
            poll_interval_seconds=_get_int("POLL_INTERVAL_SECONDS", 60),
            binance_enabled=_get_bool("BINANCE_ENABLED", True),
            alpaca_enabled=_get_bool("ALPACA_ENABLED", False),
            alpaca_paper=_get_bool("ALPACA_PAPER", True),
            alpaca_api_key=os.getenv("APCA_API_KEY_ID", "").strip(),
            alpaca_api_secret=os.getenv("APCA_API_SECRET_KEY", "").strip(),
            alpaca_symbols=_split_csv(os.getenv("ALPACA_SYMBOLS", "")),
            alpaca_trade_quote_amount=_get_float("ALPACA_TRADE_QUOTE_AMOUNT", 1000.0),
            alpaca_dca_base_order=_get_float_opt("ALPACA_DCA_BASE_ORDER"),
            alpaca_dca_safety_order=_get_float_opt("ALPACA_DCA_SAFETY_ORDER"),
            alpaca_dca_max_safety_orders=_get_int_opt("ALPACA_DCA_MAX_SAFETY_ORDERS"),
            alpaca_dca_price_deviation_pct=_get_float_opt("ALPACA_DCA_PRICE_DEVIATION_PCT"),
            alpaca_dca_take_profit_pct=_get_float_opt("ALPACA_DCA_TAKE_PROFIT_PCT"),
            alpaca_dca_stop_loss_pct=_get_float_opt("ALPACA_DCA_STOP_LOSS_PCT"),
            dca_stop_loss_pct=_get_float("DCA_STOP_LOSS_PCT", 0.0),
            dca_atr_enabled=_get_bool("DCA_ATR_ENABLED", False),
            dca_atr_period=_get_int("DCA_ATR_PERIOD", 14),
            dca_atr_step_mult=_get_float("DCA_ATR_STEP_MULT", 1.0),
            dca_atr_tp_mult=_get_float("DCA_ATR_TP_MULT", 1.5),
            dca_atr_min_pct=_get_float("DCA_ATR_MIN_PCT", 0.5),
            dca_atr_max_pct=_get_float("DCA_ATR_MAX_PCT", 8.0),
        )
        cfg.validate()
        return cfg

    def for_alpaca(self) -> "Config":
        """Производный конфиг для DCA-трейдера на Alpaca: акции, свои символы,
        бюджет и DCA-параметры. Пусто (ALPACA_DCA_* не задано) → разумные дефолты
        под акции (STOCK_DCA_DEFAULTS), а не крипто-значения. paper → testnet."""
        d = STOCK_DCA_DEFAULTS
        def pick(opt, default):
            return default if opt is None else opt
        derived = replace(
            self,
            symbols=self.alpaca_symbols or ["SPY", "QQQ"],
            trade_quote_amount=self.alpaca_trade_quote_amount,
            fee_pct=0.0,
            dry_run=False,
            testnet=self.alpaca_paper,
            api_key=self.alpaca_api_key,
            api_secret=self.alpaca_api_secret,
            withdraw_enabled=False,
            dca_base_order=pick(self.alpaca_dca_base_order, d["base_order"]),
            dca_safety_order=pick(self.alpaca_dca_safety_order, d["safety_order"]),
            dca_max_safety_orders=pick(self.alpaca_dca_max_safety_orders, d["max_safety_orders"]),
            dca_price_deviation_pct=pick(self.alpaca_dca_price_deviation_pct, d["price_deviation_pct"]),
            dca_take_profit_pct=pick(self.alpaca_dca_take_profit_pct, d["take_profit_pct"]),
            dca_stop_loss_pct=pick(self.alpaca_dca_stop_loss_pct, d["stop_loss_pct"]),
        )
        derived.validate()  # поймать перебор бюджета/символов до старта
        return derived

    @property
    def symbol(self) -> str:
        """Первая пара — для совместимости и заголовков."""
        return self.symbols[0]

    def validate(self) -> None:
        if self.strategy not in {"swing", "dca"}:
            raise ValueError("STRATEGY должна быть 'swing' или 'dca'")
        if not self.symbols:
            raise ValueError("Не задана ни одна торговая пара (SYMBOL / SYMBOLS)")
        if self.fast_ma >= self.slow_ma:
            raise ValueError("FAST_MA должна быть меньше SLOW_MA")
        if self.trade_quote_amount <= 0:
            raise ValueError("TRADE_QUOTE_AMOUNT должна быть положительной")
        if self.strategy == "dca":
            if self.dca_base_order <= 0 or self.dca_safety_order < 0:
                raise ValueError("DCA_BASE_ORDER должен быть > 0, DCA_SAFETY_ORDER >= 0")
            # Каждая монета может задействовать полный бюджет цикла независимо,
            # поэтому суммарная экспозиция = бюджет цикла × число монет.
            total = self.max_dca_budget() * len(self.symbols)
            if total > self.trade_quote_amount:
                raise ValueError(
                    f"Суммарный бюджет DCA на {len(self.symbols)} монет(ы) = "
                    f"{total:.2f} USDT превышает TRADE_QUOTE_AMOUNT "
                    f"({self.trade_quote_amount:.2f}). Уменьши размеры ордеров, число "
                    "safety-ордеров или количество монет."
                )
        # Реальные ордера невозможны без ключей.
        if not self.dry_run and (not self.api_key or not self.api_secret):
            raise ValueError(
                "Для боевой торговли (DRY_RUN=false) нужны BINANCE_API_KEY и BINANCE_API_SECRET"
            )
        if self.withdraw_enabled and not self.withdraw_address:
            raise ValueError(
                "WITHDRAW_ENABLED=true, но не задан WITHDRAW_ADDRESS (адрес кошелька)"
            )
        if self.reoptimize_every <= 0:
            raise ValueError("REOPTIMIZE_EVERY должен быть > 0")

    def max_dca_budget(self) -> float:
        """Максимально возможные вложения за один цикл DCA (база + все safety-ордера)."""
        total = self.dca_base_order
        size = self.dca_safety_order
        for _ in range(self.dca_max_safety_orders):
            total += size
            size *= self.dca_safety_volume_scale
        return total
