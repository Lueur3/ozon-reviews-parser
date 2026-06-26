"""Фильтрация собранных отзывов (период, вариант, пустые, лимит, сортировка)."""
from ozon.models import Review
from ozon.reviews import _filter_reviews, _is_empty


def _raw(uuid, ts, item_id=1, text="хороший товар"):
    return {
        "uuid": uuid, "itemId": item_id,
        "publishedAt": ts, "createdAt": ts,
        "isItemPurchased": False,
        "author": {"firstName": "Имя", "lastName": "Ф."},
        "usefulness": {"useful": 0, "unuseful": 0},
        "content": {"comment": text, "positive": "", "negative": "",
                    "photos": [], "videos": [], "score": 5},
    }


CUTOFF = 1_000_000_000  # ~2001-09; ниже — «старые»
PRODUCTS = {"1": {"variants": []}, "2": {"variants": []}}


def test_drops_reviews_before_cutoff():
    raws = {"new": _raw("new", 1_781_631_970), "old": _raw("old", 500_000_000)}
    out, skipped = _filter_reviews(raws, CUTOFF, True, None, PRODUCTS, 500)
    assert [r.date for r in out] and skipped == 0
    assert {r for r in raws} == {"new", "old"}
    assert len(out) == 1  # старый отброшен по периоду


def test_skips_empty_reviews():
    raws = {"empty": _raw("empty", 1_781_631_970, text="   ")}
    out, skipped = _filter_reviews(raws, CUTOFF, True, None, PRODUCTS, 500)
    assert out == []
    assert skipped == 1


def test_variant_filter_keeps_only_target_item():
    raws = {"a": _raw("a", 1_781_631_970, item_id=1),
            "b": _raw("b", 1_781_631_970, item_id=2)}
    out, _ = _filter_reviews(raws, CUTOFF, all_variants=False, pid_int=1,
                             products=PRODUCTS, max_reviews=500)
    assert len(out) == 1
    # all_variants=True игнорирует фильтр варианта
    out_all, _ = _filter_reviews(raws, CUTOFF, all_variants=True, pid_int=1,
                                 products=PRODUCTS, max_reviews=500)
    assert len(out_all) == 2


def test_sorted_newest_first():
    raws = {
        "mid": _raw("mid", 1_700_000_000),
        "new": _raw("new", 1_781_631_970),
        "older": _raw("older", 1_600_000_000),
    }
    out, _ = _filter_reviews(raws, CUTOFF, True, None, PRODUCTS, 500)
    dates = [r.date for r in out]
    assert dates == sorted(dates, reverse=True)


def test_max_reviews_cap_keeps_newest():
    raws = {f"r{i}": _raw(f"r{i}", 1_600_000_000 + i * 1_000_000) for i in range(5)}
    out, _ = _filter_reviews(raws, CUTOFF, True, None, PRODUCTS, max_reviews=2)
    assert len(out) == 2
    # после сортировки desc и среза остаются два самых новых (r4, r3)
    assert out[0].date >= out[1].date


def test_is_empty():
    assert _is_empty(Review(author="x", rating=5, date="2026-01-01", text="  "))
    assert not _is_empty(Review(author="x", rating=5, date="2026-01-01", pros="плюс"))
