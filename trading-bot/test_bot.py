"""Тесты бота. Запуск: python -m unittest test_bot -v  (из папки trading-bot)

Сеть не используется: биржа подменяется фейками/моками.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import types
import unittest
from pathlib import Path
from unittest import mock

import journal
from config import Config
from dca import (Action, DcaEngine, DcaParams, simulate_dca)
from regime import Regime, detect_regime
from strategy import Indicators, Signal, decide, rsi, sma

DIR = Path(__file__).parent
ARTIFACTS = ["trades.csv", "equity.csv", "withdraw_state.json", "adaptive_state.json",
             "status.json", "state.json"]


def cleanup() -> None:
    for name in ARTIFACTS:
        (DIR / name).unlink(missing_ok=True)
    for p in DIR.glob("dca_state_*.json"):
        p.unlink(missing_ok=True)
    for p in DIR.glob("status_*.json"):
        p.unlink(missing_ok=True)
    for p in DIR.glob("*.bak"):
        p.unlink(missing_ok=True)


# Полный набор полей Config с дефолтами, чтобы строить конфиг без окружения.
def make_cfg(**over) -> Config:
    base = dict(
        api_key="", api_secret="", dry_run=True, testnet=True, strategy="dca",
        symbols=["BTCUSDT"], interval="15m", trade_quote_amount=250.0,
        stop_loss_pct=2.0, take_profit_pct=4.0, fast_ma=9, slow_ma=21, rsi_period=14,
        rsi_overbought=70.0, rsi_oversold=30.0, dca_base_order=30.0, dca_safety_order=30.0,
        dca_max_safety_orders=5, dca_price_deviation_pct=2.5, dca_safety_step_scale=1.0,
        dca_safety_volume_scale=1.0, dca_take_profit_pct=3.0, fee_pct=0.1,
        withdraw_enabled=False, withdraw_profit_pct=10.0, withdraw_min_amount=15.0,
        withdraw_asset="USDT", withdraw_network="TRX", withdraw_address="",
        dashboard_port=8000, adaptive_enabled=False, adaptive_optimize=True,
        regime_interval="1h", regime_lookback=500, reoptimize_every=50,
        trend_tp_multiplier=1.5, regime_slope_pct=0.6, regime_high_vol_pct=2.5,
        poll_interval_seconds=60,
    )
    base.update(over)
    return Config(**base)


class FakeExchange:
    """Дак-тайп биржи без сети для DCA-трейдера."""
    testnet = True

    def __init__(self, price=100.0, closes=None, dry_run=True, free=1e9):
        self._price = price
        self._closes = closes or [100.0] * 600
        self.dry_run = dry_run
        self._free = free
        self.sold = []
        self.bought = []

    def set_price(self, p): self._price = p
    def get_price(self, s): return self._price
    def get_closes(self, s, interval, limit): return self._closes
    def market_buy_quote(self, s, q):
        self.bought.append((s, q)); return {"qty": q / self._price, "cummulativeQuoteQty": q}
    def market_sell_qty(self, s, qty): self.sold.append((s, qty)); return {"qty": qty}
    def round_qty(self, s, q): return q
    def min_notional(self, s): return 0.0
    def quote_asset(self, s): return "USDT"
    def get_free_balance(self, asset): return self._free
    def withdraw(self, a, n, addr, amt): return {"id": "x"}


# ─────────────────────────── strategy ───────────────────────────
class TestStrategy(unittest.TestCase):
    def test_sma(self):
        self.assertEqual(sma([1, 2, 3, 4], 2), 3.5)

    def test_sma_insufficient(self):
        with self.assertRaises(ValueError):
            sma([1], 5)

    def test_rsi_all_gains_is_100(self):
        self.assertEqual(rsi([float(i) for i in range(20)], 14), 100.0)

    def test_rsi_range(self):
        import math
        vals = [100 + 5 * math.sin(i / 2) for i in range(60)]
        r = rsi(vals, 14)
        self.assertTrue(0 <= r <= 100)

    def test_decide_signals(self):
        up = Indicators(101, 100, 99, 100, 55, 101)
        self.assertEqual(decide(up, 70, 30), Signal.BUY)
        ob = Indicators(101, 100, 99, 100, 75, 101)
        self.assertEqual(decide(ob, 70, 30), Signal.HOLD)  # перекупленность
        dn = Indicators(99, 100, 101, 100, 45, 99)
        self.assertEqual(decide(dn, 70, 30), Signal.SELL)


# ─────────────────────────── DCA engine ───────────────────────────
class TestDcaEngine(unittest.TestCase):
    def params(self, **o):
        d = dict(base_order=30, safety_order=30, max_safety_orders=3,
                 price_deviation_pct=2.0, safety_step_scale=1.0,
                 safety_volume_scale=1.0, take_profit_pct=3.0)
        d.update(o)
        return DcaParams(**d)

    def test_base_then_safety_then_tp(self):
        e = DcaEngine(self.params())
        # базовый
        o = e.decide(100); self.assertEqual(o.action, Action.BUY)
        e.apply_buy(100, 30, 0.3)
        self.assertAlmostEqual(e.state.avg_entry, 100)
        self.assertAlmostEqual(e.state.next_safety_price, 98)
        # просадка -> safety
        self.assertIsNone(e.decide(99))         # ещё не достигла порога
        o = e.decide(98); self.assertEqual(o.action, Action.BUY)
        e.apply_buy(98, 30, 30 / 98)
        self.assertLess(e.state.avg_entry, 100)  # средняя снизилась
        # рост -> тейк-профит
        tp_price = e.state.avg_entry * 1.03
        self.assertEqual(e.decide(tp_price + 0.01).action, Action.SELL_ALL)

    def test_max_safety_limit(self):
        e = DcaEngine(self.params(max_safety_orders=1))
        e.apply_buy(100, 30, 0.3)
        e.apply_buy(98, 30, 30 / 98)  # safety #1
        self.assertEqual(e.state.safety_filled, 1)
        # дальнейшее падение не даёт новых докупок
        self.assertIsNone(e.decide(90))

    def test_volume_scale(self):
        # Конвенция DCA: 1-я докупка — базовый размер, множитель к последующим.
        e = DcaEngine(self.params(safety_volume_scale=2.0))
        e.apply_buy(100, 30, 0.3)
        o1 = e.decide(98)
        self.assertAlmostEqual(o1.quote, 30.0)   # 1-я safety = базовый размер
        e.apply_buy(98, 30, 30 / 98)             # заполнили safety #1
        o2 = e.decide(95)                         # ниже следующего порога
        self.assertAlmostEqual(o2.quote, 60.0)   # 2-я safety вдвое больше

    def test_simulate_metrics(self):
        closes = [100, 98, 95, 97, 99, 103, 104]
        m = simulate_dca(closes, self.params(), start_cash=200, fee_pct=0.1)
        self.assertIn("final", m)
        self.assertGreaterEqual(m["cycles"], 1)
        self.assertGreaterEqual(m["max_drawdown_pct"], 0)

    def test_simulate_empty(self):
        m = simulate_dca([], self.params(), 100)
        self.assertEqual(m["final"], 100)


# ─────────────────────────── regime ───────────────────────────
class TestRegime(unittest.TestCase):
    def test_up(self):
        self.assertEqual(detect_regime([100 * 1.005 ** i for i in range(120)]).regime,
                         Regime.TREND_UP)

    def test_down(self):
        self.assertEqual(detect_regime([100 * 0.995 ** i for i in range(120)]).regime,
                         Regime.TREND_DOWN)

    def test_range(self):
        import math
        self.assertEqual(detect_regime([100 + 2 * math.sin(i / 4) for i in range(120)]).regime,
                         Regime.RANGE)

    def test_insufficient_data(self):
        self.assertEqual(detect_regime([100, 101, 102]).regime, Regime.RANGE)


# ─────────────────────────── optimizer ───────────────────────────
class TestOptimizer(unittest.TestCase):
    def test_returns_valid_params(self):
        from optimizer import optimize
        import math
        closes = [100 + 8 * math.sin(i / 5) for i in range(400)]
        base = DcaParams(30, 30, 5, 2.5, 1.0, 1.0, 3.0)
        best, metrics = optimize(closes, base, start_cash=180)
        self.assertIsInstance(best, DcaParams)
        self.assertIn("pnl_pct", metrics)

    def test_flat_returns_base(self):
        from optimizer import optimize
        base = DcaParams(30, 30, 5, 2.5, 1.0, 1.0, 3.0)
        best, _ = optimize([100.0] * 300, base, start_cash=180)
        self.assertEqual(best.take_profit_pct, base.take_profit_pct)  # нет циклов -> база


# ─────────────────────────── config ───────────────────────────
class TestConfig(unittest.TestCase):
    def test_valid_passes(self):
        make_cfg().validate()  # не должно бросать

    def test_multi_symbol_budget_overflow(self):
        with self.assertRaises(ValueError):
            make_cfg(symbols=["BTCUSDT", "ETHUSDT"]).validate()  # 180*2 > 250

    def test_withdraw_without_address(self):
        with self.assertRaises(ValueError):
            make_cfg(withdraw_enabled=True, withdraw_address="").validate()

    def test_fast_ge_slow(self):
        with self.assertRaises(ValueError):
            make_cfg(fast_ma=21, slow_ma=9).validate()

    def test_reoptimize_nonpositive(self):
        with self.assertRaises(ValueError):
            make_cfg(reoptimize_every=0).validate()

    def test_symbol_property(self):
        self.assertEqual(make_cfg(symbols=["ETHUSDT", "BTCUSDT"]).symbol, "ETHUSDT")

    def test_symbols_parsing_and_dedup(self):
        env = {"SYMBOLS": "btcusdt, ethusdt ,BTCUSDT", "TRADE_QUOTE_AMOUNT": "1000",
               "STRATEGY": "dca", "DRY_RUN": "true", "TESTNET": "true",
               "WITHDRAW_ENABLED": "false", "ADAPTIVE_ENABLED": "false"}
        with mock.patch.dict(os.environ, env, clear=False):
            cfg = Config.load()
        self.assertEqual(cfg.symbols, ["BTCUSDT", "ETHUSDT"])

    def test_max_dca_budget(self):
        self.assertAlmostEqual(make_cfg().max_dca_budget(), 180.0)  # 30 + 5*30


# ─────────────────────────── journal ───────────────────────────
class TestJournal(unittest.TestCase):
    def setUp(self): cleanup()
    def tearDown(self): cleanup()

    def test_roundtrip(self):
        journal.record_trade("BTCUSDT", "BUY", "база", 100, 0.3, 30, 100)
        rows = journal.read_csv(journal.TRADES_CSV)
        self.assertEqual(rows[0]["symbol"], "BTCUSDT")
        self.assertEqual(rows[0]["side"], "BUY")

    def test_header_rotation(self):
        # старый формат без колонки symbol
        journal.TRADES_CSV.write_text("time,side,reason\n2020,BUY,x\n")
        journal.record_trade("ETHUSDT", "SELL", "tp", 100, 0.3, 30, 100, 1.0)
        self.assertTrue((DIR / "trades.csv.bak").exists())  # старый отложен
        rows = journal.read_csv(journal.TRADES_CSV)
        self.assertEqual(rows[-1]["symbol"], "ETHUSDT")


# ─────────────────────────── withdrawal ───────────────────────────
class TestWithdrawal(unittest.TestCase):
    def setUp(self): cleanup()
    def tearDown(self): cleanup()

    def test_disabled_no_withdraw(self):
        from withdrawal import ProfitWithdrawer
        ex = FakeExchange()
        w = ProfitWithdrawer(make_cfg(withdraw_enabled=False), ex)
        w.on_realized_profit(100)
        self.assertAlmostEqual(w.state.reserve, 10.0)  # 10% отложено
        self.assertEqual(w.state.withdrawn_total, 0.0)  # но не выведено

    def test_negative_profit_no_reserve(self):
        from withdrawal import ProfitWithdrawer
        w = ProfitWithdrawer(make_cfg(), FakeExchange())
        w.on_realized_profit(-5)
        self.assertEqual(w.state.reserve, 0.0)
        self.assertAlmostEqual(w.state.realized_pnl_total, -5)

    def test_threshold_and_floor(self):
        from withdrawal import ProfitWithdrawer
        calls = []
        ex = FakeExchange()
        ex.withdraw = lambda a, n, addr, amt: calls.append(amt) or {"id": 1}
        cfg = make_cfg(withdraw_enabled=True, withdraw_address="TX", withdraw_min_amount=5)
        w = ProfitWithdrawer(cfg, ex)
        w.on_realized_profit(100)  # резерв 10 -> >5 -> вывод
        self.assertEqual(len(calls), 1)
        self.assertLessEqual(calls[0], 10.0)        # не больше резерва
        self.assertGreaterEqual(w.state.reserve, 0) # резерв не ушёл в минус


# ─────────────────────────── adaptive ───────────────────────────
class TestAdaptive(unittest.TestCase):
    def setUp(self): cleanup()
    def tearDown(self): cleanup()

    def closes(self, kind):
        import math
        if kind == "down": return [100 * 0.995 ** i for i in range(300)]
        if kind == "up": return [100 * 1.005 ** i for i in range(300)]
        return [100 + 2 * math.sin(i / 4) for i in range(300)]

    def test_downtrend_pauses_entry(self):
        from adaptive import AdaptiveController
        c = AdaptiveController(make_cfg(adaptive_optimize=False), FakeExchange())
        d = c.update("BTCUSDT", self.closes("down"))
        self.assertEqual(d.info.regime, Regime.TREND_DOWN)
        self.assertFalse(d.allow_new_entry)

    def test_uptrend_boosts_tp(self):
        from adaptive import AdaptiveController
        cfg = make_cfg(adaptive_optimize=False, dca_take_profit_pct=3.0, trend_tp_multiplier=2.0)
        c = AdaptiveController(cfg, FakeExchange())
        d = c.update("BTCUSDT", self.closes("up"))
        self.assertEqual(d.info.regime, Regime.TREND_UP)
        self.assertAlmostEqual(d.params.take_profit_pct, 6.0)

    def test_state_persisted(self):
        from adaptive import AdaptiveController
        c = AdaptiveController(make_cfg(), FakeExchange())
        c.update("BTCUSDT", self.closes("range"))
        self.assertTrue((DIR / "adaptive_state.json").exists())


# ─────────────────────────── exchange (моки) ───────────────────────────
class DummyClient:
    def __init__(self, *a, perms=None, free="0.5", **k):
        self._perms = perms or {"enableWithdrawals": False,
                                "enableSpotAndMarginTrading": True, "ipRestrict": True}
        self._free = free
        self.sell_qty = None

    def ping(self): return {}
    def get_account(self):
        return {"canTrade": True, "balances": [
            {"asset": "USDT", "free": "100", "locked": "0"},
            {"asset": "BTC", "free": self._free, "locked": "0"}]}
    def get_account_api_permissions(self): return self._perms
    def get_symbol_ticker(self, symbol): return {"price": "100"}
    def get_symbol_info(self, symbol):
        return {"baseAsset": "BTC", "filters": [
            {"filterType": "LOT_SIZE", "stepSize": "0.00001000"},
            {"filterType": "NOTIONAL", "minNotional": "10"}]}
    def get_asset_balance(self, asset): return {"free": self._free}
    def order_market_buy(self, **k): return {"orderId": 1, **k}
    def order_market_sell(self, **k): self.sell_qty = k.get("quantity"); return {"orderId": 2, **k}
    def get_open_orders(self, symbol=None):
        return [{"symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT",
                 "price": "60000", "origQty": "0.001"}]
    def get_deposit_address(self, coin, network=None):
        return {"address": "TDepositAddr123", "tag": "", "coin": coin}


class TestExchange(unittest.TestCase):
    def _mk(self, dry_run=False, testnet=False, **client_kw):
        with mock.patch("exchange.Client", lambda *a, **k: DummyClient(**client_kw)):
            from exchange import Exchange
            return Exchange("k", "s", testnet=testnet, dry_run=dry_run)

    def test_round_qty(self):
        ex = self._mk()
        self.assertEqual(ex.round_qty("BTCUSDT", 0.123456789), 0.12345)

    def test_min_notional(self):
        self.assertEqual(self._mk().min_notional("BTCUSDT"), 10.0)

    def test_verify_ok_mainnet(self):
        info = self._mk().verify_credentials(expect_withdraw=False)
        self.assertTrue(info["can_trade"])

    def test_verify_rejects_unexpected_withdraw(self):
        ex = self._mk(perms={"enableWithdrawals": True, "enableSpotAndMarginTrading": True})
        with self.assertRaises(PermissionError):
            ex.verify_credentials(expect_withdraw=False)

    def test_verify_requires_withdraw_when_expected(self):
        ex = self._mk(perms={"enableWithdrawals": False, "enableSpotAndMarginTrading": True})
        with self.assertRaises(PermissionError):
            ex.verify_credentials(expect_withdraw=True)

    def test_verify_requires_spot(self):
        ex = self._mk(perms={"enableWithdrawals": False, "enableSpotAndMarginTrading": False})
        with self.assertRaises(PermissionError):
            ex.verify_credentials(expect_withdraw=False)

    def test_sell_clamped_to_balance(self):
        # учли 1.0 BTC, а на балансе только 0.4 — продать должны 0.4
        ex = self._mk(free="0.4")
        ex.market_sell_qty("BTCUSDT", 1.0)
        self.assertAlmostEqual(float(ex.client.sell_qty), 0.4, places=5)

    def test_dry_run_orders(self):
        ex = self._mk(dry_run=True, testnet=True)
        self.assertTrue(ex.market_buy_quote("BTCUSDT", 30)["dry_run"])
        self.assertTrue(ex.withdraw("USDT", "TRX", "addr", 5)["dry_run"])

    def test_balances_and_orders(self):
        ex = self._mk()
        self.assertIn("USDT", ex.balances())
        self.assertEqual(ex.open_orders()[0]["symbol"], "BTCUSDT")

    def test_deposit_address_live_vs_dry(self):
        self.assertEqual(self._mk().deposit_address("USDT", "TRX")["address"], "TDepositAddr123")
        self.assertEqual(self._mk(dry_run=True, testnet=True).deposit_address("USDT")["address"], "")


# ─────────────────────────── DcaTrader интеграция ───────────────────────────
class TestDcaTrader(unittest.TestCase):
    def setUp(self): cleanup()
    def tearDown(self): cleanup()

    def test_multi_symbol_cycle(self):
        from dca_trader import DcaTrader
        cfg = make_cfg(symbols=["BTCUSDT", "ETHUSDT"], dca_max_safety_orders=2,
                       trade_quote_amount=250)  # 90*2=180 <=250
        ex = FakeExchange()
        t = DcaTrader(cfg, ex)
        ex.set_price(100); t.step()             # базовые покупки
        ex.set_price(104); t.step()             # тейк-профит (>+3%)
        syms = {r["symbol"] for r in journal.read_csv(journal.TRADES_CSV)}
        self.assertEqual(syms, {"BTCUSDT", "ETHUSDT"})
        eq = journal.read_csv(journal.EQUITY_CSV)
        self.assertTrue(len(eq) >= 2)

    def test_adaptive_pause_blocks_buy(self):
        from dca_trader import DcaTrader
        cfg = make_cfg(adaptive_enabled=True, adaptive_optimize=False)
        ex = FakeExchange(closes=[100 * 0.995 ** i for i in range(300)])
        ex.set_price(60.0)
        t = DcaTrader(cfg, ex)
        t.step()
        # в нисходящем тренде базовый ордер НЕ должен открыться
        self.assertEqual(journal.read_csv(journal.TRADES_CSV), [])
        status = json.loads((DIR / "status.json").read_text())
        self.assertEqual(status["symbols"]["BTCUSDT"]["regime"], "тренд вниз")

    def test_insufficient_balance_skips_buy(self):
        from dca_trader import DcaTrader
        cfg = make_cfg(symbols=["BTCUSDT"])
        # боевой режим, но свободно всего 5 USDT < базового ордера 30
        ex = FakeExchange(dry_run=False, free=5.0)
        ex.set_price(100)
        DcaTrader(cfg, ex).step()
        self.assertEqual(ex.bought, [])                       # покупки не было
        self.assertEqual(journal.read_csv(journal.TRADES_CSV), [])

    def test_equity_aggregation(self):
        from dca_trader import DcaTrader
        cfg = make_cfg(symbols=["BTCUSDT"])
        ex = FakeExchange()
        t = DcaTrader(cfg, ex)
        ex.set_price(100); t.step()
        last = journal.read_csv(journal.EQUITY_CSV)[-1]
        # equity = бюджет + realized + unrealized; сразу после покупки ~ бюджет
        self.assertAlmostEqual(float(last["equity"]), 250.0, delta=1.0)


# ─────────────────────────── ключи под режим ───────────────────────────
class TestConfigKeys(unittest.TestCase):
    def test_testnet_uses_testnet_keys(self):
        env = {"TESTNET": "true", "DRY_RUN": "false", "STRATEGY": "dca",
               "SYMBOL": "BTCUSDT", "TRADE_QUOTE_AMOUNT": "1000",
               "BINANCE_TESTNET_API_KEY": "tk", "BINANCE_TESTNET_API_SECRET": "ts",
               "BINANCE_API_KEY": "lk", "BINANCE_API_SECRET": "ls",
               "WITHDRAW_ENABLED": "false"}
        with mock.patch.dict(os.environ, env, clear=False):
            cfg = Config.load()
        self.assertEqual((cfg.api_key, cfg.api_secret), ("tk", "ts"))

    def test_live_uses_main_keys(self):
        env = {"TESTNET": "false", "DRY_RUN": "false", "STRATEGY": "dca",
               "SYMBOL": "BTCUSDT", "TRADE_QUOTE_AMOUNT": "1000",
               "BINANCE_TESTNET_API_KEY": "tk", "BINANCE_TESTNET_API_SECRET": "ts",
               "BINANCE_API_KEY": "lk", "BINANCE_API_SECRET": "ls",
               "WITHDRAW_ENABLED": "false"}
        with mock.patch.dict(os.environ, env, clear=False):
            cfg = Config.load()
        self.assertEqual((cfg.api_key, cfg.api_secret), ("lk", "ls"))

    def test_testnet_fallback_to_main(self):
        env = {"TESTNET": "true", "DRY_RUN": "false", "STRATEGY": "dca",
               "SYMBOL": "BTCUSDT", "TRADE_QUOTE_AMOUNT": "1000",
               "BINANCE_TESTNET_API_KEY": "", "BINANCE_TESTNET_API_SECRET": "",
               "BINANCE_API_KEY": "lk", "BINANCE_API_SECRET": "ls",
               "WITHDRAW_ENABLED": "false"}
        with mock.patch.dict(os.environ, env, clear=False):
            cfg = Config.load()
        self.assertEqual(cfg.api_key, "lk")


# ─────────────────────────── settings_store ───────────────────────────
class TestSettingsStore(unittest.TestCase):
    def setUp(self):
        import settings_store
        import tempfile
        self.ss = settings_store
        self.tmp = Path(tempfile.mkdtemp()) / ".env"
        self.tmp.write_text("BINANCE_API_SECRET=supersecretvalue\nSTRATEGY=dca\n")
        self._orig = settings_store.ENV_PATH
        settings_store.ENV_PATH = self.tmp

    def tearDown(self):
        self.ss.ENV_PATH = self._orig

    def test_secret_masked_on_read(self):
        s = self.ss.read_settings()
        self.assertTrue(s["BINANCE_API_SECRET"].startswith(self.ss.MASK))
        self.assertTrue(s["BINANCE_API_SECRET"].endswith("alue"))
        self.assertEqual(s["STRATEGY"], "dca")

    def test_save_skips_masked_secret(self):
        # передаём замаскированное значение — секрет не должен перезаписаться
        self.ss.save_settings({"BINANCE_API_SECRET": self.ss.MASK + "alue", "STRATEGY": "swing"})
        from dotenv import dotenv_values
        v = dotenv_values(self.tmp)
        self.assertEqual(v["BINANCE_API_SECRET"], "supersecretvalue")  # не тронут
        self.assertEqual(v["STRATEGY"], "swing")                       # изменён

    def test_save_real_secret(self):
        self.ss.save_settings({"BINANCE_API_SECRET": "newrealsecret"})
        from dotenv import dotenv_values
        self.assertEqual(dotenv_values(self.tmp)["BINANCE_API_SECRET"], "newrealsecret")


# ─────────────────────────── DCA: управление позициями ───────────────────────────
class TestDcaControl(unittest.TestCase):
    def setUp(self): cleanup()
    def tearDown(self): cleanup()

    def test_snapshot_and_close(self):
        from dca_trader import DcaTrader
        cfg = make_cfg(symbols=["BTCUSDT"])
        ex = FakeExchange()
        t = DcaTrader(cfg, ex)
        ex.set_price(100); t.step()                    # открыли позицию
        snap = t.snapshot()
        self.assertTrue(snap[0]["in_position"])
        self.assertAlmostEqual(snap[0]["avg_entry"], 100, delta=0.1)
        closed = t.close_all_positions()
        self.assertEqual(closed, 1)
        self.assertFalse(t.snapshot()[0]["in_position"])
        sells = [r for r in journal.read_csv(journal.TRADES_CSV)
                 if r["side"] == "SELL" and r["reason"] == "ручное закрытие"]
        self.assertEqual(len(sells), 1)


class TestSourceTagging(unittest.TestCase):
    def setUp(self): cleanup()
    def tearDown(self): cleanup()

    def test_trades_and_equity_tagged(self):
        from dca_trader import DcaTrader
        ex = FakeExchange()
        ex.set_price(100)
        DcaTrader(make_cfg(symbols=["BTCUSDT"]), ex, source="alpaca").step()
        trades = journal.read_csv(journal.TRADES_CSV)
        equity = journal.read_csv(journal.EQUITY_CSV)
        self.assertTrue(trades and all(r["source"] == "alpaca" for r in trades))
        self.assertTrue(equity and all(r["source"] == "alpaca" for r in equity))


# ─────────────────────────── manager (без сети) ───────────────────────────
class TestManager(unittest.TestCase):
    def test_fresh_info(self):
        from manager import BotManager
        info = BotManager().info()
        self.assertFalse(info["running"])
        self.assertEqual(info["units"], [])

    def test_switch_mode_invalid(self):
        from manager import BotManager
        r = BotManager().switch_mode("nonsense", "live")
        self.assertFalse(r["ok"])

    def test_switch_mode_bad_target(self):
        from manager import BotManager
        self.assertFalse(BotManager().switch_mode("binance", "paper")["ok"])
        self.assertFalse(BotManager().switch_mode("alpaca", "test")["ok"])


# ─────────────────────────── Alpaca broker (фейк-клиенты) ───────────────────────────
class _NS(types.SimpleNamespace):
    pass


class FakeAlpacaTrading:
    def __init__(self):
        self.submitted = []
        self.cash = 100000.0
    def get_account(self): return _NS(cash=str(self.cash), trading_blocked=False)
    def get_clock(self): return _NS(is_open=True)
    def get_open_position(self, asset):
        if asset == "AAPL":
            return _NS(qty="5", qty_available="5")
        raise RuntimeError("no position")
    def get_all_positions(self): return [_NS(symbol="AAPL", qty="5")]
    def get_orders(self, req):
        return [_NS(symbol="AAPL", side=_NS(value="buy"), order_type=_NS(value="market"),
                    limit_price=None, filled_avg_price="150", qty="1", notional=None)]
    def submit_order(self, req):
        self.submitted.append(req)
        return _NS(id="ord-1")
    def get_order_by_id(self, oid):
        return _NS(id=oid, filled_qty="2", filled_avg_price="150", status="filled")


class FakeAlpacaData:
    def get_stock_latest_trade(self, req):
        sym = req.symbol_or_symbols
        return {sym: _NS(price=150.0)}
    def get_stock_bars(self, req):
        sym = req.symbol_or_symbols
        return _NS(data={sym: [_NS(close=100.0), _NS(close=101.0), _NS(close=102.0)]})


class TestAlpacaBroker(unittest.TestCase):
    def _mk(self):
        from alpaca_broker import AlpacaBroker
        return AlpacaBroker("k", "s", paper=True,
                            trading_client=FakeAlpacaTrading(), data_client=FakeAlpacaData())

    def test_price_and_closes(self):
        b = self._mk()
        self.assertEqual(b.get_price("AAPL"), 150.0)
        self.assertEqual(b.get_closes("AAPL", "1h", 3), [100.0, 101.0, 102.0])

    def test_market_open_and_quote_asset(self):
        b = self._mk()
        self.assertTrue(b.market_open())
        self.assertEqual(b.quote_asset("AAPL"), "USD")
        self.assertEqual(b.base_asset("AAPL"), "AAPL")

    def test_balances_and_free(self):
        b = self._mk()
        self.assertEqual(b.balances()["USD"], 100000.0)
        self.assertEqual(b.get_free_balance("USD"), 100000.0)
        self.assertEqual(b.get_free_balance("AAPL"), 5.0)
        self.assertEqual(b.get_free_balance("TSLA"), 0.0)

    def test_open_orders_normalized(self):
        o = self._mk().open_orders()[0]
        self.assertEqual(o["symbol"], "AAPL")
        self.assertEqual(o["side"], "BUY")
        self.assertEqual(o["type"], "market")

    def test_buy_and_sell(self):
        b = self._mk()
        r = b.market_buy_quote("AAPL", 300)
        self.assertEqual(r["qty"], 2.0)
        self.assertAlmostEqual(r["cummulativeQuoteQty"], 300.0)
        self.assertEqual(b.market_sell_qty("AAPL", 2)["qty"], 2.0)

    def test_deposit_and_verify(self):
        b = self._mk()
        self.assertEqual(b.deposit_address("USD")["address"], "")
        self.assertTrue(b.verify_credentials()["can_trade"])


class TestBrokerWiring(unittest.TestCase):
    def test_for_alpaca_derives(self):
        cfg = make_cfg(symbols=["BTCUSDT"])
        cfg = dataclasses.replace(cfg, alpaca_symbols=["AAPL", "MSFT"],
                                  alpaca_paper=True, alpaca_trade_quote_amount=5000.0,
                                  alpaca_api_key="ak", alpaca_api_secret="as_")
        a = cfg.for_alpaca()
        self.assertEqual(a.symbols, ["AAPL", "MSFT"])
        self.assertEqual(a.fee_pct, 0.0)
        self.assertFalse(a.withdraw_enabled)
        self.assertEqual(a.api_key, "ak")
        self.assertTrue(a.testnet)  # paper → testnet-семантика

    def test_for_alpaca_dca_override_and_defaults(self):
        from config import STOCK_DCA_DEFAULTS
        cfg = dataclasses.replace(
            make_cfg(symbols=["BTCUSDT"]), alpaca_symbols=["AAPL"],
            alpaca_api_key="k", alpaca_api_secret="s", alpaca_trade_quote_amount=5000.0,
            alpaca_dca_take_profit_pct=8.0)  # TP переопределён, остальное — дефолты акций
        a = cfg.for_alpaca()
        self.assertEqual(a.dca_take_profit_pct, 8.0)
        self.assertEqual(a.dca_base_order, STOCK_DCA_DEFAULTS["base_order"])
        self.assertEqual(a.dca_take_profit_pct != cfg.dca_take_profit_pct, True)

    def test_for_alpaca_budget_validation(self):
        cfg = dataclasses.replace(
            make_cfg(symbols=["BTCUSDT"]), alpaca_symbols=["AAPL"],
            alpaca_api_key="k", alpaca_api_secret="s", alpaca_trade_quote_amount=50.0,
            alpaca_dca_base_order=100.0, alpaca_dca_safety_order=100.0,
            alpaca_dca_max_safety_orders=5)  # 100+100*5=600 > бюджет 50
        with self.assertRaises(ValueError):
            cfg.for_alpaca()

    def test_create_traders_attempts_binance_only(self):
        from main import create_traders
        cfg = make_cfg(symbols=["BTCUSDT"])  # binance on, alpaca off
        units, errors = create_traders(cfg, logging.getLogger("t"))
        names = [n for n, _ in units] + list(errors)  # успех ИЛИ ошибка — но попытка была
        self.assertIn("binance", names)
        self.assertNotIn("alpaca", names)

    def test_create_traders_alpaca_missing_keys(self):
        from main import create_traders
        cfg = dataclasses.replace(make_cfg(symbols=["BTCUSDT"]),
                                  binance_enabled=False, alpaca_enabled=True,
                                  alpaca_api_key="", alpaca_api_secret="")
        units, errors = create_traders(cfg, logging.getLogger("t"))
        self.assertEqual(units, [])
        self.assertIn("alpaca", errors)


# ─────────────────────────── swing (смоук) ───────────────────────────
class TestSwingTrader(unittest.TestCase):
    def setUp(self): cleanup()
    def tearDown(self): cleanup()

    def test_step_runs_without_error(self):
        from trader import Trader
        import math
        # достаточно свечей для самых длинных индикаторов
        closes = [100 + 5 * math.sin(i / 6) for i in range(120)]
        cfg = make_cfg(strategy="swing")
        ex = FakeExchange(closes=closes)
        Trader(cfg, ex).step()  # не должно бросать


if __name__ == "__main__":
    unittest.main(verbosity=2)
