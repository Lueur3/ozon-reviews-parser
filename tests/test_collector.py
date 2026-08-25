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
    assert set(meta) == {"product_id", "resolved_url", "name", "variant", "price", "stats",
                         "characteristics", "questions", "questions_widget_seen",
                         "score", "total"}


def test_stats_only_over_chrono_subset():
    import time
    now_ts = int(time.time())
    raws = {"a": _raw("a", now_ts - 5 * 86400),
            "b": _raw("b", now_ts - 6 * 86400),
            "c": _raw("c", now_ts - 7 * 86400)}
    c = _collector(raws)
    c._chrono_uuids = {"a", "b"}  # 'c' добран сортировкой по оценке — в статистику не идёт
    c.score, c.total = 4.9, 500
    s = c._stats()
    assert s["collected"]["count"] == 2
    assert s["windows"]["30d"]["count"] == 2
    assert s["overall"]["total"] == 500


def test_is_empty():
    assert _is_empty(Review(author="x", rating=5, date="2026-01-01", text="  "))
    assert not _is_empty(Review(author="x", rating=5, date="2026-01-01", pros="плюс"))


# --- курсорная пагинация вопросов (новая лента Ozon) ---

def _pdp_page(texts, cursor=None):
    """Ответ Ozon в новой разметке: вопросы + необязательный курсор в paginator."""
    ws = {"webPDPListQuestions-1-default-1": {"questions": [
        {"questionUuid": f"u{t}", "author": {"name": {"text": "Кто-то"}},
         "text": {"text": t}, "createdAt": {"text": "24 августа 2026"},
         "answers": [{"author": {"name": {"text": "Ответчик"}},
                      "text": {"text": "ответ"}, "createdAt": {"text": "24 августа 2026"}}]}
        for t in texts
    ]}}
    if cursor:
        ws["paginator-1-default-1"] = {"nextPage": cursor}
    return {"widgetStates": ws}


class _PagedClient:
    """Отдаёт заранее заданные страницы и запоминает, что у него запрашивали."""

    def __init__(self, pages):
        self.pages = pages
        self.asked = []

    async def fetch(self, param):
        self.asked.append(param)
        return self.pages[len(self.asked) - 1]


def _questions_collector(client):
    c = _collector({})
    c.client = client
    c.ppath = "/product/tovar-1234567890/"
    c.page = type("P", (), {"wait_for_timeout": staticmethod(lambda ms: _done())})()
    return c


def _done():
    import asyncio
    fut = asyncio.get_event_loop().create_future()
    fut.set_result(None)
    return fut


def test_questions_follow_the_cursor():
    """С ?page=N Ozon отдаёт одну и ту же десятку — идти нужно по nextPage."""
    import asyncio
    client = _PagedClient([
        _pdp_page(["в1", "в2"], cursor="/product/tovar-1234567890/questions/?page_key=AAA"),
        _pdp_page(["в3", "в4"], cursor="/product/tovar-1234567890/questions/?page_key=BBB"),
        _pdp_page(["в5"]),                       # курсора нет — конец ленты
    ])
    qs = asyncio.run(_questions_collector(client)._collect_questions())
    assert [q["text"] for q in qs] == ["в1", "в2", "в3", "в4", "в5"]
    assert client.asked[1].endswith("page_key=AAA")
    assert client.asked[2].endswith("page_key=BBB")


def test_questions_stop_when_page_adds_nothing_new():
    import asyncio
    client = _PagedClient([
        _pdp_page(["в1"], cursor="/next"),
        _pdp_page(["в1"], cursor="/next"),       # повтор — дальше не идём
        _pdp_page(["в2"]),
    ])
    qs = asyncio.run(_questions_collector(client)._collect_questions())
    assert [q["text"] for q in qs] == ["в1"]
    assert len(client.asked) == 2
