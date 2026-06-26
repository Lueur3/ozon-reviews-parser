r"""Recon пагинации вопросов-ответов (Q&A).

ВАЖНО: VPN выключен.

    .\.venv\Scripts\python.exe scripts/recon_qa.py "https://ozon.ru/t/nPDyAby"

Открывает /questions/?qsort=has_answers_desc, листает вниз и ловит запросы
подгрузки вопросов. Сохраняет captures/qa/*.json (ответы с webListQuestions)
и captures/qa/_index.txt: статус, число вопросов, есть ли nextPage, URL.
По индексу поймём, как именно листается лента вопросов.
"""
import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ozon.browser import launch_browser

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

QA = ROOT / "captures" / "qa"


def widget_states(data):
    out = {}
    for k, v in (data.get("widgetStates") or {}).items():
        if isinstance(v, str):
            try:
                out[k] = json.loads(v)
            except Exception:
                pass
        elif isinstance(v, dict):
            out[k] = v
    return out


def qcount(data):
    for k, w in widget_states(data).items():
        if k.startswith("webListQuestions"):
            qs = w.get("questions")
            return len(qs) if isinstance(qs, (list, dict)) else 0
    return None


async def main(url):
    QA.mkdir(parents=True, exist_ok=True)
    records = []
    pending = []
    counter = {"i": 0}

    async def on_resp(resp):
        try:
            u = resp.url
            if "webListQuestions" not in u and "question" not in u.lower() \
                    and "getanswer" not in u.lower():
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
        pr = urlparse(page.url)
        ppath = pr.path if pr.path.endswith("/") else pr.path + "/"
        qurl = f"{pr.scheme}://{pr.netloc}{ppath}questions/?qsort=has_answers_desc"
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
    if len(sys.argv) < 2:
        print('нужна ссылка: python scripts/recon_qa.py "https://ozon.ru/t/nPDyAby"')
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
