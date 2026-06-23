"""Настройки парсера отзывов Ozon."""
from pathlib import Path

# Период актуальности отзывов (в днях). Отзывы старше — отбрасываются.
REVIEW_PERIOD_DAYS = 365

# Предохранитель: максимум отзывов на один товар.
MAX_REVIEWS_PER_PRODUCT = 500

# Случайные паузы (секунды): держат нагрузку ниже порога rate-limit Ozon.
PAGE_DELAY = (1.0, 3.0)      # между прокрутками карточки (bootstrap)
FETCH_DELAY = (0.4, 0.9)     # между курсорными запросами отзывов
PRODUCT_DELAY = (3.0, 6.0)   # между товарами

# Браузер
HEADLESS = True              # переопределяется флагом --show
NAV_TIMEOUT_MS = 60_000

# Пути
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"     # сюда пишутся {product_id}.json
PROFILE_DIR = BASE_DIR / ".profile"  # сохранённая сессия/cookie браузера
