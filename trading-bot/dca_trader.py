"""Живой торговый цикл для DCA-стратегии. Поддерживает несколько монет сразу."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import replace
from pathlib import Path

import journal
from adaptive import AdaptiveController
from config import Config
from dca import Action, DcaEngine, DcaParams
from exchange import Exchange
from strategy import sma
from volatility import clamp, mean_abs_change_pct
from withdrawal import ProfitWithdrawer

log = logging.getLogger("bot.dca")

DIR = Path(__file__).parent
STATUS_FILE = DIR / "status.json"


def params_from_config(cfg: Config) -> DcaParams:
    return DcaParams(
        base_order=cfg.dca_base_order,
        safety_order=cfg.dca_safety_order,
        max_safety_orders=cfg.dca_max_safety_orders,
        price_deviation_pct=cfg.dca_price_deviation_pct,
        safety_step_scale=cfg.dca_safety_step_scale,
        safety_volume_scale=cfg.dca_safety_volume_scale,
        take_profit_pct=cfg.dca_take_profit_pct,
        stop_loss_pct=cfg.dca_stop_loss_pct,
    )


def is_network_error(exc: BaseException) -> bool:
    """Сбой связи (сон ноутбука, пропавший Wi-Fi, таймаут биржи), а не баг в коде.

    Ловим по имени класса, чтобы не тащить requests/urllib3 в импорты и не
    зависеть от того, во что именно python-binance завернул ошибку.
    """
    seen = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        name = type(cur).__name__
        if name in {"ConnectionError", "ConnectTimeout", "ReadTimeout", "Timeout",
                    "TimeoutError", "ConnectionResetError", "ConnectionAbortedError",
                    "ConnectionRefusedError", "NameResolutionError", "NewConnectionError",
                    "MaxRetryError", "ProtocolError", "SSLError", "SSLEOFError",
                    "ChunkedEncodingError", "RequestException", "gaierror", "OSError"}:
            return True
        # Биржа отдала HTML вместо JSON (заглушка Cloudflare/техработы).
        if name == "BinanceAPIException" and "Invalid JSON" in str(cur):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def _short_error(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    return text[:160] + "…" if len(text) > 160 else text


def _state_file(symbol: str) -> Path:
    return DIR / f"dca_state_{symbol}.json"


class DcaTrader:
    def __init__(self, cfg: Config, exchange: Exchange, source: str = "binance"):
        self.cfg = cfg
        self.ex = exchange
        self.source = source  # метка брокера для журнала/графиков
        params = params_from_config(cfg)
        if 0 < params.stop_loss_pct <= params.price_deviation_pct:
            log.warning("Стоп-лосс %.2f%% не шире шага докупки %.2f%% — сработает ДО "
                        "усреднения. Сделай стоп-лосс заметно шире покрытия докупок.",
                        params.stop_loss_pct, params.price_deviation_pct)
        # Отдельный движок и файл состояния на каждую монету.
        self.engines: dict[str, DcaEngine] = {}
        for sym in cfg.symbols:
            sf = _state_file(sym)
            if sf.exists():
                self.engines[sym] = DcaEngine.from_state_dict(params, json.loads(sf.read_text()))
            else:
                self.engines[sym] = DcaEngine(params)
        self.withdrawer = ProfitWithdrawer(cfg, exchange)
        self.controller = AdaptiveController(cfg, exchange) if cfg.adaptive_enabled else None

    def _save(self, symbol: str) -> None:
        _state_file(symbol).write_text(json.dumps(self.engines[symbol].state_dict()))

    # ── Обработка одной монеты ─────────────────────────────────────────
    def _process_symbol(self, symbol: str, price: float, allow_new_entry: bool = True) -> None:
        engine = self.engines[symbol]
        s = engine.state
        if not s.in_position and not allow_new_entry:
            log.info("[%s] Цена=%.2f вход на паузе (режим рынка не благоприятен)",
                     symbol, price)
            return
        if s.in_position:
            log.info("[%s] Цена=%.2f средняя=%.2f объём=%.8f safety=%d/%d след.докупка<=%.2f",
                     symbol, price, s.avg_entry, s.qty, s.safety_filled,
                     self.cfg.dca_max_safety_orders, s.next_safety_price)
        else:
            log.info("[%s] Цена=%.2f вне позиции (ждём базовый ордер)", symbol, price)

        order = engine.decide(price)
        if order is None:
            return

        if order.action == Action.BUY:
            if not self.ex.dry_run:
                # Биржа отклонит ордер меньше минимального (MIN_NOTIONAL).
                min_notional = self.ex.min_notional(symbol)
                if order.quote < min_notional:
                    log.warning("[%s] Ордер %.2f USDT меньше минимума %.2f — пропуск",
                                symbol, order.quote, min_notional)
                    return
                # Достаточно ли свободных средств (одна USDT-касса на все монеты).
                free = self.ex.get_free_balance(self.ex.quote_asset(symbol))
                if free < order.quote:
                    log.warning("[%s] Недостаточно средств: нужно %.2f, свободно %.2f — пропуск",
                                symbol, order.quote, free)
                    return
            result = self.ex.market_buy_quote(symbol, order.quote)
            qty = float(result.get("qty") or result.get("executedQty", 0.0))
            spent = float(result.get("cummulativeQuoteQty") or order.quote)
            engine.apply_buy(price, spent, qty)
            avg = engine.state.avg_entry
            log.info("[%s] >>> ПОКУПКА (%s): +%.8f за %.2f USDT | средняя=%.2f",
                     symbol, order.reason, qty, spent, avg)
            journal.record_trade(symbol, "BUY", order.reason, price, qty, spent, avg,
                                 source=self.source)
        elif order.action == Action.SELL_ALL:
            proceeds = s.qty * price * (1 - self.cfg.fee_pct / 100)
            realized = proceeds - s.spent
            pnl_pct = (price / s.avg_entry - 1) * 100 if s.avg_entry else 0
            self.ex.market_sell_qty(symbol, s.qty)
            log.info("[%s] <<< ПРОДАЖА (%s): %.8f по ~%.2f | P&L=%.2f%% (%.2f USDT)",
                     symbol, order.reason, s.qty, price, pnl_pct, realized)
            journal.record_trade(symbol, "SELL", order.reason, price, s.qty,
                                 proceeds, s.avg_entry, realized, source=self.source)
            engine.apply_sell_all()
            self.withdrawer.on_realized_profit(realized)
        self._save(symbol)

    # ── Снимок суммарного капитала по всем монетам ─────────────────────
    def _record_equity(self, prices: dict[str, float]) -> None:
        total_value = 0.0
        total_spent = 0.0
        for sym, engine in self.engines.items():
            st = engine.state
            if st.in_position:
                total_value += st.qty * prices[sym]
                total_spent += st.spent
        realized = self.withdrawer.state.realized_pnl_total
        unrealized = total_value - total_spent
        equity = self.cfg.trade_quote_amount + realized + unrealized
        # В колонки price и position_qty пишем данные первой (основной) монеты:
        # складывать qty разных монет бессмысленно, а ноль вместо количества
        # делал журнал недостоверным (позиция есть, а в CSV 0).
        main = self.engines[self.cfg.symbol].state
        journal.record_equity(
            price=prices[self.cfg.symbol], position_qty=main.qty, position_value=total_value,
            unrealized_pnl=unrealized, realized_pnl=realized, equity=equity,
            withdrawn=self.withdrawer.state.withdrawn_total,
            reserve=self.withdrawer.state.reserve, source=self.source,
        )

    def _status_file(self) -> Path:
        # Свой файл статуса на брокера, чтобы адаптивные режимы не перетирали друг друга.
        return DIR / (f"status_{self.source}.json" if self.source != "binance" else "status.json")

    def _write_status(self, statuses: dict) -> None:
        from datetime import datetime, timezone
        self._status_file().write_text(json.dumps({
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "adaptive": True,
            "symbols": statuses,
        }))

    def step(self) -> None:
        # Крипторынок работает 24/7 — расписания торгов проверять не нужно.
        # Цены берём один раз за шаг, чтобы не дёргать API повторно.
        prices = {sym: self.ex.get_price(sym) for sym in self.cfg.symbols}
        statuses: dict = {}
        for sym in self.cfg.symbols:
            allow = True
            if self.controller is not None:
                closes = self.ex.get_closes(sym, self.cfg.regime_interval,
                                            self.cfg.regime_lookback)
                decision = self.controller.update(sym, closes)
                self.engines[sym].p = decision.params  # применяем адаптацию
                allow = decision.allow_new_entry
                info = decision.info
                log.info("[%s] Режим: %s (наклон %.2f%%, волат. %.2f%%) | TP=%.1f%% | входы: %s",
                         sym, info.regime.value, info.slope_pct, info.volatility_pct,
                         decision.params.take_profit_pct, "да" if allow else "ПАУЗА")
                statuses[sym] = {
                    "regime": info.regime.value,
                    "slope_pct": round(info.slope_pct, 2),
                    "volatility_pct": round(info.volatility_pct, 2),
                    "take_profit_pct": round(decision.params.take_profit_pct, 2),
                    "deviation_pct": round(decision.params.price_deviation_pct, 2),
                    "max_safety": decision.params.max_safety_orders,
                    "allow_new_entry": allow,
                }
            elif self.cfg.dca_atr_enabled:
                self._apply_atr_spacing(sym)
            # Трендовый фильтр: не открываем новые циклы ниже длинной MA.
            if self.cfg.dca_trend_filter_enabled and not self._trend_ok(sym, prices[sym]):
                allow = False
            self._process_symbol(sym, prices[sym], allow)
        self._record_equity(prices)
        if self.controller is not None:
            self._write_status(statuses)

    def _trend_ok(self, sym: str, price: float) -> bool:
        """True, если цена выше длинной MA (восходящий тренд) или данных мало."""
        c = self.cfg
        closes = self.ex.get_closes(sym, c.dca_trend_interval, c.dca_trend_ma_period + 5)
        if len(closes) < c.dca_trend_ma_period:
            return True  # недостаточно истории — не блокируем
        ma = sma(closes, c.dca_trend_ma_period)
        ok = price > ma
        if not ok:
            log.info("[%s] Трендовый фильтр: цена %.2f < MA%d %.2f — новые входы на паузе",
                     sym, price, c.dca_trend_ma_period, ma)
        return ok

    def _apply_atr_spacing(self, sym: str) -> None:
        """Шаг просадки и тейк-профит = волатильность × множитель (с зажимом)."""
        c = self.cfg
        closes = self.ex.get_closes(sym, c.interval, c.dca_atr_period + 1)
        vol = mean_abs_change_pct(closes, c.dca_atr_period)
        if vol <= 0:
            return  # нет данных — оставляем текущие параметры
        dev = clamp(vol * c.dca_atr_step_mult, c.dca_atr_min_pct, c.dca_atr_max_pct)
        tp = clamp(vol * c.dca_atr_tp_mult, c.dca_atr_min_pct, c.dca_atr_max_pct)
        # Заменяем параметры НОВЫМ объектом (движки делят один DcaParams!).
        self.engines[sym].p = replace(self.engines[sym].p,
                                      price_deviation_pct=dev, take_profit_pct=tp)
        log.info("[%s] ATR-привязка: волат.=%.2f%% → шаг=%.2f%% TP=%.2f%%",
                 sym, vol, dev, tp)

    # ── Управление из панели ───────────────────────────────────────────
    def snapshot(self) -> list[dict]:
        """Текущие позиции по монетам — для боковой панели/окна сделки."""
        out = []
        for sym, e in self.engines.items():
            s = e.state
            price = self.ex.get_price(sym)
            out.append({
                "symbol": sym,
                "in_position": s.in_position,
                "qty": s.qty,
                "avg_entry": s.avg_entry,
                "spent": s.spent,
                "price": price,
                "unrealized": (s.qty * price - s.spent) if s.in_position else 0.0,
                "safety_filled": s.safety_filled,
                "take_profit_pct": e.p.take_profit_pct,
                "tp_price": s.avg_entry * (1 + e.p.take_profit_pct / 100) if s.in_position else 0.0,
            })
        return out

    def close_all_positions(self) -> int:
        """Закрывает все открытые позиции в рынок. Возвращает число закрытых."""
        closed = 0
        for sym, e in self.engines.items():
            s = e.state
            if not s.in_position:
                continue
            price = self.ex.get_price(sym)
            proceeds = s.qty * price * (1 - self.cfg.fee_pct / 100)
            realized = proceeds - s.spent
            self.ex.market_sell_qty(sym, s.qty)
            log.info("[%s] Закрытие позиции вручную: %.8f по ~%.2f | P&L=%.2f USDT",
                     sym, s.qty, price, realized)
            journal.record_trade(sym, "SELL", "ручное закрытие", price, s.qty,
                                 proceeds, s.avg_entry, realized, source=self.source)
            e.apply_sell_all()
            self._save(sym)
            self.withdrawer.on_realized_profit(realized)
            closed += 1
        return closed

    def run(self, stop_event=None) -> None:
        log.info(
            "Старт DCA | монеты: %s | DRY_RUN=%s TESTNET=%s | база=%.0f safety=%.0f x%d "
            "дев=%.1f%% TP=%.1f%% | стоп-лосс=%s | тренд-фильтр=%s "
            "| бюджет/монета=%.0f, всего=%.0f USDT",
            ", ".join(self.cfg.symbols), self.ex.dry_run, self.ex.testnet,
            self.cfg.dca_base_order, self.cfg.dca_safety_order,
            self.cfg.dca_max_safety_orders, self.cfg.dca_price_deviation_pct,
            self.cfg.dca_take_profit_pct,
            # Защиту видно в логе явно: молча выключенный стоп-лосс — худший из сюрпризов.
            f"{self.cfg.dca_stop_loss_pct:.0f}%" if self.cfg.dca_stop_loss_pct > 0 else "ВЫКЛ",
            f"MA{self.cfg.dca_trend_ma_period}/{self.cfg.dca_trend_interval}"
            if self.cfg.dca_trend_filter_enabled else "ВЫКЛ",
            self.cfg.max_dca_budget(),
            self.cfg.max_dca_budget() * len(self.cfg.symbols),
        )
        if self.controller is not None:
            log.info("Адаптивный режим ВКЛ: определение тренда/боковика на %s + "
                     "оптимизация параметров каждые %d шагов (optimize=%s)",
                     self.cfg.regime_interval, self.cfg.reoptimize_every,
                     self.cfg.adaptive_optimize)
        offline = 0  # сколько шагов подряд не смогли достучаться до биржи
        while stop_event is None or not stop_event.is_set():
            try:
                self.step()
                if offline:
                    log.info("Связь с биржей восстановлена (было %d неудачных шагов)", offline)
                    offline = 0
            except Exception as exc:  # noqa: BLE001 — бот не должен падать из-за разовой ошибки
                if is_network_error(exc):
                    # Ноутбук уснул / пропал Wi-Fi: это не баг, полный traceback каждую
                    # минуту раздувал лог до десятков МБ. Пишем кратко и с прореживанием.
                    offline += 1
                    if offline == 1 or offline % 30 == 0:
                        log.warning("Биржа недоступна (%d шаг(ов) подряд): %s",
                                    offline, _short_error(exc))
                else:
                    log.exception("Ошибка в цикле DCA: %s", exc)
            # Сон, прерываемый остановкой.
            if stop_event is not None:
                if stop_event.wait(self.cfg.poll_interval_seconds):
                    break
            else:
                time.sleep(self.cfg.poll_interval_seconds)
        log.info("DCA остановлен.")
