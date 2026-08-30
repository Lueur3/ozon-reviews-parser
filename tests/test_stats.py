"""Статистика оценок (compute_stats) — чистая логика над сырыми отзывами Ozon."""
from datetime import datetime, timezone

from ozon import config
from ozon.stats import compute_stats

DAY = 86_400
NOW = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
NOW_TS = int(NOW.timestamp())

LONG = "подробный отзыв " * 12   # заведомо длиннее порога LENS_MIN_CHARS
SHORT = "норм"

# Каталог вариантов в форме Ozon. 111 и 333 — РАЗНЫЕ листинги одного и того же цвета:
# так у Ozon и бывает, поэтому вариант определяется описанием, а не id листинга.
PRODUCTS = {
    "111": {"variants": [{"name": "Цвет товара", "value": "чёрный"}]},
    "222": {"variants": [{"name": "Цвет товара", "value": "белый"}]},
    "333": {"variants": [{"name": "Цвет товара", "value": "чёрный"}]},
}


def _raw(score, days_ago, text="нормально", *, useful=0, photos=None, videos=None,
         item_id=None, pros="", cons=""):
    """Сырой отзыв в форме Ozon: оценка в content.score, дата в publishedAt."""
    raw = {"publishedAt": NOW_TS - days_ago * DAY,
           "content": {"score": score, "comment": text, "positive": pros, "negative": cons,
                       "photos": photos or [], "videos": videos or []},
           "usefulness": {"useful": useful, "unuseful": 0}}
    if item_id is not None:
        raw["itemId"] = item_id
    return raw


def _stats(reviews, score=4.9, total=1000, pid=None, products=None):
    return compute_stats(reviews, score, total, NOW, pid=pid, products=products)


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


# --- lenses: срезы выборки по признакам отзыва ------------------------------

def test_substantive_selects_only_long_reviews():
    s = _stats([_raw(1, 1, text=LONG), _raw(5, 1, text=SHORT), _raw(5, 2, text=SHORT)])
    lens = s["lenses"]["substantive"]
    assert lens["count"] == 1
    assert lens["avg"] == 1.0            # длинный отзыв был единственным и негативным
    assert s["windows"]["30d"]["avg"] == 3.67   # общая выборка при этом не тронута


def test_substantive_counts_pros_and_cons_not_only_comment():
    """Покупатель мог написать всё в «достоинствах» — это тоже развёрнутый отзыв."""
    split = _raw(4, 1, text="", pros=LONG[:100], cons=LONG[:60])
    s = _stats([split])
    assert s["lenses"]["substantive"]["count"] == 1


def test_voted_uses_threshold_from_config():
    reviews = [_raw(1, 1, useful=1), _raw(5, 1, useful=0), _raw(5, 2, useful=0)]
    lens = _stats(reviews)["lenses"]["voted"]
    assert lens["min_useful"] == config.LENS_MIN_USEFUL
    assert lens["count"] == 1
    assert lens["avg"] == 1.0


def test_thresholds_are_read_at_call_time(monkeypatch):
    """Порог меняется настройкой, а не правкой кода: значения читаются из config."""
    reviews = [_raw(2, 1, useful=3), _raw(5, 1, useful=1)]
    assert _stats(reviews)["lenses"]["voted"]["count"] == 2
    monkeypatch.setattr(config, "LENS_MIN_USEFUL", 3)
    tightened = _stats(reviews)["lenses"]["voted"]
    assert tightened["min_useful"] == 3
    assert tightened["count"] == 1
    assert tightened["avg"] == 2.0


def test_with_media_covers_photos_and_videos():
    reviews = [_raw(2, 1, photos=["p.jpg"]), _raw(3, 1, videos=["v.mp4"]), _raw(5, 1)]
    lens = _stats(reviews)["lenses"]["with_media"]
    assert lens["count"] == 2
    assert lens["avg"] == 2.5


def test_this_variant_absent_without_product_id():
    """У короткой ссылки id известен только после редиректа — срез не считаем."""
    s = _stats([_raw(5, 1, item_id=111)], pid=None, products=PRODUCTS)
    assert "this_variant" not in s["lenses"]


def test_this_variant_matches_the_description_not_the_listing_id():
    """Один цвет живёт у Ozon под несколькими id: сравнение по id давало пустой срез."""
    reviews = [_raw(5, 1, item_id=111), _raw(1, 1, item_id=222), _raw(3, 1, item_id=333)]
    lens = _stats(reviews, pid="111", products=PRODUCTS)["lenses"]["this_variant"]
    assert lens["count"] == 2      # 111 и 333 — разные листинги одного и того же цвета
    assert lens["avg"] == 4.0


def test_this_variant_absent_when_the_product_has_no_variants():
    """Без вариантов срез повторял бы `all` — лишняя строка, которую можно принять за сигнал."""
    s = _stats([_raw(5, 1, item_id=999)], pid="999", products={"999": {}})
    assert "this_variant" not in s["lenses"]


def test_empty_lens_reports_none_avg_not_zero():
    lens = _stats([_raw(5, 1, text=SHORT)])["lenses"]["substantive"]
    assert lens["count"] == 0
    assert lens["avg"] is None
    assert sum(lens["dist"].values()) == 0


def test_lenses_ignore_missing_timestamp():
    """Срезу дата не нужна: отзыв без publishedAt всё равно характеризует товар."""
    s = _stats([{"content": {"score": 1, "comment": LONG}}])
    assert s["windows"]["365d"]["count"] == 0
    assert s["lenses"]["substantive"]["count"] == 1


def test_lenses_do_not_change_the_rest_of_stats():
    reviews = [_raw(1, 1, text=LONG, useful=9, photos=["p.jpg"], item_id=111),
               _raw(5, 2, text=SHORT)]
    full = _stats(reviews, pid="111", products=PRODUCTS)
    assert full["overall"] == {"avg": 4.9, "total": 1000, "source": "ozon"}
    assert full["collected"] == {"count": 2, "with_text": 2, "empty": 0}
    assert full["windows"]["30d"]["avg"] == 3.0    # среднее по всей выборке, без срезов


def test_all_lens_is_the_baseline_for_the_others():
    """Срезы сравнивают с `all`, поэтому опора считается по той же выборке."""
    reviews = [_raw(1, 1, text=LONG), _raw(5, 1, text=SHORT), _raw(5, 2, text=SHORT)]
    lenses = _stats(reviews)["lenses"]
    assert lenses["all"]["count"] == 3
    assert lenses["all"]["avg"] == 3.67          # (1+5+5)/3
    assert lenses["substantive"]["avg"] == 1.0   # срез заметно ниже опоры


def test_lens_dist_agrees_with_count():
    reviews = [_raw(s, 1, text=LONG) for s in (1, 1, 3, 5)]
    lens = _stats(reviews)["lenses"]["substantive"]
    assert lens["dist"] == {"1": 2, "2": 0, "3": 1, "4": 0, "5": 1}
    assert sum(lens["dist"].values()) == lens["count"] == 4


def test_note_and_caveats_are_shipped_with_the_numbers():
    """Оговорки едут в JSON: его читает не только человек, но и модель на шаге анализа."""
    lenses = _stats([_raw(5, 1)])["lenses"]
    assert "не корректируют оценку" in lenses["_note"].lower()
    assert all("caveat" in lenses[k] for k in ("substantive", "voted", "with_media"))
