"""Уведомления в Telegram. Тихо молчит, если креды не заданы или сеть недоступна —
торговля НИКОГДА не должна падать из-за уведомления. Креды берёт из окружения
(TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID), а если их нет — из .env рядом со скриптом
(тот же канал, что alert-check.sh и go_live_check.py)."""
from __future__ import annotations

import logging
import os
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger("bot.notify")
_DIR = Path(__file__).parent
_creds_cache: tuple[str, str] | None = None


def _creds() -> tuple[str, str]:
    global _creds_cache
    if _creds_cache is not None:
        return _creds_cache
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    env = _DIR / ".env"
    if (not token or not chat) and env.exists():
        try:
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("TELEGRAM_BOT_TOKEN=") and not token:
                    token = line.split("=", 1)[1].strip().strip("\"'")
                elif line.startswith("TELEGRAM_CHAT_ID=") and not chat:
                    chat = line.split("=", 1)[1].strip().strip("\"'")
        except OSError:
            pass
    _creds_cache = (token, chat)
    return _creds_cache


def send(text: str) -> bool:
    """Шлёт сообщение. Возвращает True при успехе, False если не настроено/ошибка."""
    token, chat = _creds()
    if not token or not chat:
        return False
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=10)
        return True
    except Exception as e:  # сеть/таймаут/HTTP — не роняем торговлю
        log.warning("не смог отправить в Telegram: %s", e)
        return False


def trade(symbol: str, side: str, reason: str, price: float, qty: float, quote: float,
          avg_entry: float, realized_pnl: float, source: str = "") -> None:
    """Форматирует и шлёт состояние после сделки."""
    host = f" [{source}]" if source else ""
    if side == "SELL":
        spent = quote - realized_pnl
        pct = (realized_pnl / spent * 100) if spent else 0.0
        emoji = "✅" if realized_pnl >= 0 else "🔻"
        text = (f"{emoji} SELL {symbol} · {reason}{host}\n"
                f"{qty:.8f} @ {price:.2f} → {quote:.2f} USDT\n"
                f"P&L {realized_pnl:+.2f} USDT ({pct:+.2f}%)")
    else:  # BUY
        emoji = "🟢" if "базов" in reason else "🟡"
        text = (f"{emoji} BUY {symbol} · {reason}{host}\n"
                f"+{qty:.8f} за {quote:.2f} USDT @ {price:.2f}\n"
                f"средняя {avg_entry:.2f}")
    send(text)
