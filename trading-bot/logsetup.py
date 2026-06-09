"""Настройка логирования: консоль + файлы с разбивкой по дням и часам.

Файлы пишутся в logs/ГГГГ-ММ-ДД/ЧЧ.log — отдельная папка на каждый день и
отдельный файл на каждый час. Удобно искать, что бот делал в конкретное время.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).with_name("logs")
FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"


class HourlyDirHandler(logging.Handler):
    """Пишет логи в logs/<дата>/<час>.log, переключая файл при смене часа."""

    def __init__(self, base_dir: Path = LOG_DIR):
        super().__init__()
        self.base = base_dir
        self._key: str | None = None
        self._stream = None

    def _open_for(self, t: datetime) -> None:
        key = t.strftime("%Y-%m-%d %H")
        if key == self._key and self._stream is not None:
            return
        if self._stream is not None:
            self._stream.close()
        path = self.base / t.strftime("%Y-%m-%d") / f"{t.strftime('%H')}.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = path.open("a", encoding="utf-8")
        self._key = key

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._open_for(datetime.fromtimestamp(record.created))
            self._stream.write(self.format(record) + "\n")
            self._stream.flush()
        except Exception:  # noqa: BLE001 — логирование не должно ронять бота
            self.handleError(record)


def setup_logging(level: int = logging.INFO) -> None:
    fmt = logging.Formatter(FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)

    hourly = HourlyDirHandler()
    hourly.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    # Чистим прежние хендлеры, чтобы не дублировать при повторном вызове.
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(console)
    root.addHandler(hourly)
