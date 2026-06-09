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


def create_traders(cfg: Config, log: logging.Logger) -> tuple[list, dict]:
    """Собирает трейдеры для всех включённых брокеров.

    Возвращает (units, errors): units = [(name, trader)], errors = {name: текст}.
    Сбой одного брокера не мешает запуститься другому.
    """
    units: list = []
    errors: dict = {}
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
