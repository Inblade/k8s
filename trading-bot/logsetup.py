"""Настройка логирования: консоль + файлы с разбивкой по дням и часам.

Файлы пишутся в logs/ГГГГ-ММ-ДД/ЧЧ.log — отдельная папка на каждый день и
отдельный файл на каждый час. Удобно искать, что бот делал в конкретное время.

Под launchd весь вывод консоли перехватывается в bot.log, который никто не
ротирует на ходу. Поэтому консоль намеренно держим тихой в фоновом режиме:
подробности всё равно лежат в logs/, а bot.log остаётся местом для аварий.
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

    def close(self) -> None:
        # Базовый Handler.close() поток не трогает — открытый файл утекал бы
        # при каждой пересборке логирования.
        if self._stream is not None:
            self._stream.close()
            self._stream = None
            self._key = None
        super().close()


def setup_logging(level: int = logging.INFO,
                  console_level: int | None = None) -> None:
    """Поднимает консольный и почасовой файловый хендлеры.

    console_level ограничивает только консоль: в фоновом режиме её вывод
    уходит в bot.log, где ежеминутный пульс не нужен. В файлы logs/ всё
    пишется полностью независимо от этого.
    """
    fmt = logging.Formatter(FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    if console_level is not None:
        console.setLevel(console_level)

    hourly = HourlyDirHandler()
    hourly.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    # Чистим прежние хендлеры, чтобы не дублировать при повторном вызове.
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(console)
    root.addHandler(hourly)

    # Дашборд опрашивает четыре эндпоинта раз в минуту, и werkzeug пишет строку
    # на каждый ответ 200 — 5760 строк в сутки и две трети объёма лога при
    # нулевой пользе. Оставляем только то, что говорит о проблеме: 4xx/5xx и
    # ошибки самого сервера по-прежнему видны, потому что они уровня WARNING+.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
