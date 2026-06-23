"""Оркестрация: браузер -> сбор отзывов -> сохранение JSON."""
import asyncio
import random

import config
from .browser import launch_browser
from .models import Product
from .reviews import collect_reviews
from .storage import save_product


async def _run_async(urls, period_days, all_variants, headless, max_reviews):
    async with launch_browser(headless=headless) as (context, page):
        for i, url in enumerate(urls):
            mode = "все варианты" if all_variants else "только этот вариант"
            print(f"[{i + 1}/{len(urls)}] {url} ({mode}) — собираю отзывы...")
            try:
                reviews, meta = await collect_reviews(
                    page, url, period_days, all_variants, max_reviews, config.PAGE_DELAY)
            except Exception as e:
                print(f"    ошибка сбора: {e!r}")
                continue

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
                characteristics={},
                reviews_period_days=period_days,
                reviews=reviews,
            )
            path = save_product(product, config.OUTPUT_DIR)
            print(f"    сохранено: {path} | отзывов: {len(reviews)} | "
                  f"оценка: {meta.get('score')} | всего на товаре: {meta.get('total')}")
            if not reviews and not all_variants:
                print("    отзывов по этому варианту не найдено — попробуй без флага --this-variant")

            if i + 1 < len(urls):
                await page.wait_for_timeout(random.uniform(*config.PRODUCT_DELAY) * 1000)


def run(urls, period_days, all_variants, headless, max_reviews):
    asyncio.run(_run_async(urls, period_days, all_variants, headless, max_reviews))
