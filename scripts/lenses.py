r"""Сводка срезов (stats.lenses) по уже собранным файлам output/.

Офлайн: браузер не запускается, сеть не нужна, VPN не мешает — читаются только
готовые JSON. Нужен, чтобы оценить срезы сразу на пачке товаров: собрал двадцать
штук обычным прогоном, запустил это и увидел, разделяют срезы товары или нет.

Запуск из корня проекта:
    .\.venv\Scripts\python.exe scripts/lenses.py
    .\.venv\Scripts\python.exe scripts/lenses.py --dir output --min-count 20

В каждой колонке «средняя/сколько отзывов». Читать нужно разрыв между `все` и
остальными колонками, а не абсолютные значения: срезы смещены вниз по построению
(недовольные пишут развёрнутее), поэтому оценкой товара они не являются.
"""
import argparse
import json
from pathlib import Path

from _common import utf8_stdout        # он же чинит sys.path для импорта ozon

from ozon import config

# Порядок колонок: сначала опора, дальше срезы по убыванию размера выборки.
COLUMNS = (("all", "все"), ("this_variant", "вариант"), ("with_media", "медиа"),
           ("substantive", "развёрнутые"), ("voted", "полезные"))


def _cell(lens: dict, min_count: int) -> str:
    """«средняя/n», либо прочерк, если выборка слишком мала, чтобы на неё смотреть."""
    if not lens:
        return "—"
    count, avg = lens.get("count") or 0, lens.get("avg")
    if avg is None:
        return f"—/{count}"
    if count < min_count:
        return f"({avg:.2f}/{count})"      # скобки: цифра есть, но доверять рано
    return f"{avg:.2f}/{count}"


def _rows(paths, min_count):
    rows, skipped = [], []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            skipped.append((path.name, f"не прочитан: {e.__class__.__name__}"))
            continue
        lenses = ((data.get("stats") or {}).get("lenses")) or {}
        if not lenses:
            skipped.append((path.name, "нет блока lenses — файл собран до этой версии"))
            continue
        overall = ((data.get("stats") or {}).get("overall") or {}).get("avg")
        rows.append({
            "name": (data.get("name") or path.stem)[:34],
            "ozon": f"{overall:.2f}" if isinstance(overall, (int, float)) else "—",
            "cells": [_cell(lenses.get(key), min_count) for key, _ in COLUMNS],
            "gap": _gap(lenses),
        })
    return rows, skipped


def _gap(lenses: dict):
    """На сколько «развёрнутые» ниже опоры — главное число этой таблицы."""
    base = (lenses.get("all") or {}).get("avg")
    sub = (lenses.get("substantive") or {}).get("avg")
    return round(sub - base, 2) if isinstance(base, float) and isinstance(sub, float) else None


def main(argv=None):
    utf8_stdout()
    p = argparse.ArgumentParser(description="Таблица срезов по собранным файлам output/")
    p.add_argument("--dir", type=Path, default=config.OUTPUT_DIR,
                   help="папка с JSON (по умолчанию output/)")
    p.add_argument("--min-count", type=int, default=15,
                   help="ниже этого размера выборки средняя печатается в скобках")
    args = p.parse_args(argv)

    paths = sorted(args.dir.glob("*.json"))
    if not paths:
        raise SystemExit(f"В {args.dir} нет .json — сначала собери товары.")

    rows, skipped = _rows(paths, args.min_count)
    if not rows:
        raise SystemExit("Ни в одном файле нет блока lenses: пересобери товары этой версией.")

    head = f"{'товар':<35} {'Ozon':>5}  " + "  ".join(f"{t:>13}" for _, t in COLUMNS)
    print(head)
    print("-" * len(head))
    for r in rows:
        print(f"{r['name']:<35} {r['ozon']:>5}  " + "  ".join(f"{c:>13}" for c in r["cells"]))

    gaps = [r["gap"] for r in rows if r["gap"] is not None]
    if gaps:
        print()
        print(f"Разрыв «развёрнутые минус все»: в среднем {sum(gaps)/len(gaps):+.2f}, "
              f"от {min(gaps):+.2f} до {max(gaps):+.2f} на {len(gaps)} товарах.")
    if skipped:
        print()
        for name, why in skipped:
            print(f"пропущен {name}: {why}")


if __name__ == "__main__":
    main()
