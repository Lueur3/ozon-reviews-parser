"""Единая настройка логирования для всех модулей пакета.

Раньше файловый обработчик навешивался в collector.py на уровне модуля — то есть
как побочный эффект импорта и только для одного логгера. Здесь настройка ленивая
и общая: все логгеры `ozon.*` пишут в один файл с одинаковым форматом.
"""
import logging

from . import config

_configured = False


def get_logger(name: str) -> logging.Logger:
    """Логгер пакета. Файловый обработчик настраивается один раз при первом вызове."""
    global _configured
    pkg = logging.getLogger("ozon")
    # Если логирование уже настроено снаружи (пакет импортировали как библиотеку),
    # не трогаем чужие обработчики и уровень.
    if not _configured and not pkg.handlers:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(config.LOG_DIR / "reviews.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        pkg.addHandler(handler)
        pkg.setLevel(config.LOG_LEVEL)
        _configured = True
    return logging.getLogger(name)
