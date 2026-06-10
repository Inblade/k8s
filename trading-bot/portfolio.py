"""Распределение бюджета между брокерами по волатильности (risk-parity).

Главный вывод ресёрча: высоковолатильный актив (крипта) при равных деньгах даёт
почти весь риск портфеля. Поэтому веса ∝ 1/волатильность, и на крипту ставится
потолок (ядро = спокойные акции, спутник = небольшая крипта).
"""
from __future__ import annotations

# Типичная годовая волатильность класса актива, % (крипта ~3–4× акций).
ASSET_CLASS_VOL = {"binance": 60.0, "alpaca": 18.0}


def inverse_vol_weights(vols: dict[str, float], crypto_max: float = 0.15) -> dict[str, float]:
    """Веса ∝ 1/волатильность, нормированы к 1. На 'binance' (крипту) — потолок
    crypto_max, остаток распределяется остальным пропорционально."""
    names = [n for n, v in vols.items() if v and v > 0]
    if not names:
        return {}
    inv = {n: 1.0 / vols[n] for n in names}
    total = sum(inv.values())
    w = {n: inv[n] / total for n in names}
    if "binance" in w and len(names) > 1 and w["binance"] > crypto_max:
        excess = w["binance"] - crypto_max
        w["binance"] = crypto_max
        others = [n for n in names if n != "binance"]
        base = sum(w[n] for n in others)
        for n in others:
            w[n] += excess * (w[n] / base) if base > 0 else excess / len(others)
    return w


def split_budget(total: float, vols: dict[str, float],
                 crypto_max: float = 0.15) -> dict[str, float]:
    """Делит общий бюджет по обратной волатильности с потолком на крипту."""
    w = inverse_vol_weights(vols, crypto_max)
    return {n: round(total * wi, 2) for n, wi in w.items()}
