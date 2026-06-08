"""Вывод части прибыли на внешний кошелёк (например, TrustWallet).

Логика «копилки»: при каждом закрытии цикла с прибылью бот откладывает
WITHDRAW_PROFIT_PCT% от прибыли в резерв. Когда резерв достигает безопасного
минимума (WITHDRAW_MIN_AMOUNT — чтобы вывод не съелся комиссией сети), бот
выводит накопленное на указанный адрес.

⚠️ Требует у API-ключа права на вывод средств. Включается явно: WITHDRAW_ENABLED.
По умолчанию выключено и в любом случае ничего не выводит без адреса.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from config import Config
from exchange import Exchange

log = logging.getLogger("bot.withdraw")

STATE_FILE = Path(__file__).with_name("withdraw_state.json")


@dataclass
class WithdrawState:
    reserve: float = 0.0            # накоплено к выводу, USDT
    withdrawn_total: float = 0.0    # всего выведено, USDT
    realized_pnl_total: float = 0.0  # суммарная реализованная прибыль (для статистики)


class ProfitWithdrawer:
    def __init__(self, cfg: Config, exchange: Exchange):
        self.cfg = cfg
        self.ex = exchange
        self.state = self._load()

    def _load(self) -> WithdrawState:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text())
            known = set(WithdrawState.__dataclass_fields__)
            return WithdrawState(**{k: v for k, v in data.items() if k in known})
        return WithdrawState()

    def _save(self) -> None:
        STATE_FILE.write_text(json.dumps(asdict(self.state)))

    # Вызывается при закрытии цикла с реализованным результатом (USDT, может быть < 0).
    def on_realized_profit(self, profit_usdt: float) -> None:
        self.state.realized_pnl_total += profit_usdt
        if profit_usdt > 0 and self.cfg.withdraw_profit_pct > 0:
            self.state.reserve += profit_usdt * self.cfg.withdraw_profit_pct / 100
            log.info("В резерв вывода отложено %.2f USDT (всего в резерве %.2f)",
                     profit_usdt * self.cfg.withdraw_profit_pct / 100, self.state.reserve)
        self._maybe_withdraw()
        self._save()

    def _maybe_withdraw(self) -> None:
        if not self.cfg.withdraw_enabled:
            return
        if self.state.reserve < self.cfg.withdraw_min_amount:
            return
        # Округляем ВНИЗ до 2 знаков, чтобы не вывести больше накопленного.
        amount = math.floor(self.state.reserve * 100) / 100
        try:
            self.ex.withdraw(self.cfg.withdraw_asset, self.cfg.withdraw_network,
                             self.cfg.withdraw_address, amount)
            self.state.reserve -= amount
            self.state.withdrawn_total += amount
            log.info("💸 Выведено %.2f %s на %s (%s). Всего выведено: %.2f",
                     amount, self.cfg.withdraw_asset, self.cfg.withdraw_address[:10] + "…",
                     self.cfg.withdraw_network, self.state.withdrawn_total)
        except Exception as exc:  # noqa: BLE001 — сбой вывода не должен ронять бота
            log.error("Не удалось вывести средства: %s (резерв сохранён, попробую позже)", exc)
