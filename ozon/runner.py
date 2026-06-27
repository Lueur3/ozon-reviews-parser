"""Оркестрация: браузер -> сбор отзывов -> сохранение JSON."""
import asyncio
import random
import time

import config
from .browser import launch_browser
from .collector import ReviewCollector
from .models import Product
from .storage import save_product


async def _run_async(urls, period_days, all_variants, headless, max_reviews):
    started = time.perf_counter()
    async with launch_browser(headless=headless) as (context, page):
        for i, url in enumerate(urls):
            mode = "все варианты" if all_variants else "только этот вариант"
            print(f"[{i + 1}/{len(urls)}] {url} ({mode}) — собираю отзывы...")
            t0 = time.perf_counter()
            try:
                collector = ReviewCollector(
                    page, url, period_days=period_days, all_variants=all_variants,
                    max_reviews=max_reviews, page_delay=config.PAGE_DELAY)
                reviews, meta = await collector.collect()
            except Exception as e:
                print(f"    ошибка сбора: {e!r}")
                continue
            elapsed = time.perf_counter() - t0

            pid = meta.get("product_id")
            if not pid:
                print(f"    не удалось определить id товара (итоговый URL: {meta.get('resolved_url')})")
                continue

            name = meta.get("name") or await page.title()
            product = Product(
                url=meta.get("resolved_url") or url,
                product_id=pid,
                name=name,
                variant=meta.get("variant", {}),
                price=meta.get("price", {}),
                characteristics=meta.get("characteristics", {}),
                questions=meta.get("questions", []),
                reviews_period_days=period_days,
                reviews=reviews,
            )
            path = save_product(product, config.OUTPUT_DIR)
            print(f"    сохранено: {path} | отзывов: {len(reviews)} | "
                  f"вопросов: {len(meta.get('questions', []))} | "
                  f"оценка: {meta.get('score')} | всего на товаре: {meta.get('total')} | "
                  f"время: {elapsed:.1f} с")
            if not reviews and not all_variants:
                print("    отзывов по этому варианту не найдено — попробуй без флага --this-variant")

            if i + 1 < len(urls):
                await page.wait_for_timeout(random.uniform(*config.PRODUCT_DELAY) * 1000)

        if len(urls) > 1:
            print(f"Готово: {len(urls)} товаров за {time.perf_counter() - started:.1f} с")


def run(urls, period_days, all_variants, headless, max_reviews):
    asyncio.run(_run_async(urls, period_days, all_variants, headless, max_reviews))
