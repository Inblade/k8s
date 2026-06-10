"""Точка входа торгового бота для Binance (консольный запуск)."""
from __future__ import annotations

import logging

from config import Config
from dca_trader import DcaTrader
from exchange import Exchange
from logsetup import setup_logging
from trader import Trader


def create_trader(cfg: Config, log: logging.Logger):
    """Собирает биржу и трейдер, проверяет ключи. Бросает исключение при проблеме.

    Используется и консольным main(), и приложением app.py.
    """
    if not cfg.dry_run and not cfg.testnet:
        log.warning("=" * 60)
        log.warning("ВНИМАНИЕ: РЕАЛЬНАЯ ТОРГОВЛЯ НАСТОЯЩИМИ ДЕНЬГАМИ!")
        log.warning("DRY_RUN=false и TESTNET=false. Ты рискуешь реальными средствами.")
        log.warning("=" * 60)

    if cfg.withdraw_enabled and not cfg.dry_run:
        log.warning("Автовывод ВКЛЮЧЁН: %.0f%% прибыли будет выводиться на %s (%s) "
                    "при накоплении >= %.0f %s. Ключ должен иметь право вывода — "
                    "держи включённым белый список адресов на Binance!",
                    cfg.withdraw_profit_pct, cfg.withdraw_address, cfg.withdraw_network,
                    cfg.withdraw_min_amount, cfg.withdraw_asset)

    exchange = Exchange(cfg.api_key, cfg.api_secret, cfg.testnet, cfg.dry_run)

    # Проверка ключей и прав доступа до начала торговли.
    if not cfg.dry_run:
        info = exchange.verify_credentials(expect_withdraw=cfg.withdraw_enabled)
        log.info("Ключи OK | canTrade=%s | балансы: %s",
                 info["can_trade"], info["balances"] or "пусто")
        if not info["can_trade"]:
            raise PermissionError("Аккаунт не может торговать (canTrade=false).")

    trader = DcaTrader(cfg, exchange) if cfg.strategy == "dca" else Trader(cfg, exchange)
    log.info("Стратегия: %s", cfg.strategy)
    return trader


def _build_alpaca(cfg: Config, log: logging.Logger):
    """DCA-трейдер для акций на Alpaca. paper → песочница (как Binance testnet)."""
    from alpaca_broker import AlpacaBroker  # ленивый импорт: нужен только при ALPACA_ENABLED

    acfg = cfg.for_alpaca()
    if not acfg.api_key or not acfg.api_secret:
        raise ValueError("ALPACA_ENABLED=true, но не заданы APCA_API_KEY_ID / APCA_API_SECRET_KEY")
    broker = AlpacaBroker(acfg.api_key, acfg.api_secret, paper=cfg.alpaca_paper)
    info = broker.verify_credentials()
    log.info("Alpaca OK (%s) | canTrade=%s | акции: %s | кэш: %s",
             "paper" if cfg.alpaca_paper else "LIVE", info["can_trade"],
             ", ".join(acfg.symbols), info["balances"] or "пусто")
    if not info["can_trade"]:
        raise PermissionError("Аккаунт Alpaca не может торговать (trading_blocked).")
    return DcaTrader(acfg, broker, source="alpaca")


def apply_auto_allocation(cfg: Config) -> Config:
    """Перераспределяет общий бюджет между Binance/Alpaca по обратной волатильности
    (крипта ≤ CRYPTO_MAX_WEIGHT). Масштабирует размеры ордеров тем же множителем,
    чтобы соотношение бюджет/ордера осталось валидным. Чистая функция (без сети)."""
    from dataclasses import replace

    from config import STOCK_DCA_DEFAULTS
    from portfolio import ASSET_CLASS_VOL, split_budget

    if not cfg.allocation_auto:
        return cfg
    budgets = {}
    if cfg.binance_enabled:
        budgets["binance"] = cfg.trade_quote_amount
    if cfg.alpaca_enabled:
        budgets["alpaca"] = cfg.alpaca_trade_quote_amount
    if len(budgets) < 2:
        return cfg  # распределять нечего
    total = sum(budgets.values())
    vols = {n: ASSET_CLASS_VOL[n] for n in budgets}
    split = split_budget(total, vols, cfg.crypto_max_weight)

    kb = split["binance"] / cfg.trade_quote_amount if cfg.trade_quote_amount else 1.0
    ka = split["alpaca"] / cfg.alpaca_trade_quote_amount if cfg.alpaca_trade_quote_amount else 1.0
    a_base = cfg.alpaca_dca_base_order if cfg.alpaca_dca_base_order is not None \
        else STOCK_DCA_DEFAULTS["base_order"]
    a_safety = cfg.alpaca_dca_safety_order if cfg.alpaca_dca_safety_order is not None \
        else STOCK_DCA_DEFAULTS["safety_order"]
    return replace(
        cfg,
        trade_quote_amount=split["binance"],
        dca_base_order=cfg.dca_base_order * kb,
        dca_safety_order=cfg.dca_safety_order * kb,
        alpaca_trade_quote_amount=split["alpaca"],
        alpaca_dca_base_order=a_base * ka,
        alpaca_dca_safety_order=a_safety * ka,
    )


def create_traders(cfg: Config, log: logging.Logger) -> tuple[list, dict]:
    """Собирает трейдеры для всех включённых брокеров.

    Возвращает (units, errors): units = [(name, trader)], errors = {name: текст}.
    Сбой одного брокера не мешает запуститься другому.
    """
    units: list = []
    errors: dict = {}
    cfg = apply_auto_allocation(cfg)  # ядро-спутник: бюджеты по волатильности
    if cfg.allocation_auto and cfg.binance_enabled and cfg.alpaca_enabled:
        log.info("Авто-распределение: крипта=%.0f, акции=%.0f USD",
                 cfg.trade_quote_amount, cfg.alpaca_trade_quote_amount)
    if cfg.binance_enabled:
        try:
            units.append(("binance", create_trader(cfg, log)))
        except Exception as exc:  # noqa: BLE001
            errors["binance"] = str(exc)
            log.error("Binance не запущен: %s", exc)
    if cfg.alpaca_enabled:
        try:
            units.append(("alpaca", _build_alpaca(cfg, log)))
        except Exception as exc:  # noqa: BLE001
            errors["alpaca"] = str(exc)
            log.error("Alpaca не запущен: %s", exc)
    return units, errors


def main() -> int:
    setup_logging()
    log = logging.getLogger("bot")
    try:
        cfg = Config.load()
        trader = create_trader(cfg, log)
    except Exception as exc:  # noqa: BLE001 — стартовая диагностика
        log.error("Не удалось запустить бота: %s", exc)
        return 1

    try:
        trader.run()
    except KeyboardInterrupt:
        log.info("Остановлено пользователем. Открытая позиция (если есть) НЕ закрыта.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
