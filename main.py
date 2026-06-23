"""CLI: парсер отзывов товаров Ozon → output/{product_id}.json"""
import argparse
from pathlib import Path

import config


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="ozon-reviews-parser",
        description="Парсер отзывов товаров Ozon в JSON.",
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("url", nargs="?", help="ссылка на товар Ozon")
    src.add_argument("-f", "--file",
                     help="файл со списком ссылок (по одной в строке, # — комментарий)")

    p.add_argument("--this-variant", action="store_true",
                   help="только вариант из ссылки (по умолчанию — все варианты товара)")
    p.add_argument("--years", type=float, default=config.REVIEW_PERIOD_DAYS / 365,
                   help="период актуальности отзывов в годах (по умолчанию 1)")
    p.add_argument("--headless", action="store_true",
                   help="headless-режим без окна (на Ozon обычно блокируется; по умолчанию видимое окно)")
    p.add_argument("--max", type=int, default=config.MAX_REVIEWS_PER_PRODUCT,
                   help=f"максимум отзывов на товар (по умолчанию {config.MAX_REVIEWS_PER_PRODUCT})")
    return p.parse_args(argv)


def load_urls(args) -> list[str]:
    if args.file:
        lines = Path(args.file).read_text(encoding="utf-8").splitlines()
        return [s.strip() for s in lines if s.strip() and not s.strip().startswith("#")]
    return [args.url]


def main(argv=None):
    args = parse_args(argv)
    urls = load_urls(args)
    if not urls:
        raise SystemExit("Не передано ни одной ссылки.")

    # Ленивый импорт: --help работает без установленного playwright.
    from ozon.runner import run
    run(
        urls,
        period_days=int(args.years * 365),
        all_variants=not args.this_variant,
        headless=args.headless,
        max_reviews=args.max,
    )


if __name__ == "__main__":
    main()
