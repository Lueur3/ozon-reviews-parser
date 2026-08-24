"""Общая настройка тестов.

Выполняется до импорта тестовых модулей, а значит до того, как ozon.logging_setup
создаст файловый обработчик. Благодаря этому прогон тестов не дописывает строки
в рабочий `logs/reviews.log` проекта.
"""
import tempfile
from pathlib import Path

from ozon import config

config.LOG_DIR = Path(tempfile.mkdtemp(prefix="ozon-tests-logs-"))
