"""Бэктест стратегий на исторических свечах Binance (без ключей, публичные данные).

Запуск:
    python backtest.py swing BTCUSDT 1h 1000
    python backtest.py dca   BTCUSDT 1h 1000

(первый аргумент-стратегия необязателен — по умолчанию берётся STRATEGY из .env)

Показывает, как стратегия отработала бы на прошлых данных. ВАЖНО: хорошие
результаты на истории НЕ гарантируют прибыль в будущем (overfitting, комиссии,
проскальзывание). Это лишь инструмент для понимания поведения.
"""
from __future__ import annotations

import sys

from binance.client import Client

from config import Config
from dca import Action, DcaEngine
from dca_trader import params_from_config
from strategy import Signal, compute_indicators, decide

FEE_PCT = 0.1  # комиссия Binance ~0.1% на сделку


def fetch_closes(symbol: str, interval: str, limit: int) -> list[float]:
    client = Client()  # публичные данные, ключи не нужны
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    return [float(k[4]) for k in klines]


def _report(symbol: str, interval: str, n: int, start_cash: float, final: float,
            trades: int, wins: int) -> None:
    pnl = (final / start_cash - 1) * 100
    winrate = (wins / trades * 100) if trades else 0.0
    print(f"\nБэктест {symbol} {interval}, свечей: {n}")
    print(f"Стартовый капитал: {start_cash:.2f} USDT")
    print(f"Итоговый капитал:  {final:.2f} USDT")
    print(f"Результат:         {pnl:+.2f}%")
    print(f"Сделок/циклов:     {trades} (прибыльных {wins}, winrate {winrate:.1f}%)")
    print("\n⚠️  Прошлые результаты не гарантируют будущую прибыль.")


def run_swing_backtest(symbol: str, interval: str, limit: int) -> None:
    cfg = Config.load()
    closes = fetch_closes(symbol, interval, limit)

    warmup = max(cfg.slow_ma, cfg.rsi_period) + 2
    cash = cfg.trade_quote_amount
    start_cash = cash
    qty = 0.0
    entry = 0.0
    trades = 0
    wins = 0

    for i in range(warmup, len(closes)):
        window = closes[: i + 1]
        ind = compute_indicators(window, cfg.fast_ma, cfg.slow_ma, cfg.rsi_period)
        price = ind.last_price
        sig = decide(ind, cfg.rsi_overbought, cfg.rsi_oversold)

        if qty == 0 and sig == Signal.BUY:
            qty = (cash * (1 - FEE_PCT / 100)) / price
            entry = price
            cash = 0.0
        elif qty > 0:
            sl = entry * (1 - cfg.stop_loss_pct / 100)
            tp = entry * (1 + cfg.take_profit_pct / 100)
            exit_now = price <= sl or price >= tp or sig == Signal.SELL
            if exit_now:
                cash = qty * price * (1 - FEE_PCT / 100)
                trades += 1
                if price > entry:
                    wins += 1
                qty = 0.0

    final = cash if qty == 0 else qty * closes[-1]
    _report(symbol, interval, len(closes), start_cash, final, trades, wins)


def run_dca_backtest(symbol: str, interval: str, limit: int) -> None:
    cfg = Config.load()
    closes = fetch_closes(symbol, interval, limit)

    engine = DcaEngine(params_from_config(cfg))
    cash = cfg.trade_quote_amount
    start_cash = cash
    cycles = 0
    wins = 0

    for price in closes:
        order = engine.decide(price)
        if order is None:
            continue
        if order.action == Action.BUY:
            spend = min(order.quote, cash)
            if spend <= 0:  # бюджет исчерпан — ждём тейк-профит или просадку
                continue
            qty = (spend * (1 - FEE_PCT / 100)) / price
            cash -= spend
            engine.apply_buy(price, spend, qty)
        elif order.action == Action.SELL_ALL:
            s = engine.state
            cash += s.qty * price * (1 - FEE_PCT / 100)
            cycles += 1
            if price > s.avg_entry:
                wins += 1
            engine.apply_sell_all()

    # Незавершённый цикл оцениваем по последней цене (открытая позиция).
    open_value = engine.state.qty * closes[-1] if engine.state.in_position else 0.0
    final = cash + open_value
    _report(symbol, interval, len(closes), start_cash, final, cycles, wins)
    if engine.state.in_position:
        s = engine.state
        print(f"(на конец периода открыта позиция: {s.qty:.8f} @ средняя {s.avg_entry:.2f}, "
              f"safety {s.safety_filled}/{cfg.dca_max_safety_orders})")


if __name__ == "__main__":
    args = sys.argv[1:]
    strat = Config.load().strategy
    if args and args[0] in ("swing", "dca"):
        strat = args.pop(0)
    sym = args[0] if len(args) > 0 else "BTCUSDT"
    itv = args[1] if len(args) > 1 else "1h"
    lim = int(args[2]) if len(args) > 2 else 1000
    if strat == "dca":
        run_dca_backtest(sym, itv, lim)
    else:
        run_swing_backtest(sym, itv, lim)
