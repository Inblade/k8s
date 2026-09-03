"""Бэктест стратегий на исторических свечах Binance (без ключей, публичные данные).

Запуск:
    python backtest.py swing BTCUSDT 1h 1000
    python backtest.py dca   BTCUSDT 1h 1000
    python backtest.py replay equity.csv        # по собственной записанной ленте

(первый аргумент-стратегия необязателен — по умолчанию берётся STRATEGY из .env)

Режим replay отличается принципиально: он берёт не свечи с биржи, а ту самую
ленту цен, которую бот реально видел (колонка price в equity.csv), и прогоняет
её дважды — как есть и через PriceGuard. Так видно, что именно фильтр выбросов
изменил бы в уже случившейся истории.

Показывает, как стратегия отработала бы на прошлых данных. ВАЖНО: хорошие
результаты на истории НЕ гарантируют прибыль в будущем (overfitting, комиссии,
проскальзывание). Это лишь инструмент для понимания поведения.
"""
from __future__ import annotations

import sys

from binance.client import Client

from config import Config
from dca import Action, DcaEngine, simulate_dca
from dca_trader import params_from_config
from exchange import PriceGuard, SuspectPrice
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


def load_recorded(path: str) -> list[float]:
    """Цены из журнала капитала (equity.csv): колонка price, по одной в минуту."""
    import csv
    with open(path, newline="", encoding="utf-8") as fh:
        return [float(row["price"]) for row in csv.DictReader(fh) if float(row["price"]) > 0]


def apply_guard(prices: list[float], cfg: Config, step: float = 60.0) -> tuple[list[float], int]:
    """Прогоняет ленту через фильтр. Возвращает принятые цены и число отвергнутых."""
    guard = PriceGuard(cfg.price_max_jump_pct, cfg.price_confirm_ticks,
                       cfg.price_stale_seconds)
    kept, rejected, t = [], 0, 0.0
    for price in prices:
        try:
            kept.append(guard.check("REPLAY", price, t))
        except SuspectPrice:
            rejected += 1
        t += step
    return kept, rejected


def run_replay(path: str) -> None:
    cfg = Config.load()
    raw = load_recorded(path)
    if not raw:
        print(f"В {path} нет пригодных цен.")
        return

    # Логи фильтра здесь не нужны: считаем отвергнутые тики сами.
    import logging
    logging.getLogger("bot.exchange").setLevel(logging.ERROR)

    kept, rejected = apply_guard(raw, cfg)
    params = params_from_config(cfg)
    start = cfg.max_dca_budget() + cfg.dca_base_order  # тот же старт для обоих

    before = simulate_dca(raw, params, start, FEE_PCT)
    after = simulate_dca(kept, params, start, FEE_PCT)

    print(f"\nПовтор по записанной ленте: {path}")
    print(f"Тиков: {len(raw)} | отвергнуто фильтром: {rejected} "
          f"({rejected / len(raw) * 100:.3f}%)")
    print(f"Фильтр: ±{cfg.price_max_jump_pct:.0f}% / {cfg.price_confirm_ticks} тик(ов)"
          if cfg.price_max_jump_pct > 0 else "Фильтр: ВЫКЛЮЧЕН")
    print(f"Стартовый капитал: {start:.2f} USDT\n")

    rows = [
        ("Итоговый капитал, USDT", "final", "{:.2f}"),
        ("Результат, %", "pnl_pct", "{:+.2f}"),
        ("Закрытых циклов", "cycles", "{:.0f}"),
        ("Прибыльных", "wins", "{:.0f}"),
        ("Макс. просадка, %", "max_drawdown_pct", "{:.2f}"),
    ]
    print(f"{'':24} {'как было':>12} {'с фильтром':>12} {'разница':>12}")
    for label, key, fmt in rows:
        b, a = before[key], after[key]
        print(f"{label:24} {fmt.format(b):>12} {fmt.format(a):>12} "
              f"{fmt.format(a - b) if key != 'final' else f'{a - b:+.2f}':>12}")

    print("\n⚠️  Это пересчёт уже случившегося, а не предсказание: комиссия взята "
          f"{FEE_PCT}%, проскальзывание не моделируется.")


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
    if args and args[0] == "replay":
        run_replay(args[1] if len(args) > 1 else "equity.csv")
        raise SystemExit(0)
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
