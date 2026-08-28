"""Сбор отзывов/Q&A/карточки одного товара через сессию браузера (Ozon).

Заголовки внутреннего API берём из живой сессии браузера (он прошёл анти-бот),
дальше пагинацию ленты отзывов гоняем через fetch в контексте страницы.

Анонимному пользователю Ozon отдаёт ограниченный объём ленты («Войдите,
чтобы посмотреть больше»). Если хронологическая лента упирается в эту стену
раньше, чем покрывает заданный период, добираем отзывы сортировками по оценке
(низкая/высокая) — так в окно попадает больше негатива и позитива.

Состояние сбора живёт в атрибутах ReviewCollector (один экземпляр = один товар),
а шаги — в методах; точка входа — collect().
"""
import asyncio

from . import api, config, interrupt, parse
from .errors import BootstrapError, CaptchaTimeout
from .logging_setup import get_logger
from .stats import compute_stats
from .urls import extract_product_id

log = get_logger("ozon.collector")


def _is_empty(rev) -> bool:
    return not (rev.text.strip() or rev.pros.strip() or rev.cons.strip())


class ReviewCollector:
    """Сбор отзывов, Q&A и карточки одного товара. Жизненный цикл — collect()."""

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
        self.headers = None                # заголовки внутреннего API из сессии
        self._pending: list = []           # незавершённые обработчики response
        self._chrono_uuids: set = set()    # uuid из хронологической ленты (для непредвзятой статистики)
        self._oldest_ts = 0                # самая ранняя дата среди собранных (для стопа по периоду)
        self.questions_widget_seen = False  # отличить «вопросов нет» от «разметка сменилась»

        # реквизиты товара (заполняются в _bootstrap по resolved_url)
        self.resolved_url = ""
        self.product_id = None
        self.pid_int = None
        self.origin = ""
        self.rpath = ""    # путь ленты отзывов /product/.../reviews/
        self.ppath = ""    # путь карточки /product/.../
        self.client = None  # OzonClient — создаётся после bootstrap, когда есть заголовки

    # ------------------------------------------------------------------ #
    # Точка входа
    # ------------------------------------------------------------------ #
    async def collect(self):
        """Вернуть (list[Review], meta)."""
        await self._bootstrap()

        price, characteristics = await self._collect_extras()
        log.info("extras: price=%s характеристик=%d", bool(price), len(characteristics))

        questions = await self._collect_questions()
        log.info("вопросов с ответами: %d", len(questions))

        await self._collect_review_feed()

        stats = self._stats()
        reviews, skipped = self._filtered()
        log.info("итог: собрано=%d, пустых пропущено=%d, после фильтров=%d (all_variants=%s)",
                 len(self.reviews_by_uuid), skipped, len(reviews), self.all_variants)
        return reviews, self._meta(price, characteristics, questions, stats)

    # ------------------------------------------------------------------ #
    # Bootstrap и слушатель ответов
    # ------------------------------------------------------------------ #
    async def _bootstrap(self):
        """Открыть карточку, снять заголовки API и курсор полки, определить id товара."""
        def schedule(resp):
            self._pending.append(asyncio.ensure_future(self._on_response(resp)))

        self.page.on("response", schedule)
        try:
            try:
                await self.page.goto(self.url, wait_until="domcontentloaded")
            except Exception as e:
                # Самая частая причина — включённый VPN: Ozon рвёт соединение
                # ещё до загрузки страницы (net::ERR_FAILED).
                raise BootstrapError(
                    f"страница не открылась: {self.url}. Проверь, что VPN выключен "
                    f"и есть доступ к сети. Причина: {e.__class__.__name__}") from None
            await self.page.wait_for_timeout(config.PAGE_SETTLE_MS)
            await self._drain()
            self.resolved_url = self.page.url
            self.product_id = extract_product_id(self.resolved_url)
            for _ in range(config.HEADER_SCROLLS):
                if self.headers and self.shelf_next:
                    break
                await self.page.mouse.wheel(0, config.SCROLL_STEP_PX)
                await self.page.wait_for_timeout(config.delay_ms(self.page_delay))
                await self._drain()
        finally:
            await self._drain()
            self.page.remove_listener("response", schedule)

        self.origin = api.origin_of(self.resolved_url)
        self.ppath = api.product_path(self.resolved_url)
        self.rpath = api.reviews_path(self.resolved_url)
        try:
            self.pid_int = int(self.product_id)
        except (TypeError, ValueError):
            self.pid_int = None

        log.info("bootstrap: id=%s headers=%s shelf_next=%s reviews=%d",
                 self.product_id, bool(self.headers), bool(self.shelf_next), len(self.reviews_by_uuid))
        # Без заголовков живой сессии любой fetch получит 403 — падаем сразу с понятной
        # причиной, а не собираем пустоту (раньше здесь был молчаливый фолбэк на {}).
        if not self.headers:
            raise BootstrapError(
                "не удалось снять заголовки внутреннего API Ozon с живой сессии. "
                "Вероятно: страница не загрузилась, VPN включён, или Ozon сменил эндпоинт. "
                f"Итоговый URL: {self.resolved_url or self.url}")

        self.client = api.OzonClient(self.page, self.origin, self.headers,
                                     recovery_url=self.resolved_url)

    def _absorb(self, data: dict) -> int:
        """Вынуть отзывы из webListReviews в reviews_by_uuid; вернуть число новых."""
        res = parse.extract_reviews_widget(data)
        if not res:
            return 0
        reviews, prods, sc, tot = res
        if prods:
            self.products.update(prods)
        if sc is not None:
            self.score = sc
        if tot is not None:
            self.total = tot
        before = len(self.reviews_by_uuid)
        for r in reviews:
            uuid = r.get("uuid")
            if not uuid:
                continue
            self.reviews_by_uuid[uuid] = r
            # ведём минимум по ходу: пересчёт по всему буферу на каждой странице
            # стоил бы O(n) при n до нескольких тысяч
            ts = r.get("publishedAt") or r.get("createdAt") or 0
            if ts and (not self._oldest_ts or ts < self._oldest_ts):
                self._oldest_ts = ts
        return len(self.reviews_by_uuid) - before

    async def _on_response(self, resp):
        """Перехват entrypoint/composer-ответов: снять headers, абсорбировать, поймать shelf_next."""
        try:
            if "json" not in resp.headers.get("content-type", ""):
                return
            if "entrypoint-api" not in resp.url and "composer-api" not in resp.url:
                return
            if "entrypoint-api" in resp.url and self.headers is None:
                self.headers = api.session_headers(await resp.request.all_headers())
            data = await resp.json()
        except Exception as e:
            # Ответ мог быть отменён/не-JSON — это штатно, но причину пишем в лог,
            # иначе поломка структуры Ozon выглядит как «просто пусто».
            log.debug("ответ %s не разобран: %r", getattr(resp, "url", "?"), e)
            return
        self._absorb(data)
        np = data.get("nextPage")
        if np and "review" in np.lower() and self.shelf_next is None:
            self.shelf_next = np

    async def _drain(self):
        """Дождаться накопленных обработчиков response.

        При отмене (Ctrl+C) незавершённые задачи отменяем явно, иначе asyncio
        ругается «Future exception was never retrieved» уже после выхода.
        """
        if not self._pending:
            return
        pending, self._pending = self._pending, []
        try:
            await asyncio.gather(*pending, return_exceptions=True)
        except asyncio.CancelledError:
            for task in pending:
                task.cancel()
            raise

    # ------------------------------------------------------------------ #
    # Доп. данные карточки
    # ------------------------------------------------------------------ #
    async def _collect_extras(self):
        """(price, characteristics): карточка (краткие) + /features/ (полные)."""
        price, characteristics = {}, {}
        try:
            pdata = await self.client.fetch(self.ppath)
            price = parse.parse_price(pdata)
            characteristics = parse.parse_characteristics(pdata)
        except CaptchaTimeout:
            raise                     # сессия мертва — дальше каждый fetch ждал бы ещё 5 мин
        except Exception as e:
            log.warning("карточка (цена/характеристики) не получена: %r", e)
        try:
            full = parse.parse_characteristics(
                await self.client.fetch(api.features_path(self.ppath)))
            if len(full) > len(characteristics):
                characteristics = full
        except CaptchaTimeout:
            raise
        except Exception as e:
            log.warning("features (полные характеристики) не получены: %r", e)
        return price, characteristics

    async def _collect_questions(self, max_pages: int = config.QUESTION_PAGES) -> list:
        """Вопросы с ответами, сортировка «сначала с ответом».

        Останавливаемся, когда курсор кончился или страница не принесла новых
        отвеченных вопросов — при этой сортировке дальше идут только без ответов.
        В прежней разметке у вопросов бывала пометка «Ещё N ответ»: для них
        ответы догружаются со страницы вопроса.
        """
        questions = []
        seen_q = set()
        # Новая лента вопросов листается курсором (виджет paginator), а не ?page=N:
        # с фиксированным номером страницы Ozon возвращает одну и ту же первую десятку.
        param = api.questions_page(self.ppath, 1)
        for page_n in range(1, max_pages + 1):
            if not param or interrupt.requested():
                break
            try:
                qdata = await self.client.fetch(param)
            except CaptchaTimeout:
                raise
            except Exception as e:
                log.warning("вопросы: страница %d не получена: %r", page_n, e)
                break
            if parse.question_widget(qdata) is not None:
                self.questions_widget_seen = True
            new = [q for q in parse.parse_questions(qdata, answered_only=True)
                   if q["text"] not in seen_q]
            if not new:
                break
            for q in new:
                seen_q.add(q["text"])
                if q.get("_has_more") and q.get("_id"):
                    try:
                        full = parse.parse_questions(
                            await self.client.fetch(api.question_page(self.ppath, q["_id"])),
                            answered_only=False)
                        if full and len(full[0]["answers"]) > len(q["answers"]):
                            q["answers"] = full[0]["answers"]
                    except CaptchaTimeout:
                        raise
                    except Exception as e:
                        log.warning("вопрос %s: доп.ответы не получены: %r", q.get("_id"), e)
                q.pop("_id", None)
                q.pop("_has_more", None)
                questions.append(q)
            param = parse.next_page(qdata)
            await self.page.wait_for_timeout(config.delay_ms(config.FETCH_DELAY))
        return questions

    # ------------------------------------------------------------------ #
    # Лента отзывов
    # ------------------------------------------------------------------ #
    async def _run_cursor(self, param: str, label: str, date_sorted: bool) -> str:
        """Гонять курсор пагинации. Причина остановки: cutoff|end|limit|error."""
        pages = 0
        empty = 0
        while param and "review" in param.lower() and pages < config.MAX_FETCH_PAGES:
            if interrupt.requested():
                log.info("[%s] stop: остановка по запросу пользователя", label)
                return "interrupted"
            if len(self.reviews_by_uuid) >= self.max_reviews * config.COLLECT_OVERSHOOT:
                log.info("[%s] stop: лимит набран", label)
                return "limit"
            try:
                data = await self.client.fetch(param)
            except CaptchaTimeout:
                raise
            except Exception as e:
                log.warning("[%s] fetch упал: %r", label, e)
                return "error"
            added = self._absorb(data)
            pages += 1
            oldest = self._oldest_ts
            log.info("[%s] page %d: added=%d total=%d oldest=%s hasNext=%s",
                     label, pages, added, len(self.reviews_by_uuid),
                     parse.ts_to_date(oldest), bool(data.get("nextPage")))
            if date_sorted and oldest and oldest < self.cutoff:
                log.info("[%s] stop: достигнут период", label)
                return "cutoff"
            empty = empty + 1 if added == 0 else 0
            if empty >= config.EMPTY_PAGES_LIMIT:
                log.info("[%s] stop: %d страниц без новых (стена анонима/конец)", label, config.EMPTY_PAGES_LIMIT)
                return "end"
            param = data.get("nextPage")
            await self.page.wait_for_timeout(config.delay_ms(config.FETCH_DELAY))
        return "end"

    async def _collect_review_feed(self):
        """Основная лента /reviews/, затем фолбэк на полку или добор сортировками по оценке."""
        before_deep = len(self.reviews_by_uuid)
        deep = api.reviews_feed(self.rpath, api.SORT_NEWEST)
        await self._run_cursor(deep, "reviews", date_sorted=True)
        # непредвзятая хронологическая выборка для статистики (до доборов по оценке)
        self._chrono_uuids = set(self.reviews_by_uuid)

        if len(self.reviews_by_uuid) - before_deep <= 3 and self.shelf_next:
            # лента не отдалась — откат на «полку» отзывов карточки
            log.info("лента /reviews/ дала мало — откат на полку карточки")
            await self._run_cursor(self.shelf_next, "shelf", date_sorted=True)
            self._chrono_uuids = set(self.reviews_by_uuid)  # полка тоже хронологическая
        else:
            # добор сортировками по оценке: каждая отдаёт свой срез (~+50% уникальных в окне),
            # заодно гарантирует негатив и позитив. Анонимно лента ограничена ~990 на сортировку.
            for srt, label in ((api.SORT_SCORE_ASC, "low"), (api.SORT_SCORE_DESC, "high")):
                await self._run_cursor(api.reviews_feed(self.rpath, srt), label, date_sorted=False)

    # ------------------------------------------------------------------ #
    # Результат
    # ------------------------------------------------------------------ #
    def _filtered(self):
        """(list[Review], skipped_empty): период, вариант, пустые, сортировка «сначала новые», лимит."""
        out = []
        skipped_empty = 0
        for raw in self.reviews_by_uuid.values():
            ts = raw.get("publishedAt") or raw.get("createdAt") or 0
            if ts < self.cutoff:
                continue
            if not self.all_variants and self.pid_int is not None and raw.get("itemId") != self.pid_int:
                continue
            rev = parse.to_review(raw, self.products)
            if _is_empty(rev):
                skipped_empty += 1
                continue
            out.append(rev)
        out.sort(key=lambda r: r.date, reverse=True)
        return out[:self.max_reviews], skipped_empty

    def _stats(self) -> dict:
        """Статистика по непредвзятой хронологической выборке (без доборов по оценке; overall — из Ozon)."""
        chrono = [self.reviews_by_uuid[u] for u in self._chrono_uuids]
        return compute_stats(chrono, self.score, self.total, parse.now_local())

    def _meta(self, price: dict, characteristics: dict, questions: list, stats: dict) -> dict:
        """Сводка meta для runner."""
        return {
            "product_id": self.product_id,
            "resolved_url": self.resolved_url,
            "name": (self.products.get(str(self.product_id)) or {}).get("name", ""),
            "variant": parse.variant_map(self.product_id, self.products),
            "price": price,
            "stats": stats,
            "characteristics": characteristics,
            "questions": questions,
            "questions_widget_seen": self.questions_widget_seen,
            "score": self.score,
            "total": self.total,
        }
