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
import json
import logging
import random
from urllib.parse import quote, urlparse

import config
from . import parse
from .urls import extract_product_id

_API_PATH = "/api/entrypoint-api.bx/page/json/v2?url="
_HEADER_SCROLLS = 12
_MAX_FETCH_PAGES = 4000
_EMPTY_LIMIT = 8
_VARIANT_MODE = "reviewsVariantMode=2"  # все варианты (фильтр по варианту делаем сами)
_DROP_HEADERS = {"host", "cookie", "content-length", "accept-encoding", "connection",
                 "user-agent", "origin", "referer"}

_CAPTCHA_WAIT_ITERS = 75   # ~5 минут (по 4 с) ждём, пока пользователь решит капчу в окне
_FETCH_JS = """async ({u, h}) => {
    const r = await fetch(u, {headers: h, credentials: 'include'});
    return {status: r.status, text: await r.text()};
}"""

_LOGDIR = config.BASE_DIR / "logs"
_LOGDIR.mkdir(exist_ok=True)
log = logging.getLogger("ozon.collector")
if not log.handlers:
    _h = logging.FileHandler(_LOGDIR / "reviews.log", encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)


def _origin(url: str) -> str:
    pr = urlparse(url)
    return f"{pr.scheme}://{pr.netloc}"


def _reviews_path(resolved_url: str) -> str:
    path = urlparse(resolved_url).path
    if not path.endswith("/"):
        path += "/"
    return path + "reviews/"


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
        """Вернуть (list[Review], meta)."""
        await self._bootstrap()

        price, characteristics = await self._collect_extras()
        log.info("extras: price=%s характеристик=%d", bool(price), len(characteristics))

        questions = await self._collect_questions()
        log.info("вопросов с ответами: %d", len(questions))

        await self._collect_review_feed()

        reviews, skipped = self._filtered()
        log.info("итог: собрано=%d, пустых пропущено=%d, после фильтров=%d (all_variants=%s)",
                 len(self.reviews_by_uuid), skipped, len(reviews), self.all_variants)
        return reviews, self._meta(price, characteristics, questions)

    # ------------------------------------------------------------------ #
    # Bootstrap и слушатель ответов
    # ------------------------------------------------------------------ #
    async def _bootstrap(self):
        """Открыть карточку, снять заголовки API и курсор полки, определить id товара."""
        def schedule(resp):
            self._pending.append(asyncio.ensure_future(self._on_response(resp)))

        self.page.on("response", schedule)
        try:
            await self.page.goto(self.url, wait_until="domcontentloaded")
            await self.page.wait_for_timeout(2500)
            await self._drain()
            self.resolved_url = self.page.url
            self.product_id = extract_product_id(self.resolved_url)
            for _ in range(_HEADER_SCROLLS):
                if self.headers and self.shelf_next:
                    break
                await self.page.mouse.wheel(0, 3000)
                await self.page.wait_for_timeout(random.uniform(*self.page_delay) * 1000)
                await self._drain()
        finally:
            await self._drain()
            self.page.remove_listener("response", schedule)

        self.origin = _origin(self.resolved_url)
        self.rpath = _reviews_path(self.resolved_url)
        ppath = urlparse(self.resolved_url).path
        if not ppath.endswith("/"):
            ppath += "/"
        self.ppath = ppath
        try:
            self.pid_int = int(self.product_id)
        except (TypeError, ValueError):
            self.pid_int = None

        log.info("bootstrap: id=%s headers=%s shelf_next=%s reviews=%d",
                 self.product_id, bool(self.headers), bool(self.shelf_next), len(self.reviews_by_uuid))
        self.headers = self.headers or {}

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
            if uuid:
                self.reviews_by_uuid[uuid] = r
        return len(self.reviews_by_uuid) - before

    async def _on_response(self, resp):
        """Перехват entrypoint/composer-ответов: снять headers, абсорбировать, поймать shelf_next."""
        try:
            if "json" not in resp.headers.get("content-type", ""):
                return
            if "entrypoint-api" not in resp.url and "composer-api" not in resp.url:
                return
            if "entrypoint-api" in resp.url and self.headers is None:
                hh = await resp.request.all_headers()
                self.headers = {k: v for k, v in hh.items()
                                if k.lower() not in _DROP_HEADERS and not k.startswith(":")}
            data = await resp.json()
        except Exception:
            return
        self._absorb(data)
        np = data.get("nextPage")
        if np and "review" in np.lower() and self.shelf_next is None:
            self.shelf_next = np

    async def _drain(self):
        """Дождаться накопленных обработчиков response."""
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)
            self._pending.clear()

    # ------------------------------------------------------------------ #
    # Сетевой fetch (через контекст страницы)
    # ------------------------------------------------------------------ #
    async def _fetch(self, param: str) -> dict:
        """GET entrypoint-api JSON в контексте страницы. При капче/блоке ждёт решения и повторяет."""
        api = self.origin + _API_PATH + quote(param, safe="")
        waited = False
        for _ in range(_CAPTCHA_WAIT_ITERS):
            try:
                res = await self.page.evaluate(_FETCH_JS, {"u": api, "h": self.headers})
                if isinstance(res, dict) and res.get("status") == 200:
                    return json.loads(res["text"])
            except Exception:
                pass
            if not waited:
                print(">>> Капча/блокировка Ozon. Реши капчу в открытом окне Chrome — "
                      "жду и продолжу сам...")
                log.warning("captcha/block: жду решения пользователя в окне")
                try:
                    await self.page.goto(self.resolved_url, wait_until="domcontentloaded")
                except Exception:
                    pass
                waited = True
            await self.page.wait_for_timeout(4000)
        raise RuntimeError("капча не решена за отведённое время")

    # ------------------------------------------------------------------ #
    # Доп. данные карточки
    # ------------------------------------------------------------------ #
    async def _collect_extras(self):
        """(price, characteristics): карточка (краткие) + /features/ (полные)."""
        price, characteristics = {}, {}
        try:
            pdata = await self._fetch(self.ppath)
            price = parse.parse_price(pdata)
            characteristics = parse.parse_characteristics(pdata)
        except Exception as e:
            log.warning("карточка (цена/характеристики) не получена: %r", e)
        try:
            full = parse.parse_characteristics(await self._fetch(self.ppath + "features/"))
            if len(full) > len(characteristics):
                characteristics = full
        except Exception as e:
            log.warning("features (полные характеристики) не получены: %r", e)
        return price, characteristics

    async def _collect_questions(self, max_pages: int = 12) -> list:
        """Вопросы с ответами (сорт «сначала с ответом»; анонимно ~90 вопросов).

        У вопросов с пометкой «Ещё N ответ» догружаем все ответы со страницы вопроса.
        """
        questions = []
        seen_q = set()
        for page_n in range(1, max_pages + 1):
            try:
                qdata = await self._fetch(f"{self.ppath}questions/?qsort=has_answers_desc&page={page_n}")
            except Exception as e:
                log.warning("вопросы: страница %d не получена: %r", page_n, e)
                break
            new = [q for q in parse.parse_questions(qdata, answered_only=True)
                   if q["text"] not in seen_q]
            if not new:
                break
            for q in new:
                seen_q.add(q["text"])
                if q.get("_has_more") and q.get("_id"):
                    try:
                        full = parse.parse_questions(
                            await self._fetch(f"{self.ppath}question/{q['_id']}/"), answered_only=False)
                        if full and len(full[0]["answers"]) > len(q["answers"]):
                            q["answers"] = full[0]["answers"]
                    except Exception as e:
                        log.warning("вопрос %s: доп.ответы не получены: %r", q.get("_id"), e)
                q.pop("_id", None)
                q.pop("_has_more", None)
                questions.append(q)
        return questions

    # ------------------------------------------------------------------ #
    # Лента отзывов
    # ------------------------------------------------------------------ #
    async def _run_cursor(self, param: str, label: str, date_sorted: bool) -> str:
        """Гонять курсор пагинации. Причина остановки: cutoff|end|limit|error."""
        pages = 0
        empty = 0
        while param and "review" in param.lower() and pages < _MAX_FETCH_PAGES:
            if len(self.reviews_by_uuid) >= self.max_reviews * 3:
                log.info("[%s] stop: лимит набран", label)
                return "limit"
            try:
                data = await self._fetch(param)
            except Exception as e:
                log.warning("[%s] fetch упал: %r", label, e)
                return "error"
            added = self._absorb(data)
            pages += 1
            # тот же расчёт даты, что и в фильтре; нули (нет даты) игнорируем, чтобы не остановиться раньше времени
            stamps = [r.get("publishedAt") or r.get("createdAt") or 0 for r in self.reviews_by_uuid.values()]
            oldest = min((t for t in stamps if t), default=0)
            log.info("[%s] page %d: added=%d total=%d oldest=%s hasNext=%s",
                     label, pages, added, len(self.reviews_by_uuid),
                     parse.ts_to_date(oldest), bool(data.get("nextPage")))
            if date_sorted and oldest and oldest < self.cutoff:
                log.info("[%s] stop: достигнут период", label)
                return "cutoff"
            empty = empty + 1 if added == 0 else 0
            if empty >= _EMPTY_LIMIT:
                log.info("[%s] stop: %d страниц без новых (стена анонима/конец)", label, _EMPTY_LIMIT)
                return "end"
            param = data.get("nextPage")
            await self.page.wait_for_timeout(random.uniform(*config.FETCH_DELAY) * 1000)
        return "end"

    async def _collect_review_feed(self):
        """Основная лента /reviews/, затем фолбэк на полку или добор сортировками по оценке."""
        before_deep = len(self.reviews_by_uuid)
        deep = f"{self.rpath}?sort=published_at_desc&{_VARIANT_MODE}"
        await self._run_cursor(deep, "reviews", date_sorted=True)

        if len(self.reviews_by_uuid) - before_deep <= 3 and self.shelf_next:
            # лента не отдалась — откат на «полку» отзывов карточки
            log.info("лента /reviews/ дала мало — откат на полку карточки")
            await self._run_cursor(self.shelf_next, "shelf", date_sorted=True)
        else:
            # добор сортировками по оценке: каждая отдаёт свой срез (~+50% уникальных в окне),
            # заодно гарантирует негатив и позитив. Анонимно лента ограничена ~990 на сортировку.
            for srt, label in (("score_asc", "low"), ("score_desc", "high")):
                await self._run_cursor(f"{self.rpath}?sort={srt}&{_VARIANT_MODE}", label, date_sorted=False)

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

    def _meta(self, price: dict, characteristics: dict, questions: list) -> dict:
        """Сводка meta для runner."""
        return {
            "product_id": self.product_id,
            "resolved_url": self.resolved_url,
            "name": (self.products.get(str(self.product_id)) or {}).get("name", ""),
            "variant": parse.variant_map(self.product_id, self.products),
            "price": price,
            "characteristics": characteristics,
            "questions": questions,
            "score": self.score,
            "total": self.total,
        }
