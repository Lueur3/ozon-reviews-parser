r"""Аудит глубины: сколько отзывов на товаре реально удаётся собрать.

ВАЖНО: запускать с ВЫКЛЮЧЕННЫМ VPN.

Запуск из корня проекта:
    .\.venv\Scripts\python.exe scripts/audit.py "<ссылка на товар>"
    .\.venv\Scripts\python.exe scripts/audit.py "<ссылка>" --all-sorts

Без ограничения по дате и количеству листает ленту /reviews/ до конца (пока есть
nextPage), считает: всего уникальных, пустых, непустых; показывает диапазон дат и
причину остановки по каждой сортировке. Полные тексты НЕ сохраняются — только
короткие заголовки (дата | оценка | пустой | вариант) в captures/audit_headers.txt.
"""
import argparse
import asyncio
import logging
import random
import sys

from _common import CAPTURES, LOGS, api, open_session, utf8_stdout

from ozon import parse

EMPTY_LIMIT = 5
PAGE_CAP = 1500

utf8_stdout()
LOGS.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOGS / "audit.log", encoding="utf-8")])
log = logging.getLogger("audit")


def is_empty(raw: dict) -> bool:
    c = raw.get("content") or {}
    return not ((c.get("comment") or "").strip()
                or (c.get("positive") or "").strip()
                or (c.get("negative") or "").strip())


async def audit(url: str, sorts: list[str]):
    seen = {}                      # uuid -> (date, score, empty, itemId)
    claimed = {"total": None}

    def absorb(data: dict) -> int:
        res = parse.extract_reviews_widget(data)
        if not res:
            return 0
        reviews, _prods, _sc, tot = res
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

    report = []
    log.info("Открываю: %s", url)
    async with open_session(url, on_data=absorb) as s:
        log.info("id=%s | заголовки API: %s", s.product_id,
                 "есть" if s.client.headers else "НЕТ")

        for srt in sorts:
            param = api.reviews_feed(s.rpath, srt)
            pages = 0
            empty_streak = 0
            before = len(seen)
            stop = "no_next"
            while param and "review" in param.lower() and pages < PAGE_CAP:
                try:
                    data = await s.fetch(param)
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
                    break
                param = nxt
                await s.page.wait_for_timeout(random.uniform(0.3, 0.7) * 1000)
            else:
                if pages >= PAGE_CAP:
                    stop = "page_cap"
            line = (f"[{srt}] страниц={pages} +уникальных={len(seen) - before} "
                    f"стоп={stop} (всего уникальных={len(seen)})")
            log.info(line)
            report.append(line)
        resolved, pid = s.resolved_url, s.product_id

    empties = sum(1 for v in seen.values() if v[2])
    dates = sorted(v[0] for v in seen.values())
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
        f"  непустых: {len(seen) - empties}",
        f"общий диапазон дат: {f'{dates[0]} .. {dates[-1]}' if dates else '—'}",
    ]
    if claimed["total"]:
        share = 100 * len(seen) / claimed["total"]
        if len(seen) >= claimed["total"] * 0.95:
            summary.append(f"ВЫВОД: собрано практически всё ({share:.0f}% заявленного).")
        else:
            summary.append(f"ВЫВОД: собрано {len(seen)} из ~{claimed['total']} ({share:.0f}%) — "
                           f"дальше сбор не идёт, причина по каждой сортировке выше.")

    CAPTURES.mkdir(exist_ok=True)
    (CAPTURES / "audit_summary.txt").write_text("\n".join(summary), encoding="utf-8")
    rows = sorted(((v[0], v[1], "пусто" if v[2] else "текст", v[3]) for v in seen.values()),
                  reverse=True)
    (CAPTURES / "audit_headers.txt").write_text(
        "date | score | empty | itemId\n" +
        "\n".join(f"{d} | {s} | {e} | {it}" for d, s, e, it in rows), encoding="utf-8")

    print("\n".join(summary))
    log.info("Сводка: captures/audit_summary.txt | заголовки: captures/audit_headers.txt")


def main():
    p = argparse.ArgumentParser(description="Аудит глубины ленты отзывов Ozon.")
    p.add_argument("url", help="ссылка на товар")
    p.add_argument("--all-sorts", action="store_true",
                   help="добрать сортировками по оценке (score_asc/score_desc)")
    args = p.parse_args()
    sorts = [api.SORT_NEWEST]
    if args.all_sorts:
        sorts += [api.SORT_SCORE_ASC, api.SORT_SCORE_DESC]
    asyncio.run(audit(args.url, sorts))


if __name__ == "__main__":
    main()
