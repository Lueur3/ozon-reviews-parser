"""Настройки парсера отзывов Ozon."""
import logging
from pathlib import Path

# Период актуальности отзывов (в днях). Отзывы старше — отбрасываются.
REVIEW_PERIOD_DAYS = 365

# Предохранитель: максимум отзывов на один товар.
MAX_REVIEWS_PER_PRODUCT = 500

# Случайные паузы (секунды): держат нагрузку ниже порога rate-limit Ozon.
PAGE_DELAY = (1.0, 3.0)      # между прокрутками карточки (bootstrap)
FETCH_DELAY = (0.15, 0.35)   # между курсорными запросами отзывов
PRODUCT_DELAY = (3.0, 6.0)   # между товарами

# Браузер (headless задаётся флагом --headless; по умолчанию видимое окно).
# 60 с — карточка Ozon с холодным профилем и анти-бот-проверкой грузится до ~30 с;
# берём двойной запас, чтобы медленный интернет не ронял сбор.
NAV_TIMEOUT_MS = 60_000

# Самопроверка (--doctor): эталонный товар со всеми секциями и пороги PASS
DOCTOR_URL = "https://www.ozon.ru/product/138342427/"
DOCTOR_MIN_CHARS = 5         # минимум характеристик для PASS
DOCTOR_MAX_REVIEWS = 20      # лёгкий сбор — проверке хватает

# Логирование
LOG_LEVEL = logging.INFO

# Пути (BASE_DIR — корень проекта, на уровень выше пакета)
BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"     # сюда пишутся {product_id}.json
PROFILE_DIR = BASE_DIR / ".profile"  # сохранённая сессия/cookie браузера
LOG_DIR = BASE_DIR / "logs"          # logs/reviews.log
