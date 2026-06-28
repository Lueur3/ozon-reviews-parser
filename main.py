"""CLI: парсер отзывов товаров Ozon → output/{product_id}.json"""
import argparse
from pathlib import Path

import config


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="ozon-reviews-parser",
        description="Парсер отзывов товаров Ozon в JSON (один файл на товар: output/<id>.json).",
        epilog=(
            "Примеры:\n"
            '  python main.py "https://ozon.ru/t/xxxxxxx"            все варианты, отзывы за год\n'
            '  python main.py "<ссылка>" --this-variant              только вариант из ссылки\n'
            '  python main.py "<ссылка>" --years 2 --max 1000        за 2 года, до 1000 отзывов\n'
            "  python main.py -f urls.txt                            список ссылок из файла\n"
            "\n"
            "По умолчанию: все варианты, отзывы за 1 год, видимое окно Chrome.\n"
            "Запускать с ВЫКЛЮЧЕННЫМ VPN. Диагностика глубины: scripts/audit.py."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src = p.add_mutually_exclusive_group(required=False)
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
    p.add_argument("--doctor", action="store_true",
                   help="самопроверка парсинга (эталонный товар или переданная ссылка)")
    return p.parse_args(argv)


def load_urls(args) -> list[str]:
    if args.file:
        lines = Path(args.file).read_text(encoding="utf-8").splitlines()
        return [s.strip() for s in lines if s.strip() and not s.strip().startswith("#")]
    return [args.url]


def main(argv=None):
    args = parse_args(argv)

    if args.doctor:
        from ozon.doctor import run_doctor
        raise SystemExit(run_doctor(args.url or config.DOCTOR_URL))

    if not (args.url or args.file):
        raise SystemExit("Нужна ссылка на товар, -f файл или --doctor.")
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
