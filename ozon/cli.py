"""CLI парсера: разбор аргументов и запуск. Точка входа — main().

Запускается тремя способами: `python main.py ...`, `python -m ozon ...`
и командой `ozon-reviews-parser ...` после установки пакета.
"""
import argparse
from pathlib import Path

from . import config
from .urls import normalize


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="ozon-reviews-parser",
        description="Парсер отзывов товаров Ozon в JSON (один файл на товар: output/<id>.json).",
        epilog=(
            "Товар задаётся короткой ссылкой «Поделиться», полной ссылкой карточки\n"
            "или артикулом из поиска.\n\n"
            "Примеры:\n"
            '  python main.py "<ссылка>"                             все варианты, за год\n'
            "  python main.py 138342427                              по артикулу из поиска\n"
            '  python main.py "<ссылка>" --this-variant              только вариант из ссылки\n'
            '  python main.py "<ссылка>" --years 2 --max 1000        за 2 года, до 1000 отзывов\n'
            "  python main.py -f urls.txt                            список ссылок из файла\n"
            '  python main.py "<ссылка>" --doctor                    самопроверка парсинга\n'
            "\n"
            "По умолчанию: все варианты, отзывы за 1 год, видимое окно Chrome.\n"
            "Запускать с ВЫКЛЮЧЕННЫМ VPN. Диагностика глубины: scripts/audit.py."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src = p.add_mutually_exclusive_group(required=False)
    src.add_argument("url", nargs="?",
                     help="ссылка на товар Ozon (короткая или полная) либо артикул")
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
                   help="самопроверка парсинга по переданной ссылке: печатает PASS/WARN/FAIL по секциям")
    p.add_argument("--output-dir", type=Path, default=config.OUTPUT_DIR,
                   help=f"куда писать JSON (по умолчанию {config.OUTPUT_DIR.name}/)")
    p.add_argument("--profile-dir", type=Path, default=config.PROFILE_DIR,
                   help=f"где хранить профиль браузера (по умолчанию {config.PROFILE_DIR.name}/)")
    p.add_argument("--fresh-profile", action="store_true",
                   help="удалить сохранённый профиль браузера перед запуском "
                        "(если сессия испортилась: залипла капча, забанен отпечаток)")
    return p.parse_args(argv)


def load_urls(args) -> list[str]:
    """Ссылки из аргумента или файла, приведённые к переходибельному виду."""
    if args.file:
        lines = Path(args.file).read_text(encoding="utf-8").splitlines()
        raw = [s.strip() for s in lines if s.strip() and not s.strip().startswith("#")]
    else:
        raw = [args.url]
    return [normalize(s) for s in raw]


def main(argv=None):
    args = parse_args(argv)

    # Ленивые импорты: --help работает без установленного playwright.
    if args.doctor:
        if not args.url:
            raise SystemExit("Для --doctor нужна ссылка на товар: main.py --doctor \"<ссылка>\"")
        from .doctor import run_doctor
        raise SystemExit(guarded(lambda: run_doctor(normalize(args.url),
                                                    profile_dir=args.profile_dir,
                                                    fresh_profile=args.fresh_profile)))

    if not (args.url or args.file):
        raise SystemExit("Нужна ссылка на товар, -f файл или --doctor.")
    urls = load_urls(args)
    if not urls:
        raise SystemExit("Не передано ни одной ссылки.")

    from .runner import run
    raise SystemExit(guarded(lambda: run(
        urls,
        period_days=int(args.years * 365),
        all_variants=not args.this_variant,
        headless=args.headless,
        max_reviews=args.max,
        output_dir=args.output_dir,
        profile_dir=args.profile_dir,
        fresh_profile=args.fresh_profile,
    )))


def guarded(action) -> int:
    """Запускает работу, переводя прерывание и известные сбои в понятный текст."""
    from .errors import OzonParserError
    try:
        return action() or 0
    except KeyboardInterrupt:
        print("\nПрервано пользователем.")
        return 130                      # общепринятый код для SIGINT
    except OzonParserError as e:
        print(f"Ошибка: {e}")
        return 1
