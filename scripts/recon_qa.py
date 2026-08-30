r"""Recon пагинации вопросов-ответов (Q&A).

ВАЖНО: VPN выключен.

    .\.venv\Scripts\python.exe scripts/recon_qa.py "<ссылка на товар>"

Открывает /questions/?qsort=has_answers_desc, листает вниз и ловит запросы
подгрузки вопросов. Сохраняет captures/qa/*.json (ответы с виджетом вопросов)
и captures/qa/_index.txt: статус, число вопросов, есть ли nextPage, URL.
По индексу поймём, как именно листается лента вопросов.
"""
import argparse
import asyncio
import json
import re
from urllib.parse import urlparse

from _common import CAPTURES, api, launch_browser, normalize, utf8_stdout

from ozon import parse

utf8_stdout()
QA = CAPTURES / "qa"


def qcount(data):
    """Сколько вопросов в ответе. Виджет ищем тем же кодом, что и в проде, —
    иначе скрипт устаревает при первом же изменении на стороне сайта."""
    w = parse.question_widget(data)
    if w is None:
        return None
    qs = w.get("questions")
    return len(qs) if isinstance(qs, (list, dict)) else 0


async def main(url):
    url = normalize(url)        # принимаем ссылку или артикул, как основной CLI
    QA.mkdir(parents=True, exist_ok=True)
    records = []
    pending = []
    counter = {"i": 0}

    async def on_resp(resp):
        try:
            u = resp.url
            if "question" not in u.lower() and "getanswer" not in u.lower():
                return
            if "json" not in resp.headers.get("content-type", ""):
                return
            data = await resp.json()
        except Exception:
            return
        req = resp.request
        try:
            body = req.post_data
        except Exception:
            body = None
        counter["i"] += 1
        (QA / f"{counter['i']:02d}.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")
        records.append(f"{resp.status} | {req.method} | {u}\n    BODY: {body}")

    def schedule(r):
        pending.append(asyncio.ensure_future(on_resp(r)))

    async def drain():
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            pending.clear()

    async with launch_browser(headless=False) as (ctx, page):
        page.on("response", schedule)
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        await drain()
        ppath = api.product_path(page.url)
        qurl = api.origin_of(page.url) + f"{ppath}questions/?qsort={api.QUESTIONS_SORT}"
        print("Открываю вопросы:", qurl)
        await page.goto(qurl, wait_until="domcontentloaded")
        await page.wait_for_timeout(3500)
        await drain()
        print("Кликаю 'Показать больше'...")
        for i in range(40):
            btn = page.get_by_text(re.compile(r"оказать больше", re.I)).first
            try:
                await btn.scroll_into_view_if_needed(timeout=4000)
                await btn.click(timeout=4000)
            except Exception as e:
                print(f"стоп на клике #{i}: {e!r}")
                break
            await page.wait_for_timeout(1800)
            await drain()
        await drain()
        page.remove_listener("response", schedule)

    (QA / "_index.txt").write_text("\n".join(records), encoding="utf-8")
    print(f"Поймано ответов с вопросами: {len(records)}. См. captures/qa/_index.txt")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Recon пагинации вопросов-ответов (Q&A).")
    p.add_argument("url", help="ссылка на товар")
    asyncio.run(main(p.parse_args().url))
