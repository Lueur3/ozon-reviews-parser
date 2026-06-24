r"""Аудит глубины: сколько отзывов реально отдаёт fetch-курсор (есть ли «стена анонима»).

ВАЖНО: запускать с ВЫКЛЮЧЕННЫМ VPN.

Запуск из корня проекта:
    .\.venv\Scripts\python.exe scripts/audit.py "<ссылка на товар>"
    .\.venv\Scripts\python.exe scripts/audit.py "<ссылка>" --all-sorts

Без ограничения по дате и количеству листает ленту /reviews/ до конца (пока есть
nextPage), считает: всего уникальных, пустых, непустых; показывает диапазон дат и
причину остановки по каждой сортировке. Полные тексты НЕ сохраняются — только
короткие заголовки (дата | оценка | пустой | вариант) в captures/audit_headers.txt.
"""
import asyncio
import json
import logging
import random
import sys
from pathlib import Path
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config
from ozon import parse
from ozon.browser import launch_browser
from ozon.urls import extract_product_id

API = "/api/entrypoint-api.bx/page/json/v2?url="
VARIANT_MODE = "reviewsVariantMode=2"
DROP_HEADERS = {"host", "cookie", "content-length", "accept-encoding", "connection",
                "user-agent", "origin", "referer"}
FETCH_JS = """async ({u, h}) => {
    const r = await fetch(u, {headers: h, credentials: 'include'});
    return await r.text();
}"""
EMPTY_LIMIT = 5
PAGE_CAP = 1500

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CAP = ROOT / "captures"
LOGS = ROOT / "logs"
LOGS.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOGS / "audit.log", encoding="utf-8")])
log = logging.getLogger("audit")


def reviews_path(resolved_url: str) -> str:
    path = urlparse(resolved_url).path
    if not path.endswith("/"):
        path += "/"
    return path + "reviews/"


def is_empty(raw: dict) -> bool:
    c = raw.get("content") or {}
    return not ((c.get("comment") or "").strip()
                or (c.get("positive") or "").strip()
                or (c.get("negative") or "").strip())


async def audit(url: str, sorts: list[str]):
    seen = {}          # uuid -> (date, score, empty, itemId)
    claimed = {"total": None}
    state = {"headers": None}
    pending = []

    def absorb(data: dict) -> int:
        res = parse.extract_reviews_widget(data)
        if not res:
            return 0
        reviews, prods, sc, tot = res
        if tot is not None:
            claimed["total"] = tot
        before = len(seen)
        for r in reviews:
            u = r.get("uuid")
            if not u:
                continue
            seen[u] = (parse.ts_to_date(r.get("publishedAt") or r.get("createdAt")),
                       (r.get("content") or {}).get("score"), is_empty(r), r.get("itemId"))
        return len(seen) - before

    async def on_response(resp):
        try:
            if "json" not in resp.headers.get("content-type", ""):
                return
            if "entrypoint-api" not in resp.url and "composer-api" not in resp.url:
                return
            if "entrypoint-api" in resp.url and state["headers"] is None:
                hh = await resp.request.all_headers()
                state["headers"] = {k: v for k, v in hh.items()
                                    if k.lower() not in DROP_HEADERS and not k.startswith(":")}
            data = await resp.json()
        except Exception:
            return
        absorb(data)

    def schedule(resp):
        pending.append(asyncio.ensure_future(on_response(resp)))

    async def drain():
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            pending.clear()

    report = []
    async with launch_browser(headless=False) as (context, page):
        page.on("response", schedule)
        log.info("Открываю: %s", url)
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)
        await drain()
        resolved = page.url
        pid = extract_product_id(resolved)
        for _ in range(8):
            if state["headers"]:
                break
            await page.mouse.wheel(0, 3000)
            await page.wait_for_timeout(1200)
            await drain()
        page.remove_listener("response", schedule)

        origin = f"{urlparse(resolved).scheme}://{urlparse(resolved).netloc}"
        rpath = reviews_path(resolved)
        headers = state["headers"] or {}
        log.info("id=%s | заголовки API: %s", pid, "есть" if headers else "НЕТ")

        for srt in sorts:
            param = f"{rpath}?sort={srt}&{VARIANT_MODE}"
            pages = 0
            empty_streak = 0
            before = len(seen)
            stop = "no_next"
            while param and "review" in param.lower() and pages < PAGE_CAP:
                api = origin + API + quote(param, safe="")
                try:
                    text = await page.evaluate(FETCH_JS, {"u": api, "h": headers})
                    data = json.loads(text)
                except Exception as e:
                    stop = f"error:{e!r}"
                    break
                added = absorb(data)
                pages += 1
                empty_streak = empty_streak + 1 if added == 0 else 0
                if pages % 25 == 0:
                    log.info("[%s] страниц=%d уникальных=%d", srt, pages, len(seen))
                if empty_streak >= EMPTY_LIMIT:
                    stop = "empty_wall"
                    break
                nxt = data.get("nextPage")
                if not (nxt and "review" in nxt.lower()):
                    stop = "no_next"
                    param = None
                    break
                param = nxt
                await page.wait_for_timeout(random.uniform(0.3, 0.7))
            else:
                if pages >= PAGE_CAP:
                    stop = "page_cap"
            contributed = len(seen) - before
            line = (f"[{srt}] страниц={pages} +уникальных={contributed} "
                    f"стоп={stop} (всего уникальных={len(seen)})")
            log.info(line)
            report.append(line)

    # сводка
    empties = sum(1 for v in seen.values() if v[2])
    nonempty = len(seen) - empties
    dates = sorted(v[0] for v in seen.values())
    drange = f"{dates[0]} .. {dates[-1]}" if dates else "—"

    summary = [
        "=== АУДИТ ГЛУБИНЫ ОТЗЫВОВ ===",
        f"товар: {pid}",
        f"url: {resolved}",
        f"заявлено Ozon (paging.total, все варианты): {claimed['total']}",
        "",
        *report,
        "",
        f"ИТОГО уникальных собрано: {len(seen)}",
        f"  пустых (без текста): {empties}",
        f"  непустых: {nonempty}",
        f"общий диапазон дат: {drange}",
    ]
    if claimed["total"]:
        got = len(seen)
        if got >= claimed["total"] * 0.95:
            summary.append("ВЫВОД: fetch достал практически ВСЁ — стены для fetch фактически нет.")
        else:
            summary.append(f"ВЫВОД: fetch достал {got} из ~{claimed['total']} — дальше упор "
                           f"(стоп см. по сортировкам). Это и есть предел для анонима.")

    (CAP).mkdir(exist_ok=True)
    (CAP / "audit_summary.txt").write_text("\n".join(summary), encoding="utf-8")
    rows = sorted(((v[0], v[1], "пусто" if v[2] else "текст", v[3]) for v in seen.values()),
                  reverse=True)
    (CAP / "audit_headers.txt").write_text(
        "date | score | empty | itemId\n" +
        "\n".join(f"{d} | {s} | {e} | {it}" for d, s, e, it in rows), encoding="utf-8")

    print("\n".join(summary))
    log.info("Сводка: captures/audit_summary.txt | заголовки: captures/audit_headers.txt")


if __name__ == "__main__":
    args = sys.argv[1:]
    all_sorts = "--all-sorts" in args
    args = [a for a in args if a != "--all-sorts"]
    if not args:
        print("Укажи ссылку. Пример: python scripts/audit.py \"https://ozon.ru/t/nPDyAby\" --all-sorts")
        sys.exit(1)
    sorts = ["published_at_desc"]
    if all_sorts:
        sorts += ["score_asc", "score_desc"]
    asyncio.run(audit(args[0], sorts))
