"""Сводная статистика оценок по собранным отзывам.

`overall` берётся из данных Ozon (`productScore`/`total`) — это честный «средний
за всё время»; нашу анонимную выборку (~50% отзывов) для него использовать нельзя.
`windows` считаются по собранным **сырым** отзывам, включая пустые: оценка без
текста — тоже сигнал. `covered` показывает, покрывает ли выборка всё окно (есть ли
отзыв старше начала окна); если нет — цифры окна смещены к свежим.
"""
_DAY = 86_400
_WINDOWS_DAYS = (30, 90, 180, 365)


def _rating(raw: dict):
    score = (raw.get("content") or {}).get("score")
    return score if isinstance(score, int) and 1 <= score <= 5 else None


def _ts(raw: dict) -> int:
    return raw.get("publishedAt") or raw.get("createdAt") or 0


def _has_text(raw: dict) -> bool:
    c = raw.get("content") or {}
    return bool((c.get("comment") or "").strip()
                or (c.get("positive") or "").strip()
                or (c.get("negative") or "").strip())


def compute_stats(raw_reviews, overall_score, overall_total, now, windows_days=_WINDOWS_DAYS) -> dict:
    """Сводка по сырым отзывам Ozon. `now` — tz-aware datetime (инъектируется в тестах)."""
    raws = list(raw_reviews)
    now_ts = int(now.timestamp())

    rated = [(_ts(r), s) for r in raws if (s := _rating(r)) is not None]
    rated = [(t, s) for t, s in rated if t > 0]
    oldest_ts = min((t for t, _ in rated), default=None)

    windows = {}
    for days in windows_days:
        start = now_ts - days * _DAY
        sel = [s for t, s in rated if t >= start]
        count = len(sel)
        windows[f"{days}d"] = {
            "count": count,
            "avg": round(sum(sel) / count, 2) if count else None,
            "dist": {str(s): sel.count(s) for s in range(1, 6)},
            "covered": oldest_ts is not None and oldest_ts <= start,
        }

    with_text = sum(1 for r in raws if _has_text(r))
    return {
        "overall": {"avg": overall_score, "total": overall_total, "source": "ozon"},
        "collected": {"count": len(raws), "with_text": with_text, "empty": len(raws) - with_text},
        "windows": windows,
    }
