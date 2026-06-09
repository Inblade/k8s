"""Адаптивный контроллер: меняет поведение DCA под режим рынка и подбирает
параметры на свежей истории.

Правила под режим:
  * боковик (RANGE)       → обычный DCA (он для боковика и создан);
  * тренд вверх (TREND_UP)→ выше тейк-профит (даём прибыли «бежать»);
  * тренд вниз (TREND_DOWN) или высокая волатильность → НОВЫЕ входы на паузе
    (не ловим падающий нож), но открытая позиция продолжает управляться.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from pathlib import Path

from config import Config
from dca import DcaParams
from exchange import Exchange
from optimizer import optimize
from regime import Regime, RegimeInfo, detect_regime

log = logging.getLogger("bot.adaptive")

STATE_FILE = Path(__file__).with_name("adaptive_state.json")


@dataclass
class Decision:
    allow_new_entry: bool
    params: DcaParams
    info: RegimeInfo


def base_params(cfg: Config) -> DcaParams:
    return DcaParams(
        base_order=cfg.dca_base_order,
        safety_order=cfg.dca_safety_order,
        max_safety_orders=cfg.dca_max_safety_orders,
        price_deviation_pct=cfg.dca_price_deviation_pct,
        safety_step_scale=cfg.dca_safety_step_scale,
        safety_volume_scale=cfg.dca_safety_volume_scale,
        take_profit_pct=cfg.dca_take_profit_pct,
        stop_loss_pct=cfg.dca_stop_loss_pct,  # сохраняем стоп-лосс и в адаптиве
    )


class AdaptiveController:
    def __init__(self, cfg: Config, exchange: Exchange):
        self.cfg = cfg
        self.ex = exchange
        self.base = base_params(cfg)
        self.counter = 0
        # Оптимизированные параметры по монетам: {symbol: {tp,dev,ms}}.
        self.optimized: dict[str, dict] = {}
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text())
            self.counter = data.get("counter", 0)
            self.optimized = data.get("optimized", {})

    def _save(self) -> None:
        STATE_FILE.write_text(json.dumps({"counter": self.counter, "optimized": self.optimized}))

    def _stored_params(self, symbol: str) -> DcaParams:
        o = self.optimized.get(symbol)
        if not o:
            return self.base
        return replace(self.base, take_profit_pct=o["tp"],
                       price_deviation_pct=o["dev"], max_safety_orders=o["ms"])

    def _maybe_optimize(self, symbol: str, closes: list[float]) -> None:
        if not self.cfg.adaptive_optimize:
            return
        first_time = symbol not in self.optimized
        due = self.counter % self.cfg.reoptimize_every == 0
        if not (first_time or due):
            return
        budget = self.cfg.max_dca_budget()
        best, _ = optimize(closes, self.base, start_cash=budget, fee_pct=self.cfg.fee_pct)
        self.optimized[symbol] = {
            "tp": best.take_profit_pct,
            "dev": best.price_deviation_pct,
            "ms": best.max_safety_orders,
        }

    def update(self, symbol: str, closes: list[float]) -> Decision:
        """Принимает свежие свечи монеты и выдаёт решение по поведению."""
        self.counter += 1
        self._maybe_optimize(symbol, closes)

        info = detect_regime(
            closes,
            slope_threshold_pct=self.cfg.regime_slope_pct,
            high_vol_pct=self.cfg.regime_high_vol_pct,
        )
        params = self._stored_params(symbol)
        allow_new_entry = True

        if info.regime == Regime.TREND_DOWN or info.high_volatility:
            allow_new_entry = False
        elif info.regime == Regime.TREND_UP:
            params = replace(params,
                             take_profit_pct=params.take_profit_pct * self.cfg.trend_tp_multiplier)

        self._save()
        return Decision(allow_new_entry, params, info)
