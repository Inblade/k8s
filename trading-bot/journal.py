"""Журнал сделок и снимков капитала в CSV — источник данных для дашборда."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

DIR = Path(__file__).parent
TRADES_CSV = DIR / "trades.csv"
EQUITY_CSV = DIR / "equity.csv"

TRADE_FIELDS = ["time", "source", "symbol", "side", "reason", "price", "qty", "quote",
                "avg_entry", "realized_pnl"]
EQUITY_FIELDS = ["time", "source", "price", "position_qty", "position_value",
                 "unrealized_pnl", "realized_pnl", "equity", "withdrawn", "reserve"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append(path: Path, fields: list[str], row: dict) -> None:
    # Если файл существует со старым набором колонок — отложим его в .bak,
    # чтобы не смешать форматы (например, после добавления колонки symbol).
    if path.exists():
        with path.open(newline="") as f:
            header = f.readline().strip().split(",")
        if header != fields:
            path.rename(path.with_suffix(path.suffix + ".bak"))
    new_file = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new_file:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in fields})


def record_trade(symbol: str, side: str, reason: str, price: float, qty: float,
                 quote: float, avg_entry: float, realized_pnl: float = 0.0,
                 source: str = "binance") -> None:
    _append(TRADES_CSV, TRADE_FIELDS, {
        "time": _now(), "source": source, "symbol": symbol, "side": side, "reason": reason,
        "price": round(price, 2), "qty": round(qty, 8), "quote": round(quote, 2),
        "avg_entry": round(avg_entry, 2), "realized_pnl": round(realized_pnl, 4),
    })


def record_equity(price: float, position_qty: float, position_value: float,
                  unrealized_pnl: float, realized_pnl: float,
                  equity: float, withdrawn: float, reserve: float,
                  source: str = "binance") -> None:
    _append(EQUITY_CSV, EQUITY_FIELDS, {
        "time": _now(), "source": source, "price": round(price, 2),
        "position_qty": round(position_qty, 8), "position_value": round(position_value, 2),
        "unrealized_pnl": round(unrealized_pnl, 2), "realized_pnl": round(realized_pnl, 2),
        "equity": round(equity, 2), "withdrawn": round(withdrawn, 2),
        "reserve": round(reserve, 2),
    })


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))
