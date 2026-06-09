"""Движок «умного» DCA (Dollar-Cost Averaging) — как у популярных DCA-ботов.

Идея цикла:
  1. БАЗОВЫЙ ОРДЕР — первая покупка на сумму base_order.
  2. SAFETY-ОРДЕРА — докупки при просадке цены на price_deviation% от цены
     последней покупки. Каждая докупка снижает среднюю цену входа.
  3. ТЕЙК-ПРОФИТ — когда цена поднимается на take_profit% выше СРЕДНЕЙ цены
     входа, продаём весь объём и начинаем цикл заново.

Шаги и объёмы safety-ордеров можно масштабировать (step_scale / volume_scale),
чтобы докупать «реже, но больше» при углублении просадки.

Класс хранит только состояние позиции и не знает про сеть — поэтому одинаково
работает и в живом боте, и в бэктесте.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class Action(Enum):
    BUY = "BUY"
    SELL_ALL = "SELL_ALL"


@dataclass
class DcaParams:
    base_order: float
    safety_order: float
    max_safety_orders: int
    price_deviation_pct: float
    safety_step_scale: float
    safety_volume_scale: float
    take_profit_pct: float
    stop_loss_pct: float = 0.0  # выход из цикла при просадке ниже средней; 0 = выкл


@dataclass
class DcaState:
    qty: float = 0.0           # суммарно куплено базовой валюты (BTC)
    spent: float = 0.0         # суммарно потрачено котируемой (USDT)
    safety_filled: int = 0     # сколько safety-ордеров уже исполнено
    next_safety_price: float = 0.0  # цена, ниже которой сработает следующая докупка

    @property
    def in_position(self) -> bool:
        return self.qty > 0

    @property
    def avg_entry(self) -> float:
        return self.spent / self.qty if self.qty > 0 else 0.0


@dataclass
class Order:
    """Намерение торговать. quote — сумма в USDT для покупки (для SELL_ALL не нужна)."""
    action: Action
    quote: float = 0.0
    reason: str = ""


class DcaEngine:
    def __init__(self, params: DcaParams, state: DcaState | None = None):
        self.p = params
        self.state = state or DcaState()

    # ── Решение на основе текущей цены ─────────────────────────────────
    def decide(self, price: float) -> Order | None:
        s, p = self.state, self.p
        if not s.in_position:
            return Order(Action.BUY, quote=p.base_order, reason="базовый ордер")

        # Тейк-профит имеет приоритет.
        if price >= s.avg_entry * (1 + p.take_profit_pct / 100):
            return Order(Action.SELL_ALL, reason=f"тейк-профит {p.take_profit_pct}%")

        # Стоп-лосс на цикл: режем убыток, если цена ушла слишком глубоко вниз.
        if p.stop_loss_pct > 0 and price <= s.avg_entry * (1 - p.stop_loss_pct / 100):
            return Order(Action.SELL_ALL, reason=f"стоп-лосс {p.stop_loss_pct:g}%")

        # Safety-ордер при достаточной просадке.
        if s.safety_filled < p.max_safety_orders and price <= s.next_safety_price:
            size = p.safety_order * (p.safety_volume_scale ** s.safety_filled)
            return Order(Action.BUY, quote=size,
                         reason=f"safety-ордер #{s.safety_filled + 1}")
        return None

    # ── Применение исполненного ордера к состоянию ─────────────────────
    def apply_buy(self, price: float, quote_spent: float, qty_filled: float) -> None:
        s, p = self.state, self.p
        is_base = not s.in_position
        s.qty += qty_filled
        s.spent += quote_spent
        if not is_base:
            s.safety_filled += 1
        # Следующая докупка — ещё ниже от ЭТОЙ цены, с учётом масштаба шага.
        step = p.price_deviation_pct * (p.safety_step_scale ** s.safety_filled)
        s.next_safety_price = price * (1 - step / 100)

    def apply_sell_all(self) -> None:
        self.state = DcaState()

    # ── Сериализация состояния ─────────────────────────────────────────
    def state_dict(self) -> dict:
        return asdict(self.state)

    @classmethod
    def from_state_dict(cls, params: DcaParams, data: dict) -> "DcaEngine":
        # Игнорируем лишние ключи на случай миграции формата.
        known = {f for f in DcaState.__dataclass_fields__}
        return cls(params, DcaState(**{k: v for k, v in data.items() if k in known}))


def simulate_dca(closes: list[float], params: DcaParams, start_cash: float,
                 fee_pct: float = 0.1) -> dict:
    """Прогон DCA по списку цен. Возвращает метрики для бэктеста/оптимизатора.

    Метрики: final (итоговый капитал), pnl_pct, cycles, wins, max_drawdown_pct.
    Капитал считается как свободные деньги + стоимость открытой позиции, поэтому
    кривая отражает и просадку по незакрытой позиции.
    """
    engine = DcaEngine(params)
    cash = start_cash
    cycles = 0
    wins = 0
    peak = start_cash
    max_dd = 0.0

    for price in closes:
        order = engine.decide(price)
        if order is not None:
            if order.action == Action.BUY:
                spend = min(order.quote, cash)
                if spend > 0:
                    qty = (spend * (1 - fee_pct / 100)) / price
                    cash -= spend
                    engine.apply_buy(price, spend, qty)
            elif order.action == Action.SELL_ALL:
                s = engine.state
                cash += s.qty * price * (1 - fee_pct / 100)
                cycles += 1
                if price > s.avg_entry:
                    wins += 1
                engine.apply_sell_all()
        # Отслеживаем просадку по полному капиталу (кэш + позиция).
        equity = cash + engine.state.qty * price
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100)

    final = cash + engine.state.qty * (closes[-1] if closes else 0)
    return {
        "final": final,
        "pnl_pct": (final / start_cash - 1) * 100 if start_cash else 0.0,
        "cycles": cycles,
        "wins": wins,
        "max_drawdown_pct": max_dd,
    }

