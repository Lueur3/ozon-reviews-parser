"""Фильтрация собранных отзывов в ReviewCollector (период, вариант, пустые, лимит, сортировка).

Сетевые методы (_bootstrap/_fetch/курсоры) не тестируем — требуют живого Ozon.
_filtered работает только над атрибутами, поэтому конструируем коллектор с page=None.
"""
from ozon.collector import ReviewCollector, _is_empty
from ozon.models import Review

CUTOFF = 1_000_000_000  # ~2001-09; ниже — «старые»
PRODUCTS = {"1": {"variants": []}, "2": {"variants": []}}


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


def _collector(reviews_by_uuid, *, all_variants=True, pid_int=None, max_reviews=500):
    c = ReviewCollector(page=None, url="", period_days=1, all_variants=all_variants,
                        max_reviews=max_reviews, page_delay=(0, 0))
    c.reviews_by_uuid = reviews_by_uuid
    c.products = PRODUCTS
    c.pid_int = pid_int
    c.cutoff = CUTOFF  # фиксируем, не зависим от текущей даты
    return c


def test_drops_reviews_before_cutoff():
    raws = {"new": _raw("new", 1_781_631_970), "old": _raw("old", 500_000_000)}
    out, skipped = _collector(raws)._filtered()
    assert len(out) == 1 and skipped == 0  # старый отброшен по периоду


def test_skips_empty_reviews():
    raws = {"empty": _raw("empty", 1_781_631_970, text="   ")}
    out, skipped = _collector(raws)._filtered()
    assert out == []
    assert skipped == 1


def test_variant_filter_keeps_only_target_item():
    raws = {"a": _raw("a", 1_781_631_970, item_id=1),
            "b": _raw("b", 1_781_631_970, item_id=2)}
    out, _ = _collector(raws, all_variants=False, pid_int=1)._filtered()
    assert len(out) == 1
    out_all, _ = _collector(raws, all_variants=True, pid_int=1)._filtered()
    assert len(out_all) == 2  # all_variants=True игнорирует фильтр варианта


def test_sorted_newest_first():
    raws = {
        "mid": _raw("mid", 1_700_000_000),
        "new": _raw("new", 1_781_631_970),
        "older": _raw("older", 1_600_000_000),
    }
    out, _ = _collector(raws)._filtered()
    dates = [r.date for r in out]
    assert dates == sorted(dates, reverse=True)


def test_max_reviews_cap_keeps_newest():
    raws = {f"r{i}": _raw(f"r{i}", 1_600_000_000 + i * 1_000_000) for i in range(5)}
    out, _ = _collector(raws, max_reviews=2)._filtered()
    assert len(out) == 2
    assert out[0].date >= out[1].date  # после сортировки desc остаются два самых новых


def test_meta_shape():
    c = _collector({})
    c.product_id = "1"
    c.resolved_url = "https://ozon.ru/product/x-1/"
    c.score, c.total = 4.8, 123
    meta = c._meta(price={"price": "10 ₽"}, characteristics={"Тип": "X"},
                   questions=[], stats={"overall": {}})
    assert meta["product_id"] == "1"
    assert meta["price"] == {"price": "10 ₽"}
    assert meta["stats"] == {"overall": {}}
    assert meta["score"] == 4.8 and meta["total"] == 123
    assert set(meta) == {"product_id", "resolved_url", "name", "variant",
                         "price", "stats", "characteristics", "questions", "score", "total"}


def test_is_empty():
    assert _is_empty(Review(author="x", rating=5, date="2026-01-01", text="  "))
    assert not _is_empty(Review(author="x", rating=5, date="2026-01-01", pros="плюс"))
