"""Общая обвязка диагностических скриптов.

Каждый скрипт раньше повторял одно и то же: правку sys.path, запуск браузера,
слушатель ответов для снятия заголовков API, свой JS-сниппет fetch и свой список
отбрасываемых заголовков. Теперь это здесь, а знание об адресах Ozon — в ozon.api.
"""
import asyncio
import contextlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ozon import api                     # noqa: E402  (после правки sys.path)
from ozon.browser import launch_browser   # noqa: E402
from ozon.urls import extract_product_id  # noqa: E402

CAPTURES = ROOT / "captures"
LOGS = ROOT / "logs"


def utf8_stdout() -> None:
    """Консоль Windows по умолчанию cp1251 — иначе кириллица в выводе ломается."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class Session:
    """Открытая карточка товара + готовый OzonClient для запросов к внутреннему API."""

    def __init__(self, page, client, resolved_url, product_id):
        self.page = page
        self.client = client
        self.resolved_url = resolved_url
        self.product_id = product_id

    @property
    def ppath(self) -> str:
        return api.product_path(self.resolved_url)

    @property
    def rpath(self) -> str:
        return api.reviews_path(self.resolved_url)

    async def fetch(self, param: str) -> dict:
        return await self.client.fetch(param)


@contextlib.asynccontextmanager
async def open_session(url: str, scrolls: int = 8, on_data=None, headless: bool = False):
    """Открывает товар, снимает заголовки живой сессии и отдаёт Session.

    on_data — необязательный колбэк(dict) на каждый перехваченный JSON-ответ
    (скрипты используют его, чтобы собирать сырые ответы).
    """
    state = {"headers": None}
    pending = []

    async def on_response(resp):
        try:
            if "json" not in resp.headers.get("content-type", ""):
                return
            if "entrypoint-api" not in resp.url and "composer-api" not in resp.url:
                return
            if "entrypoint-api" in resp.url and state["headers"] is None:
                state["headers"] = api.session_headers(await resp.request.all_headers())
            data = await resp.json()
        except Exception:
            return
        if on_data:
            on_data(data)

    def schedule(resp):
        pending.append(asyncio.ensure_future(on_response(resp)))

    async def drain():
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            pending.clear()

    async with launch_browser(headless=headless) as (_context, page):
        page.on("response", schedule)
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(2500)
            await drain()
            for _ in range(scrolls):
                if state["headers"]:
                    break
                await page.mouse.wheel(0, 3000)
                await page.wait_for_timeout(1200)
                await drain()
        finally:
            await drain()
            page.remove_listener("response", schedule)

        resolved = page.url
        client = api.OzonClient(page, api.origin_of(resolved), state["headers"] or {},
                                recovery_url=resolved)
        yield Session(page, client, resolved, extract_product_id(resolved))
