r"""Recon для цены, характеристик и вопросов/ответов.

ВАЖНО: запускать с ВЫКЛЮЧЕННЫМ VPN.

    .\.venv\Scripts\python.exe scripts/recon_extra.py "https://ozon.ru/t/nPDyAby"

Берёт заголовки API из живой сессии и через fetch тянет JSON карточки и
раздела вопросов. Сохраняет сырьё в captures/extra/ и карту виджетов
(layout-компоненты + ключи widgetStates) в captures/extra/_widgets.txt —
по ней найдём, где цена, характеристики и Q&A.
"""
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ozon.browser import launch_browser
from ozon.urls import extract_product_id

API = "/api/entrypoint-api.bx/page/json/v2?url="
DROP = {"host", "cookie", "content-length", "accept-encoding", "connection",
        "user-agent", "origin", "referer"}
FETCH_JS = """async ({u, h}) => {
    const r = await fetch(u, {headers: h, credentials: 'include'});
    return await r.text();
}"""

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

EXTRA = ROOT / "captures" / "extra"


def widget_map(data: dict) -> list[str]:
    out = []
    layout = data.get("layout")
    if isinstance(layout, list):
        for w in layout:
            out.append(f"  layout: {w.get('component')}  stateId={w.get('stateId')}")
    ws = data.get("widgetStates")
    if isinstance(ws, dict):
        for k in ws:
            out.append(f"  state : {k}")
    return out


async def main(url: str):
    EXTRA.mkdir(parents=True, exist_ok=True)
    state = {"headers": None}
    pending = []

    async def on_response(resp):
        try:
            if "entrypoint-api" in resp.url and state["headers"] is None:
                if "json" in resp.headers.get("content-type", ""):
                    hh = await resp.request.all_headers()
                    state["headers"] = {k: v for k, v in hh.items()
                                        if k.lower() not in DROP and not k.startswith(":")}
        except Exception:
            pass

    def schedule(resp):
        pending.append(asyncio.ensure_future(on_response(resp)))

    report = []
    async with launch_browser(headless=False) as (context, page):
        page.on("response", schedule)
        print("Открываю:", url)
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3500)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        resolved = page.url
        pid = extract_product_id(resolved)
        ppath = urlparse(resolved).path
        if not ppath.endswith("/"):
            ppath += "/"
        origin = f"{urlparse(resolved).scheme}://{urlparse(resolved).netloc}"
        headers = state["headers"] or {}
        print(f"id={pid} | заголовки API: {'есть' if headers else 'НЕТ'}")

        async def fetch_dump(param, label):
            api = origin + API + quote(param, safe="")
            try:
                text = await page.evaluate(FETCH_JS, {"u": api, "h": headers})
                data = json.loads(text)
            except Exception as e:
                print(f"[{label}] ошибка: {e!r}")
                report.append(f"### {label}  ({param})\n  ОШИБКА: {e!r}")
                return None
            (EXTRA / f"{label}.json").write_text(text, encoding="utf-8")
            keys = widget_map(data)
            report.append(f"### {label}  ({param})  [{len(text)} байт]\n" + "\n".join(keys))
            print(f"[{label}] сохранено ({len(text)} байт), виджетов: {len(keys)}")
            return data

        # карточка (цена/артикул/краткие характеристики), полные характеристики, вопросы
        await fetch_dump(ppath, "product")
        await fetch_dump(ppath + "features/", "features")
        await fetch_dump(ppath + "questions/", "questions")

        page.remove_listener("response", schedule)

    (EXTRA / "_widgets.txt").write_text("\n\n".join(report), encoding="utf-8")
    print("\nКарта виджетов: captures/extra/_widgets.txt")
    print("Сырьё: captures/extra/*.json")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print('Укажи ссылку: python scripts/recon_extra.py "https://ozon.ru/t/nPDyAby"')
        sys.exit(1)
    asyncio.run(main(args[0]))
