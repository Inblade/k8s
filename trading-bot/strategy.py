"""Торговая стратегия: пересечение скользящих средних с фильтром по RSI.

Логика проста и прозрачна:
  * Сигнал на ПОКУПКУ  — быстрая MA пересекает медленную снизу вверх
                         И RSI не в зоне перекупленности.
  * Сигнал на ПРОДАЖУ  — быстрая MA пересекает медленную сверху вниз.

Дополнительно позиция закрывается по стоп-лоссу / тейк-профиту — это считается
в trader.py, а не здесь.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Indicators:
    fast_ma: float
    slow_ma: float
    prev_fast_ma: float
    prev_slow_ma: float
    rsi: float
    last_price: float


def sma(values: list[float], period: int) -> float:
    """Простая скользящая средняя по последним `period` значениям."""
    if len(values) < period:
        raise ValueError("Недостаточно данных для SMA")
    return sum(values[-period:]) / period


def rsi(closes: list[float], period: int) -> float:
    """Классический RSI (Wilder smoothing)."""
    if len(closes) < period + 1:
        raise ValueError("Недостаточно данных для RSI")

    gains, losses = 0.0, 0.0
    # Первичное среднее по первому окну.
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period

    # Сглаживание по остальным точкам.
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_indicators(
    closes: list[float], fast_period: int, slow_period: int, rsi_period: int
) -> Indicators:
    return Indicators(
        fast_ma=sma(closes, fast_period),
        slow_ma=sma(closes, slow_period),
        prev_fast_ma=sma(closes[:-1], fast_period),
        prev_slow_ma=sma(closes[:-1], slow_period),
        rsi=rsi(closes, rsi_period),
        last_price=closes[-1],
    )


def decide(ind: Indicators, rsi_overbought: float, rsi_oversold: float) -> Signal:
    crossed_up = ind.prev_fast_ma <= ind.prev_slow_ma and ind.fast_ma > ind.slow_ma
    crossed_down = ind.prev_fast_ma >= ind.prev_slow_ma and ind.fast_ma < ind.slow_ma

    if crossed_up and ind.rsi < rsi_overbought:
        return Signal.BUY
    if crossed_down:
        return Signal.SELL
    return Signal.HOLD
