"""Статистика оценок (compute_stats) — чистая логика над сырыми отзывами Ozon."""
from datetime import datetime, timezone

from ozon.stats import compute_stats

DAY = 86_400
NOW = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
NOW_TS = int(NOW.timestamp())


def _raw(score, days_ago, text="нормально"):
    """Сырой отзыв в форме Ozon: оценка в content.score, дата в publishedAt."""
    return {"publishedAt": NOW_TS - days_ago * DAY,
            "content": {"score": score, "comment": text, "positive": "", "negative": ""}}


def _stats(reviews, score=4.9, total=1000):
    return compute_stats(reviews, score, total, NOW)


def test_overall_from_ozon_not_from_sample():
    s = _stats([_raw(1, 5), _raw(1, 5)], score=4.9, total=136783)
    assert s["overall"] == {"avg": 4.9, "total": 136783, "source": "ozon"}


def test_empty_input():
    s = _stats([], score=None, total=None)
    assert s["overall"]["avg"] is None
    assert s["collected"] == {"count": 0, "with_text": 0, "empty": 0}
    assert all(w["count"] == 0 and w["avg"] is None for w in s["windows"].values())


def test_avg_and_dist():
    s = _stats([_raw(5, 1), _raw(5, 2), _raw(3, 3), _raw(1, 4)])
    w = s["windows"]["30d"]
    assert w["count"] == 4
    assert w["avg"] == 3.5  # (5+5+3+1)/4
    assert w["dist"] == {"1": 1, "2": 0, "3": 1, "4": 0, "5": 2}
    assert sum(w["dist"].values()) == w["count"]


def test_empty_reviews_counted_in_stats():
    # 1★ без текста — учитывается в оценках, но не в with_text
    s = _stats([_raw(5, 1, text="отлично"), _raw(1, 2, text="")])
    assert s["collected"] == {"count": 2, "with_text": 1, "empty": 1}
    assert s["windows"]["30d"]["count"] == 2  # обе оценки в распределении
    assert s["windows"]["30d"]["dist"]["1"] == 1


def test_windows_are_nested():
    s = _stats([_raw(5, 15), _raw(4, 100), _raw(3, 300)])
    counts = {k: w["count"] for k, w in s["windows"].items()}
    assert counts == {"30d": 1, "90d": 1, "180d": 2, "365d": 3}


def test_window_boundary_inclusive():
    s = _stats([_raw(4, 30)])  # ровно 30 дней назад
    assert s["windows"]["30d"]["count"] == 1


def test_covered_flag():
    # есть отзыв старше начала окна -> covered True для всех окон
    covered = _stats([_raw(5, 400), _raw(5, 1)])
    assert all(w["covered"] for w in covered["windows"].values())
    # все отзывы свежее начала окна -> 30d не покрыт
    fresh = _stats([_raw(5, 1), _raw(4, 5)])
    assert fresh["windows"]["30d"]["covered"] is False
    assert fresh["windows"]["365d"]["covered"] is False


def test_invalid_scores_ignored_in_ratings_but_counted_in_collected():
    reviews = [_raw(5, 1), _raw(0, 1), _raw(None, 1), {"publishedAt": NOW_TS, "content": {"score": 7}}]
    s = _stats(reviews)
    assert s["collected"]["count"] == 4
    assert s["windows"]["30d"]["count"] == 1  # только валидная оценка 5
    assert s["windows"]["30d"]["avg"] == 5.0


def test_review_without_timestamp_excluded_from_windows():
    reviews = [{"content": {"score": 5, "comment": "ok"}}]  # нет publishedAt/createdAt
    s = _stats(reviews)
    assert s["collected"]["count"] == 1
    assert s["windows"]["365d"]["count"] == 0


def test_avg_rounded_two_decimals():
    s = _stats([_raw(5, 1), _raw(4, 1), _raw(4, 1)])  # 13/3 = 4.333...
    assert s["windows"]["30d"]["avg"] == 4.33
