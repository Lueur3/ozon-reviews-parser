r"""Recon: разовый сбор реальной структуры Ozon, чтобы написать точный парсер.

ВАЖНО: запускать с ВЫКЛЮЧЕННЫМ VPN, иначе Ozon заблокирует.

Запуск из корня проекта:
    .\.venv\Scripts\python.exe scripts/recon.py "<ссылка на товар>"
    .\.venv\Scripts\python.exe scripts/recon.py "<ссылка>" --headless   # без окна

Сохраняет в папку captures/:
    resolved_url.txt   — итоговая ссылка и id товара
    all_requests.txt   — ВСЕ сетевые запросы (статус, тип, url)
    review_*.json      — пойманные JSON-ответы с отзывами
    product.html / reviews.html — HTML страниц
    product.png  / reviews.png  — скриншоты
Подробный лог: logs/recon.log (читается в UTF-8, даже если консоль коверкает кириллицу).
"""
import asyncio
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ozon.browser import launch_browser
from ozon.urls import extract_product_id

CAP = ROOT / "captures"
LOGS = ROOT / "logs"
REVIEW_HINTS = ("review", "comment", "otzyv", "feedback")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def setup_logging():
    LOGS.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOGS / "recon.log", encoding="utf-8"),
        ],
    )
    return logging.getLogger("recon")


log = setup_logging()


def reviews_url_from(resolved: str) -> str:
    pr = urlparse(resolved)
    path = pr.path.rstrip("/") + "/reviews/"
    return urlunparse((pr.scheme, pr.netloc, path, "", "", ""))


async def run(url: str, headless: bool):
    CAP.mkdir(exist_ok=True)
    captured = []          # (status, content-type, url)
    pending = []
    counter = {"n": 0}

    async def on_response(resp):
        try:
            ct = resp.headers.get("content-type", "")
            captured.append((resp.status, ct, resp.url))
            low = resp.url.lower()
            if "json" in ct and any(h in low for h in REVIEW_HINTS):
                try:
                    body = await resp.text()
                except Exception as e:
                    log.warning("  не смог прочитать тело %s: %s", resp.url, e)
                    return
                counter["n"] += 1
                (CAP / f"review_{counter['n']:02d}.json").write_text(body, encoding="utf-8")
                log.info("  OK: сохранён отзывный JSON #%d (%d байт): %s",
                         counter["n"], len(body), resp.url)
        except Exception as e:
            log.debug("  ошибка обработчика ответа: %s", e)

    log.info("Запуск. Видимое окно: %s", not headless)
    log.info("Если увидишь страницу 'Выключите VPN' — выключи VPN и запусти снова.")

    async with launch_browser(headless=headless) as (context, page):
        context.on("response", lambda r: pending.append(asyncio.ensure_future(on_response(r))))

        log.info("1) Открываю ссылку: %s", url)
        try:
            resp = await page.goto(url, wait_until="domcontentloaded")
        except Exception as e:
            log.error("Не удалось открыть страницу: %s", e)
            return

        await page.wait_for_timeout(4000)
        resolved = page.url
        status = resp.status if resp else None
        title = await page.title()
        pid = extract_product_id(resolved)
        log.info("   Статус: %s | Заголовок: %s", status, title)
        log.info("   Итоговый URL: %s", resolved)
        log.info("   ID товара: %s", pid)

        (CAP / "resolved_url.txt").write_text(
            f"{resolved}\nid={pid}\nstatus={status}\ntitle={title}\n", encoding="utf-8")
        (CAP / "product.html").write_text(await page.content(), encoding="utf-8")
        await page.screenshot(path=str(CAP / "product.png"))

        body_low = (await page.content()).lower()
        if status == 403 or "выключите vpn" in body_low or "нет соединения" in body_low:
            log.error("!!! БЛОКИРОВКА Ozon (скорее всего включён VPN). Выключи VPN и запусти снова.")
            log.error("    Скриншот: captures/product.png")

        log.info("1b) Листаю карточку вниз, чтобы подгрузился блок отзывов...")
        for _ in range(6):
            await page.mouse.wheel(0, 2500)
            await page.wait_for_timeout(1200)

        rurl = reviews_url_from(resolved)
        log.info("2) Открываю страницу отзывов: %s", rurl)
        try:
            await page.goto(rurl, wait_until="domcontentloaded")
            await page.wait_for_timeout(4000)
        except Exception as e:
            log.warning("   Не удалось открыть отзывы напрямую: %s", e)

        log.info("3) Листаю вниз, чтобы подгрузить отзывы (8 прокруток)...")
        for _ in range(8):
            await page.mouse.wheel(0, 3000)
            await page.wait_for_timeout(1500)

        (CAP / "reviews.html").write_text(await page.content(), encoding="utf-8")
        await page.screenshot(path=str(CAP / "reviews.png"))

        await asyncio.gather(*pending, return_exceptions=True)

    (CAP / "all_requests.txt").write_text(
        "\n".join(f"{s}\t{ct}\t{u}" for (s, ct, u) in captured), encoding="utf-8")

    log.info("ГОТОВО. Сетевых ответов: %d | отзывных JSON сохранено: %d", len(captured), counter["n"])
    log.info("Смотри папку captures/ и logs/recon.log")
    if counter["n"] == 0:
        log.warning("Отзывных JSON не поймано — пришли captures/all_requests.txt и reviews.html, "
                    "найду нужный эндпоинт по ним.")


if __name__ == "__main__":
    args = sys.argv[1:]
    headless = "--headless" in args
    args = [a for a in args if a != "--headless"]
    if not args:
        log.error("Укажи ссылку. Пример: python scripts/recon.py \"https://ozon.ru/t/nPDyAby\"")
        sys.exit(1)
    asyncio.run(run(args[0], headless))
