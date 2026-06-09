"""Определение режима рынка по ценам закрытия: тренд вверх / вниз / боковик.

Без претензий на магию: это простые, проверенные индикаторы (наклон EMA и
волатильность). Они запаздывают и иногда ошибаются — поэтому используются только
как фильтр поведения, а не как «предсказание».
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from enum import Enum


class Regime(Enum):
    TREND_UP = "тренд вверх"
    TREND_DOWN = "тренд вниз"
    RANGE = "боковик"


@dataclass
class RegimeInfo:
    regime: Regime
    trend_pct: float       # положение быстрой EMA относительно медленной, %
    slope_pct: float       # наклон медленной EMA за окно, %
    volatility_pct: float  # волатильность (стд. откл. доходностей), %
    high_volatility: bool


def ema(values: list[float], period: int) -> list[float]:
    """Экспоненциальная скользящая средняя (полный ряд)."""
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def detect_regime(
    closes: list[float],
    fast: int = 20,
    slow: int = 50,
    slope_window: int = 10,
    slope_threshold_pct: float = 0.6,
    high_vol_pct: float = 2.5,
) -> RegimeInfo:
    """Классифицирует режим. slope_threshold_pct — порог наклона за окно (в %).

    high_vol_pct — порог волатильности (стд. откл. доходностей в %), выше которого
    рынок считается «опасно волатильным».
    """
    if len(closes) < slow + slope_window + 1:
        # Данных мало — считаем боковиком (самый осторожный режим для DCA).
        return RegimeInfo(Regime.RANGE, 0.0, 0.0, 0.0, False)

    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)

    trend_pct = (ema_fast[-1] - ema_slow[-1]) / ema_slow[-1] * 100
    prev = ema_slow[-1 - slope_window]
    slope_pct = (ema_slow[-1] - prev) / prev * 100 if prev else 0.0

    returns = [(closes[i] / closes[i - 1] - 1) * 100 for i in range(-slope_window, 0)]
    volatility = statistics.pstdev(returns) if len(returns) > 1 else 0.0
    high_vol = volatility >= high_vol_pct

    if slope_pct >= slope_threshold_pct and trend_pct > 0:
        regime = Regime.TREND_UP
    elif slope_pct <= -slope_threshold_pct and trend_pct < 0:
        regime = Regime.TREND_DOWN
    else:
        regime = Regime.RANGE

    return RegimeInfo(regime, trend_pct, slope_pct, volatility, high_vol)
