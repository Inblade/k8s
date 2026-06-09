"""Простая оценка волатильности по закрытиям — ATR-прокси для динамического шага.

Истинный ATR требует high/low; здесь берём среднее абсолютное изменение цены
закрытия за период (в %). Для дневных/часовых баров это близкий и достаточный
ориентир, не требующий запроса OHLC.
"""
from __future__ import annotations


def mean_abs_change_pct(closes: list[float], period: int = 14) -> float:
    """Среднее |изменение закрытия к закрытию| за последние `period` баров, в %."""
    if not closes or len(closes) < 2:
        return 0.0
    window = closes[-(period + 1):] if len(closes) > period + 1 else closes
    changes = [abs(window[i] / window[i - 1] - 1) * 100
               for i in range(1, len(window)) if window[i - 1] > 0]
    return sum(changes) / len(changes) if changes else 0.0


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
