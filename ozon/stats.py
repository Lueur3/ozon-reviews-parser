"""Сводная статистика оценок по собранным отзывам.

`overall` берётся из данных Ozon (`productScore`/`total`) — это честный «средний
за всё время»; нашу анонимную выборку (~50% отзывов) для него использовать нельзя.
`windows` считаются по собранным **сырым** отзывам, включая пустые: оценка без
текста — тоже сигнал. `covered` показывает, покрывает ли выборка всё окно (есть ли
отзыв старше начала окна); если нет — цифры окна смещены к свежим.

`lenses` — срезы той же выборки по признакам отзыва (длина, голоса, медиа, вариант).
Это **не поправка** к оценке: подмножества смещены вниз по построению, потому что
недовольные пишут развёрнутее и голосуют за критику чаще. Замер на 36 товарах
(август 2026): `substantive` ниже опоры на 34 товарах из 36 (в среднем на 0.34),
`voted` — на 35 из 36 (в среднем на 0.54), а у `with_media` единого направления
нет вовсе. Смешивать эти числа с `overall` нельзя, иначе любой товар выглядит
плохим; их смысл в разрыве между строками.

Считается всё это по хронологическому подмножеству (см. collector._stats): доборы
сортировками по оценке намеренно набивают выборку единицами и пятёрками, и срез
по такому пулу измерял бы способ сбора, а не товар.
"""
from . import config
from .parse import variant_map

_DAY = 86_400   # секунд в сутках: работаем с unix-таймстампами, DST на них не влияет

_NOTE = ("Срезы собранной выборки. Не корректируют оценку выше и не должны с ней "
         "смешиваться: подмножества смещены вниз, потому что недовольные пишут "
         "развёрнутее. Смысл — в разрыве между строками, а не в абсолютном значении.")

_CAVEAT_SUBSTANTIVE = ("Около половины таких отзывов (48% на 36 товарах) упоминают доставку, "
                       "упаковку или продавца, а не сам товар.")
_CAVEAT_VOTED = ("Смещён к критике: короткие негативные отзывы собирают примерно в 7 раз "
                 "больше голосов, чем короткие положительные. Ниже опоры на 35 товарах из 36.")
_CAVEAT_MEDIA = ("Единого направления у среза нет: на 36 товарах он уходил и вниз (-1.23), "
                 "и вверх (+0.57), в среднем ноль. Читать только по конкретному товару.")


def _rating(raw: dict):
    score = (raw.get("content") or {}).get("score")
    return score if isinstance(score, int) and 1 <= score <= 5 else None


def _ts(raw: dict) -> int:
    return raw.get("publishedAt") or raw.get("createdAt") or 0


def _texts(raw: dict) -> tuple:
    c = raw.get("content") or {}
    return (c.get("comment") or "", c.get("positive") or "", c.get("negative") or "")


def _has_text(raw: dict) -> bool:
    return any(t.strip() for t in _texts(raw))


def _text_len(raw: dict) -> int:
    """Длина всего написанного покупателем: комментарий плюс достоинства и недостатки."""
    return sum(len(t.strip()) for t in _texts(raw))


def _useful(raw: dict) -> int:
    return (raw.get("usefulness") or {}).get("useful") or 0


def _has_media(raw: dict) -> bool:
    c = raw.get("content") or {}
    return bool(c.get("photos") or c.get("videos"))


def _summary(scores: list) -> dict:
    """Счётчик, средняя и распределение по звёздам для любого подмножества оценок."""
    count = len(scores)
    return {
        "count": count,
        "avg": round(sum(scores) / count, 2) if count else None,
        "dist": {str(s): scores.count(s) for s in range(1, 6)},
    }


def _lenses(rated: list, pid, products: dict) -> dict:
    """Срезы выборки. `rated` — пары (сырой отзыв, оценка); `pid`/`products` — целевой вариант."""
    def pick(keep):
        return _summary([s for r, s in rated if keep(r)])

    out = {
        "_note": _NOTE,
        # Опора для сравнения: без неё остальные срезы не с чем сопоставить,
        # а блок должен читаться сам по себе — его подают на вход анализу.
        "all": _summary([s for _r, s in rated]),
        "substantive": {"min_chars": config.LENS_MIN_CHARS,
                        **pick(lambda r: _text_len(r) >= config.LENS_MIN_CHARS),
                        "caveat": _CAVEAT_SUBSTANTIVE},
        "voted": {"min_useful": config.LENS_MIN_USEFUL,
                  **pick(lambda r: _useful(r) >= config.LENS_MIN_USEFUL),
                  "caveat": _CAVEAT_VOTED},
        "with_media": {**pick(_has_media), "caveat": _CAVEAT_MEDIA},
    }
    # Сравниваем ОПИСАНИЕ варианта, а не itemId: один и тот же цвет/объём живёт у Ozon
    # под несколькими id (разные листинги одного товара). Замер на 23 товарах: у одного
    # из них 194 отзыва из 500 описывают вариант карточки, и ни у одного itemId не
    # совпал с запрошенным — сравнение по id давало пустой срез на всех товарах.
    target = variant_map(pid, products or {})
    if target:
        out["this_variant"] = pick(lambda r: variant_map(r.get("itemId"), products) == target)
    return out


def compute_stats(raw_reviews, overall_score, overall_total, now,
                  windows_days=None, pid=None, products=None) -> dict:
    """Сводка по сырым отзывам Ozon. `now` — tz-aware datetime (инъектируется в тестах)."""
    windows_days = windows_days or config.STATS_WINDOWS_DAYS
    raws = list(raw_reviews)
    now_ts = int(now.timestamp())

    rated = [(r, s) for r in raws if (s := _rating(r)) is not None]
    # Окнам нужна дата, срезам — нет: отзыв без даты всё равно характеризует товар.
    timed = [(t, s) for r, s in rated if (t := _ts(r)) > 0]
    oldest_ts = min((t for t, _ in timed), default=None)

    windows = {}
    for days in windows_days:
        start = now_ts - days * _DAY
        windows[f"{days}d"] = {
            **_summary([s for t, s in timed if t >= start]),
            "covered": oldest_ts is not None and oldest_ts <= start,
        }

    with_text = sum(1 for r in raws if _has_text(r))
    return {
        "overall": {"avg": overall_score, "total": overall_total, "source": "ozon"},
        "collected": {"count": len(raws), "with_text": with_text, "empty": len(raws) - with_text},
        "windows": windows,
        "lenses": _lenses(rated, pid, products),
    }
