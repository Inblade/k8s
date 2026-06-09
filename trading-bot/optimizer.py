"""Подбор параметров DCA по свежей истории (walk-forward оптимизация).

«Обучение на лучших»: перебираем набор разумных параметров, прогоняем каждый на
последних N свечах функцией simulate_dca и выбираем лучший по риск-скорректированной
метрике (доходность минус штраф за просадку).

⚠️ ЧЕСТНОЕ ПРЕДУПРЕЖДЕНИЕ: это подгонка под прошлые данные (curve fitting). То, что
было лучшим вчера, не обязано быть лучшим завтра. Поэтому:
  * перебор ограничен узким безопасным диапазоном;
  * метрика штрафует за просадку, а не гонится за максимумом доходности;
  * результат применяется только в пределах заданных границ.
"""
from __future__ import annotations

import logging
from dataclasses import replace

from dca import DcaParams, simulate_dca

log = logging.getLogger("bot.optimizer")

# Узкие безопасные сетки значений для перебора.
TP_GRID = [1.5, 2.0, 3.0, 4.0]
DEVIATION_GRID = [1.5, 2.5, 4.0]
MAX_SAFETY_GRID = [3, 5]


def _score(metrics: dict) -> float:
    """Риск-скорректированная оценка: доходность со штрафом за просадку."""
    return metrics["pnl_pct"] - 0.5 * metrics["max_drawdown_pct"]


def optimize(closes: list[float], base: DcaParams, start_cash: float,
             fee_pct: float = 0.1) -> tuple[DcaParams, dict]:
    """Возвращает (лучшие_параметры, метрики). Меняем только TP, шаг докупки и
    число safety-ордеров — размеры ордеров оставляем как в конфиге (бюджет)."""
    best_params = base
    best_metrics = simulate_dca(closes, base, start_cash, fee_pct)
    best_score = _score(best_metrics)

    for tp in TP_GRID:
        for dev in DEVIATION_GRID:
            for ms in MAX_SAFETY_GRID:
                cand = replace(base, take_profit_pct=tp,
                               price_deviation_pct=dev, max_safety_orders=ms)
                m = simulate_dca(closes, cand, start_cash, fee_pct)
                # Требуем хотя бы пару закрытых циклов, чтобы не выбрать «пустышку».
                if m["cycles"] < 2:
                    continue
                sc = _score(m)
                if sc > best_score:
                    best_score, best_params, best_metrics = sc, cand, m

    log.info("Оптимизация: TP=%.1f дев=%.1f safety=%d | доходность=%.2f%% "
             "просадка=%.2f%% циклов=%d",
             best_params.take_profit_pct, best_params.price_deviation_pct,
             best_params.max_safety_orders, best_metrics["pnl_pct"],
             best_metrics["max_drawdown_pct"], best_metrics["cycles"])
    return best_params, best_metrics
