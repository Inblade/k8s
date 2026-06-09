"""Загрузка и валидация конфигурации из переменных окружения / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val not in (None, "") else default


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
        )
        cfg.validate()
        return cfg

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
