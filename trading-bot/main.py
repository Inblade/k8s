"""Точка входа торгового бота для Binance."""
from __future__ import annotations

import logging

from config import Config
from dca_trader import DcaTrader
from exchange import Exchange
from logsetup import setup_logging
from trader import Trader


def main() -> int:
    setup_logging()
    log = logging.getLogger("bot")
    try:
        cfg = Config.load()
    except ValueError as exc:
        log.error("Ошибка конфигурации: %s", exc)
        return 1

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
        try:
            info = exchange.verify_credentials(expect_withdraw=cfg.withdraw_enabled)
        except Exception as exc:  # noqa: BLE001 — стартовая диагностика
            log.error("Проверка API-ключей не пройдена: %s", exc)
            return 1
        log.info("Ключи OK | canTrade=%s | балансы: %s",
                 info["can_trade"], info["balances"] or "пусто")
        if not info["can_trade"]:
            log.error("Аккаунт не может торговать (canTrade=false). Проверь права ключа.")
            return 1

    trader = DcaTrader(cfg, exchange) if cfg.strategy == "dca" else Trader(cfg, exchange)
    log.info("Стратегия: %s", cfg.strategy)

    try:
        trader.run()
    except KeyboardInterrupt:
        log.info("Остановлено пользователем. Открытая позиция (если есть) НЕ закрыта.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
