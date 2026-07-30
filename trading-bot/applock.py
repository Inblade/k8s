"""Блокировка «только один экземпляр бота».

Два одновременно запущенных бота торговали бы одним счётом: дублировали ордера и
перетирали файлы состояния позиций. Поэтому при старте берём эксклюзивный лок на
файл. Лок держится ОС и освобождается автоматически при завершении процесса —
даже после kill -9, так что «протухших» локов не остаётся.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path

LOCK_FILE = Path(__file__).with_name(".bot.lock")


class AlreadyRunning(RuntimeError):
    """Другой экземпляр бота уже работает."""


def acquire(path: Path = LOCK_FILE):
    """Берёт эксклюзивный лок. Возвращает файловый объект — его нужно держать
    открытым всё время работы (закрытие снимает лок).

    Бросает AlreadyRunning, если лок уже занят другим процессом.
    """
    fh = path.open("a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        fh.seek(0)
        pid = fh.read().strip() or "?"
        fh.close()
        raise AlreadyRunning(
            f"бот уже запущен (PID {pid}). Останови его, прежде чем запускать новый: "
            f"pkill -f app.py"
        ) from exc
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    return fh
