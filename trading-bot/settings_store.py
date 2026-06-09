"""Чтение и запись настроек в .env для редактирования из окна приложения.

Секреты при отдаче в UI маскируются. Сохранение пишет в .env через python-dotenv,
сохраняя остальные строки файла.
"""
from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values, set_key

ENV_PATH = Path(__file__).with_name(".env")

# Поля, которые показываем/редактируем в окне настроек (порядок = порядок в форме).
EDITABLE = [
    "STRATEGY", "SYMBOLS", "SYMBOL", "INTERVAL", "TRADE_QUOTE_AMOUNT",
    "DCA_BASE_ORDER", "DCA_SAFETY_ORDER", "DCA_MAX_SAFETY_ORDERS",
    "DCA_PRICE_DEVIATION_PCT", "DCA_TAKE_PROFIT_PCT", "DCA_STOP_LOSS_PCT",
    "DCA_ATR_ENABLED", "DCA_TREND_FILTER_ENABLED", "ADAPTIVE_ENABLED", "POLL_INTERVAL_SECONDS",
    "WITHDRAW_ENABLED", "WITHDRAW_PROFIT_PCT", "WITHDRAW_MIN_AMOUNT",
    "WITHDRAW_ASSET", "WITHDRAW_NETWORK", "WITHDRAW_ADDRESS",
    "BINANCE_ENABLED", "BINANCE_API_KEY", "BINANCE_API_SECRET",
    "BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_API_SECRET",
    "ALPACA_ENABLED", "ALPACA_PAPER", "ALPACA_SYMBOLS",
    "ALPACA_TRADE_QUOTE_AMOUNT",
    "ALPACA_DCA_BASE_ORDER", "ALPACA_DCA_SAFETY_ORDER", "ALPACA_DCA_MAX_SAFETY_ORDERS",
    "ALPACA_DCA_PRICE_DEVIATION_PCT", "ALPACA_DCA_TAKE_PROFIT_PCT", "ALPACA_DCA_STOP_LOSS_PCT",
    "APCA_API_KEY_ID", "APCA_API_SECRET_KEY",
]

SECRET_FIELDS = {"BINANCE_API_SECRET", "BINANCE_TESTNET_API_SECRET",
                 "BINANCE_API_KEY", "BINANCE_TESTNET_API_KEY",
                 "APCA_API_KEY_ID", "APCA_API_SECRET_KEY"}

# Значение-заглушка: если пришло из UI без изменений — не перезаписываем секрет.
MASK = "••••••••"


def _mask(key: str, value: str) -> str:
    if not value:
        return ""
    if key in SECRET_FIELDS:
        # Показываем только хвост, чтобы можно было отличить ключи.
        return MASK + value[-4:] if len(value) > 4 else MASK
    return value


def read_settings() -> dict:
    """Текущие значения для формы (секреты замаскированы)."""
    raw = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    return {k: _mask(k, raw.get(k, "") or "") for k in EDITABLE}


def set_value(key: str, value: str) -> None:
    """Записать произвольный ключ в .env (например, TESTNET для смены режима)."""
    if not ENV_PATH.exists():
        ENV_PATH.touch()
    set_key(str(ENV_PATH), key, str(value), quote_mode="never")


def save_settings(values: dict) -> list[str]:
    """Сохраняет переданные поля в .env. Маскированные секреты пропускает.

    Возвращает список реально изменённых ключей.
    """
    if not ENV_PATH.exists():
        ENV_PATH.touch()
    changed = []
    for key in EDITABLE:
        if key not in values:
            continue
        val = str(values[key])
        # Пустое значение = «не трогать»: не затираем ключи/булевы дефолты пустотой
        # (иначе включённый брокер мог бы выключиться после сохранения настроек).
        if val.strip() == "":
            continue
        # Замаскированное значение (не редактировали) — не трогаем.
        if key in SECRET_FIELDS and val.startswith(MASK):
            continue
        set_key(str(ENV_PATH), key, val, quote_mode="never")
        changed.append(key)
    return changed
