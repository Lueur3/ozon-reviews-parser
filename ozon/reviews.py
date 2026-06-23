"""Сбор отзывов через внутренний API Ozon (entrypoint-api page json v2).

Заголовки запроса берём из живой сессии браузера (он прошёл анти-бот),
дальше пагинацию ленты отзывов гоняем через fetch в контексте страницы.

Анонимному пользователю Ozon отдаёт ограниченный объём ленты («Войдите,
чтобы посмотреть больше»). Если хронологическая лента упирается в эту стену
раньше, чем покрывает заданный период, добираем отзывы сортировками по оценке
(низкая/высокая) — так в окно попадает больше негатива и позитива.
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

_FETCH_JS = """async ({u, h}) => {
    const r = await fetch(u, {headers: h, credentials: 'include'});
    return await r.text();
}"""

_LOGDIR = config.BASE_DIR / "logs"
_LOGDIR.mkdir(exist_ok=True)
log = logging.getLogger("ozon.reviews")
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


async def collect_reviews(page, url, period_days, all_variants, max_reviews, page_delay):
    """Возвращает (list[Review], meta). meta: product_id, resolved_url, name, variant, score, total."""
    cutoff = parse.cutoff_ts(period_days)

    raw_by_uuid = {}
    products = {}
    state = {"score": None, "total": None, "next": None, "headers": None}
    pending = []

    def absorb(data: dict) -> int:
        res = parse.extract_reviews_widget(data)
        if not res:
            return 0
        reviews, prods, sc, tot = res
        if prods:
            products.update(prods)
        if sc is not None:
            state["score"] = sc
        if tot is not None:
            state["total"] = tot
        before = len(raw_by_uuid)
        for r in reviews:
            uuid = r.get("uuid")
            if uuid:
                raw_by_uuid[uuid] = r
        return len(raw_by_uuid) - before

    async def on_response(resp):
        try:
            if "json" not in resp.headers.get("content-type", ""):
                return
            if "entrypoint-api" not in resp.url and "composer-api" not in resp.url:
                return
            if "entrypoint-api" in resp.url and state["headers"] is None:
                hh = await resp.request.all_headers()
                state["headers"] = {k: v for k, v in hh.items()
                                    if k.lower() not in _DROP_HEADERS and not k.startswith(":")}
            data = await resp.json()
        except Exception:
            return
        absorb(data)
        np = data.get("nextPage")
        if np and "review" in np.lower() and state["next"] is None:
            state["next"] = np

    def schedule(resp):
        pending.append(asyncio.ensure_future(on_response(resp)))

    async def drain():
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            pending.clear()

    page.on("response", schedule)
    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)
        await drain()
        resolved_url = page.url
        product_id = extract_product_id(resolved_url)
        for _ in range(_HEADER_SCROLLS):
            if state["headers"] and state["next"]:
                break
            await page.mouse.wheel(0, 3000)
            await page.wait_for_timeout(random.uniform(*page_delay) * 1000)
            await drain()
    finally:
        await drain()
        page.remove_listener("response", schedule)

    origin = _origin(resolved_url)
    headers = state["headers"] or {}
    rpath = _reviews_path(resolved_url)
    try:
        pid_int = int(product_id)
    except (TypeError, ValueError):
        pid_int = None

    log.info("bootstrap: id=%s headers=%s shelf_next=%s reviews=%d",
             product_id, bool(state["headers"]), bool(state["next"]), len(raw_by_uuid))

    async def run_cursor(param, label, date_sorted) -> str:
        """Гоняет курсор пагинации. Возвращает причину остановки: cutoff|end|limit|error."""
        pages = 0
        empty = 0
        while param and "review" in param.lower() and pages < _MAX_FETCH_PAGES:
            if len(raw_by_uuid) >= max_reviews * 3:
                log.info("[%s] stop: лимит набран", label)
                return "limit"
            api = origin + _API_PATH + quote(param, safe="")
            try:
                text = await page.evaluate(_FETCH_JS, {"u": api, "h": headers})
            except Exception as e:
                log.warning("[%s] evaluate/fetch упал: %r", label, e)
                return "error"
            try:
                data = json.loads(text)
            except Exception as e:
                log.warning("[%s] json не разобрался (len=%d head=%r): %r",
                            label, len(text), text[:160], e)
                return "error"
            added = absorb(data)
            pages += 1
            oldest = min((r.get("publishedAt") or 0) for r in raw_by_uuid.values()) if raw_by_uuid else 0
            log.info("[%s] page %d: textlen=%d added=%d total=%d oldest=%s hasNext=%s",
                     label, pages, len(text), added, len(raw_by_uuid),
                     parse.ts_to_date(oldest), bool(data.get("nextPage")))
            if date_sorted and oldest and oldest < cutoff:
                log.info("[%s] stop: достигнут период", label)
                return "cutoff"
            empty = empty + 1 if added == 0 else 0
            if empty >= _EMPTY_LIMIT:
                log.info("[%s] stop: %d страниц без новых (стена анонима/конец)", label, _EMPTY_LIMIT)
                return "end"
            param = data.get("nextPage")
            await page.wait_for_timeout(random.uniform(*config.FETCH_DELAY) * 1000)
        return "end"

    # основной путь: хронологическая лента /reviews/
    before_deep = len(raw_by_uuid)
    deep = f"{rpath}?sort=published_at_desc&{_VARIANT_MODE}"
    status = await run_cursor(deep, "reviews", date_sorted=True)

    if len(raw_by_uuid) - before_deep <= 3 and state["next"]:
        # лента не отдалась — откат на «полку» отзывов карточки
        log.info("лента /reviews/ дала мало — откат на полку карточки")
        await run_cursor(state["next"], "shelf", date_sorted=True)
    elif status != "cutoff":
        # лента упёрлась в стену анонима раньше, чем покрыла год — добираем сортировками
        log.info("лента не покрыла период — добираю сортировками по оценке")
        for srt, label in (("score_asc", "low"), ("score_desc", "high")):
            await run_cursor(f"{rpath}?sort={srt}&{_VARIANT_MODE}", label, date_sorted=False)

    # фильтрация: период, вариант, пустые отзывы (дедуп уже по uuid)
    out = []
    skipped_empty = 0
    for raw in raw_by_uuid.values():
        ts = raw.get("publishedAt") or raw.get("createdAt") or 0
        if ts < cutoff:
            continue
        if not all_variants and pid_int is not None and raw.get("itemId") != pid_int:
            continue
        rev = parse.to_review(raw, products)
        if _is_empty(rev):
            skipped_empty += 1
            continue
        out.append(rev)
    out.sort(key=lambda r: r.date, reverse=True)
    out = out[:max_reviews]
    log.info("итог: собрано=%d, пустых пропущено=%d, после фильтров=%d (all_variants=%s)",
             len(raw_by_uuid), skipped_empty, len(out), all_variants)

    meta = {
        "product_id": product_id,
        "resolved_url": resolved_url,
        "name": (products.get(str(product_id)) or {}).get("name", ""),
        "variant": parse.variant_map(product_id, products),
        "score": state["score"],
        "total": state["total"],
    }
    return out, meta
