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

    exchange = Exchange(cfg.api_key, cfg.api_secret, cfg.testnet, cfg.dry_run,
                        max_jump_pct=cfg.price_max_jump_pct,
                        confirm_ticks=cfg.price_confirm_ticks,
                        stale_seconds=cfg.price_stale_seconds)

    # Проверка ключей и прав доступа до начала торговли.
    if not cfg.dry_run:
        info = exchange.verify_credentials(expect_withdraw=cfg.withdraw_enabled)
        # На testnet в аккаунте лежат сотни фейковых монет — целиком этот словарь
        # раздувал каждую строку старта до килобайт. Показываем только то, чем
        # реально торгуем, остальное — счётчиком.
        bal = info["balances"] or {}
        used: set[str] = set()
        for sym in cfg.symbols:
            quote = exchange.quote_asset(sym)
            used.update({quote, sym[: -len(quote)] if sym.endswith(quote) else sym})
        shown = {k: v for k, v in bal.items() if k in used}
        log.info("Ключи OK | canTrade=%s | балансы: %s%s",
                 info["can_trade"], shown or "пусто",
                 f" (+ещё {len(bal) - len(shown)} активов)" if len(bal) > len(shown) else "")
        if not info["can_trade"]:
            raise PermissionError("Аккаунт не может торговать (canTrade=false).")

    trader = DcaTrader(cfg, exchange) if cfg.strategy == "dca" else Trader(cfg, exchange)
    log.info("Стратегия: %s", cfg.strategy)
    return trader


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
