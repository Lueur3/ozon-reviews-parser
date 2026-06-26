"""СКЕЛЕТ: перенос collect_reviews в класс ReviewCollector.

Это каркас-план, по которому переносим логику из ozon/reviews.py. Рабочая
реализация пока остаётся в reviews.py — здесь только структура: состояние,
сигнатуры методов и порядок вызовов в collect(). Тела-заглушки помечены
NotImplementedError с указанием участка reviews.py для переноса.

Зачем класс: сейчас collect_reviews держит всё состояние в замыканиях
(raw_by_uuid, state, headers, pending) и вложенных функциях. Класс делает
это состояние явными атрибутами, а шаги — методами; функцию-монолит
заменяет читаемый конвейер collect().

План перевода после реализации:
1. перенести тела методов из reviews.py (ссылки в докстрингах);
2. runner.py: collect_reviews(...) → ReviewCollector(page, url, ...).collect();
3. удалить collect_reviews и вложенные функции из reviews.py
   (модульные хелперы _collect_extras/_collect_questions/_filter_reviews
   станут методами; _is_empty можно оставить общим);
4. тесты test_reviews.py адаптировать под ReviewCollector._filtered.
"""
import asyncio
from urllib.parse import urlparse

import config
from . import parse
from .urls import extract_product_id


class ReviewCollector:
    """Сбор отзывов, Q&A и карточки одного товара через живую сессию браузера.

    Один экземпляр = один товар. Жизненный цикл — метод collect():
    bootstrap → цена/характеристики → вопросы → лента отзывов (курсоры) →
    фильтрация → (list[Review], meta).
    """

    def __init__(self, page, url, *, period_days, all_variants, max_reviews, page_delay):
        self.page = page
        self.url = url
        self.all_variants = all_variants
        self.max_reviews = max_reviews
        self.page_delay = page_delay
        self.cutoff = parse.cutoff_ts(period_days)

        # буферы накопления (заполняются по ходу сбора)
        self.reviews_by_uuid: dict = {}    # uuid -> сырой отзыв (дедуп по uuid)
        self.products: dict = {}           # id -> карточка варианта (для variant_map)
        self.score = None                  # средняя оценка товара (productScore)
        self.total = None                  # всего отзывов на товаре (paging.total)
        self.shelf_next = None             # курсор «полки» отзывов карточки (фолбэк)
        self.headers: dict | None = None   # заголовки внутреннего API из сессии
        self._pending: list = []           # незавершённые обработчики response

        # реквизиты товара (заполняются в _bootstrap по resolved_url)
        self.resolved_url = ""
        self.product_id = None
        self.pid_int = None
        self.origin = ""
        self.rpath = ""    # путь ленты отзывов /product/.../reviews/
        self.ppath = ""    # путь карточки /product/.../

    # ------------------------------------------------------------------ #
    # Точка входа
    # ------------------------------------------------------------------ #
    async def collect(self):
        """Вернуть (list[Review], meta). Порядок шагов — как в текущем collect_reviews."""
        await self._bootstrap()
        price, characteristics = await self._collect_extras()
        questions = await self._collect_questions()
        await self._collect_review_feed()
        reviews, _skipped = self._filtered()
        return reviews, self._meta(price, characteristics, questions)

    # ------------------------------------------------------------------ #
    # Bootstrap и слушатель ответов
    # ------------------------------------------------------------------ #
    async def _bootstrap(self):
        """Открыть карточку, снять заголовки API и курсор полки, определить id.

        Переносим reviews.py:115-211 — goto, прокрутки до появления headers и
        shelf_next, затем resolved_url/product_id/pid_int/origin/rpath/ppath.
        """
        raise NotImplementedError

    def _absorb(self, data: dict) -> int:
        """Вынуть отзывы из webListReviews в reviews_by_uuid; вернуть число новых.

        Переносим reviews.py:141-157 (absorb): обновляет products, score, total.
        """
        raise NotImplementedError

    async def _on_response(self, resp):
        """Перехват entrypoint/composer-ответов: снять headers, абсорбировать, поймать shelf_next.

        Переносим reviews.py:159-175 (on_response).
        """
        raise NotImplementedError

    async def _drain(self):
        """Дождаться накопленных обработчиков response. Переносим reviews.py:180-183."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Сетевой fetch (через контекст страницы)
    # ------------------------------------------------------------------ #
    async def _fetch(self, param: str) -> dict:
        """GET entrypoint-api JSON в контексте страницы; ждать решения капчи.

        Переносим reviews.py:213-234 (_fetch_json): при капче/блоке открывает
        resolved_url в окне и ждёт пользователя, потом повторяет.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Доп. данные карточки
    # ------------------------------------------------------------------ #
    async def _collect_extras(self):
        """(price, characteristics): карточка (краткие) + /features/ (полные).

        Переносим модульный _collect_extras (reviews.py): self._fetch вместо fetch,
        self.ppath вместо ppath.
        """
        raise NotImplementedError

    async def _collect_questions(self, max_pages: int = 12) -> list:
        """Вопросы с ответами (сорт «сначала с ответом»); догрузка всех ответов.

        Переносим модульный _collect_questions (reviews.py) на self._fetch/self.ppath.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Лента отзывов
    # ------------------------------------------------------------------ #
    async def _run_cursor(self, param: str, label: str, date_sorted: bool) -> str:
        """Гонять курсор пагинации; причина остановки: cutoff|end|limit|error.

        Переносим reviews.py:246-276 (run_cursor) на self.reviews_by_uuid/self._fetch,
        лимит self.max_reviews * 3, расчёт oldest как в фильтре (publishedAt→createdAt).
        """
        raise NotImplementedError

    async def _collect_review_feed(self):
        """Основная лента /reviews/, затем фолбэк на полку или добор сортировками.

        Переносим reviews.py:278-291: published_at_desc; если дало мало и есть
        shelf_next — полка; иначе score_asc/score_desc.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Результат
    # ------------------------------------------------------------------ #
    def _filtered(self):
        """(list[Review], skipped_empty): период, вариант, пустые, сортировка, лимит.

        Переносим модульный _filter_reviews (reviews.py) на self.* — это покрыто
        тестами test_reviews.py, поведение менять нельзя.
        """
        raise NotImplementedError

    def _meta(self, price: dict, characteristics: dict, questions: list) -> dict:
        """Сводка meta для runner. Переносим reviews.py:298-308."""
        raise NotImplementedError
