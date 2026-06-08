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


@dataclass
class Config:
    api_key: str
    api_secret: str
    dry_run: bool
    testnet: bool

    symbol: str
    interval: str
    trade_quote_amount: float

    stop_loss_pct: float
    take_profit_pct: float

    fast_ma: int
    slow_ma: int
    rsi_period: int
    rsi_overbought: float
    rsi_oversold: float

    poll_interval_seconds: int

    @classmethod
    def load(cls) -> "Config":
        cfg = cls(
            api_key=os.getenv("BINANCE_API_KEY", ""),
            api_secret=os.getenv("BINANCE_API_SECRET", ""),
            dry_run=_get_bool("DRY_RUN", True),
            testnet=_get_bool("TESTNET", True),
            symbol=os.getenv("SYMBOL", "BTCUSDT").upper(),
            interval=os.getenv("INTERVAL", "15m"),
            trade_quote_amount=_get_float("TRADE_QUOTE_AMOUNT", 250.0),
            stop_loss_pct=_get_float("STOP_LOSS_PCT", 2.0),
            take_profit_pct=_get_float("TAKE_PROFIT_PCT", 4.0),
            fast_ma=_get_int("FAST_MA", 9),
            slow_ma=_get_int("SLOW_MA", 21),
            rsi_period=_get_int("RSI_PERIOD", 14),
            rsi_overbought=_get_float("RSI_OVERBOUGHT", 70.0),
            rsi_oversold=_get_float("RSI_OVERSOLD", 30.0),
            poll_interval_seconds=_get_int("POLL_INTERVAL_SECONDS", 60),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.fast_ma >= self.slow_ma:
            raise ValueError("FAST_MA должна быть меньше SLOW_MA")
        if self.trade_quote_amount <= 0:
            raise ValueError("TRADE_QUOTE_AMOUNT должна быть положительной")
        # Реальные ордера невозможны без ключей.
        if not self.dry_run and (not self.api_key or not self.api_secret):
            raise ValueError(
                "Для боевой торговли (DRY_RUN=false) нужны BINANCE_API_KEY и BINANCE_API_SECRET"
            )
