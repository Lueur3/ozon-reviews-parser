"""Самопроверка парсинга: сбор по эталонному товару + отчёт, какая секция отвалилась.

Ловит изменения на стороне Ozon (поменяли разметку/виджеты): вместо молчаливого
пустого JSON — явный FAIL с указанием виджета. Запуск: `python main.py --doctor`.
"""
import asyncio

import config


def check_health(meta: dict, reviews: list, min_chars: int = config.DOCTOR_MIN_CHARS) -> list:
    """Проверка собранного. → list[(секция, 'PASS'|'WARN'|'FAIL', деталь)]; деталь пустая у PASS."""
    price = meta.get("price") or {}
    chars = meta.get("characteristics") or {}
    questions = meta.get("questions") or []
    overall = (meta.get("stats") or {}).get("overall") or {}
    checks = [
        ("id товара", bool(meta.get("product_id")), "FAIL", "id не определён из URL"),
        ("цена", bool(price.get("price") or price.get("card_price")), "FAIL",
         "webPrice-<id>: цена не извлечена"),
        ("характеристики", len(chars) >= min_chars, "FAIL",
         f"webCharacteristics: получено {len(chars)} (< {min_chars})"),
        ("отзывы", len(reviews) >= 1, "FAIL", "webListReviews: 0 отзывов"),
        ("вопросы", len(questions) >= 1, "WARN",
         "webListQuestions: 0 (возможно, у товара нет вопросов)"),
        ("статистика", overall.get("total") is not None, "FAIL", "productScore/total не сняты"),
    ]
    return [(name, "PASS", "") if ok else (name, st, detail)
            for name, ok, st, detail in checks]


def has_failures(report: list) -> bool:
    return any(st == "FAIL" for _, st, _ in report)


def _print_report(url: str, meta: dict, report: list) -> None:
    print(f"\n=== Самопроверка парсинга: {url} ===")
    print(f"товар: {meta.get('name') or '—'} (id {meta.get('product_id')})")
    for name, st, detail in report:
        line = f"  [{st:4}] {name}"
        if detail:
            line += f" — {detail}"
        print(line)
    print("ИТОГ:", "OK" if not has_failures(report) else "ЕСТЬ ПОЛОМКИ — см. FAIL выше")


async def _run_doctor_async(url: str) -> int:
    from .browser import launch_browser
    from .collector import ReviewCollector
    async with launch_browser(headless=False) as (_context, page):
        collector = ReviewCollector(page, url, period_days=config.REVIEW_PERIOD_DAYS,
                                    all_variants=True, max_reviews=config.DOCTOR_MAX_REVIEWS,
                                    page_delay=config.PAGE_DELAY)
        reviews, meta = await collector.collect()
    report = check_health(meta, reviews)
    _print_report(url, meta, report)
    return 1 if has_failures(report) else 0


def run_doctor(url: str) -> int:
    """Живая самопроверка. Возвращает код выхода (0 — ок, 1 — есть FAIL)."""
    return asyncio.run(_run_doctor_async(url))
