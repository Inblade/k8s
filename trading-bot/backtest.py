"""Бэктест стратегии на исторических свечах Binance (без ключей, публичные данные).

Запуск:
    python backtest.py BTCUSDT 1h 1000

Показывает, как стратегия отработала бы на прошлых данных. ВАЖНО: хорошие
результаты на истории НЕ гарантируют прибыль в будущем (overfitting, комиссии,
проскальзывание). Это лишь инструмент для понимания поведения.
"""
from __future__ import annotations

import sys

from binance.client import Client

from config import Config
from strategy import Signal, compute_indicators, decide

FEE_PCT = 0.1  # комиссия Binance ~0.1% на сделку


def run_backtest(symbol: str, interval: str, limit: int) -> None:
    cfg = Config.load()
    client = Client()  # публичные данные, ключи не нужны
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    closes = [float(k[4]) for k in klines]

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
    pnl = (final / start_cash - 1) * 100
    winrate = (wins / trades * 100) if trades else 0.0

    print(f"\nБэктест {symbol} {interval}, свечей: {len(closes)}")
    print(f"Стартовый капитал: {start_cash:.2f} USDT")
    print(f"Итоговый капитал:  {final:.2f} USDT")
    print(f"Результат:         {pnl:+.2f}%")
    print(f"Сделок:            {trades} (прибыльных {wins}, winrate {winrate:.1f}%)")
    print("\n⚠️  Прошлые результаты не гарантируют будущую прибыль.")


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    itv = sys.argv[2] if len(sys.argv) > 2 else "1h"
    lim = int(sys.argv[3]) if len(sys.argv) > 3 else 1000
    run_backtest(sym, itv, lim)
