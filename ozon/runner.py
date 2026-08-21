"""Оркестрация: браузер -> сбор отзывов -> сохранение JSON."""
import asyncio
import time

from . import config
from .browser import launch_browser
from .collector import ReviewCollector
from .logging_setup import get_logger
from .models import Product
from .storage import save_product

log = get_logger("ozon.runner")


def _report(msg: str) -> None:
    """Печатает пользователю и дублирует в лог — чтобы картина в файле была полной."""
    print(msg)
    log.info(msg.strip())


async def _run_async(urls, period_days, all_variants, headless, max_reviews,
                     output_dir=None, profile_dir=None, fresh_profile=False):
    output_dir = output_dir or config.OUTPUT_DIR
    started = time.perf_counter()
    async with launch_browser(headless=headless, fresh_profile=fresh_profile,
                              profile_dir=profile_dir or config.PROFILE_DIR) as (context, page):
        for i, url in enumerate(urls):
            mode = "все варианты" if all_variants else "только этот вариант"
            _report(f"[{i + 1}/{len(urls)}] {url} ({mode}) — собираю отзывы...")
            t0 = time.perf_counter()
            try:
                collector = ReviewCollector(
                    page, url, period_days=period_days, all_variants=all_variants,
                    max_reviews=max_reviews, page_delay=config.PAGE_DELAY)
                reviews, meta = await collector.collect()
            except Exception as e:
                _report(f"    ошибка сбора: {e}")
                log.exception("сбор %s не удался", url)
                continue
            elapsed = time.perf_counter() - t0

            pid = meta.get("product_id")
            if not pid:
                _report(f"    не удалось определить id товара (итоговый URL: {meta.get('resolved_url')})")
                continue

            # Раньше пустое имя подменялось page.title() — это давало в JSON мусор
            # вроде «Ozon». Лучше честно сказать, что имя не пришло.
            name = meta.get("name") or ""
            if not name:
                _report("    предупреждение: название товара не получено (webListReviews.products)")

            product = Product(
                url=meta.get("resolved_url") or url,
                product_id=pid,
                name=name,
                variant=meta.get("variant", {}),
                price=meta.get("price", {}),
                stats=meta.get("stats", {}),
                characteristics=meta.get("characteristics", {}),
                questions=meta.get("questions", []),
                reviews_period_days=period_days,
                reviews=reviews,
            )
            path = save_product(product, output_dir)
            _report(f"    сохранено: {path} | отзывов: {len(reviews)} | "
                    f"вопросов: {len(meta.get('questions', []))} | "
                    f"оценка: {meta.get('score')} | всего на товаре: {meta.get('total')} | "
                    f"время: {elapsed:.1f} с")
            if not reviews and not all_variants:
                _report("    отзывов по этому варианту не найдено — попробуй без флага --this-variant")

            if i + 1 < len(urls):
                await page.wait_for_timeout(config.delay_ms(config.PRODUCT_DELAY))

        if len(urls) > 1:
            _report(f"Готово: {len(urls)} товаров за {time.perf_counter() - started:.1f} с")


def run(urls, period_days, all_variants, headless, max_reviews,
        output_dir=None, profile_dir=None, fresh_profile=False):
    asyncio.run(_run_async(urls, period_days, all_variants, headless, max_reviews,
                           output_dir=output_dir, profile_dir=profile_dir,
                           fresh_profile=fresh_profile))
