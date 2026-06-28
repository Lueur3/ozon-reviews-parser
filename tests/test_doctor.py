"""Самопроверка: check_health (чистая логика, без сети)."""
from ozon.doctor import check_health, has_failures
from ozon.models import Review


def _meta(**over):
    meta = {
        "product_id": "1",
        "name": "Товар",
        "price": {"price": "10 ₽"},
        "characteristics": {f"k{i}": "v" for i in range(6)},
        "questions": [{"text": "вопрос"}],
        "stats": {"overall": {"total": 100}},
    }
    meta.update(over)
    return meta


def _reviews(n=1):
    return [Review(author="a", rating=5, date="2026-01-01", text="t") for _ in range(n)]


def _status(report):
    return {name: st for name, st, _ in report}


def test_all_pass():
    report = check_health(_meta(), _reviews(3))
    assert all(st == "PASS" for _, st, _ in report)
    assert not has_failures(report)


def test_each_critical_section_fails():
    cases = {
        "id товара": _meta(product_id=None),
        "цена": _meta(price={}),
        "характеристики": _meta(characteristics={"a": "1"}),  # < 5
        "отзывы": _meta(),  # с пустым списком отзывов ниже
        "статистика": _meta(stats={"overall": {}}),
    }
    for section, meta in cases.items():
        reviews = [] if section == "отзывы" else _reviews(1)
        report = check_health(meta, reviews)
        assert _status(report)[section] == "FAIL", section
        assert has_failures(report)


def test_no_questions_is_warn_not_fail():
    report = check_health(_meta(questions=[]), _reviews(1))
    assert _status(report)["вопросы"] == "WARN"
    assert not has_failures(report)  # WARN не валит самопроверку


def test_fail_detail_present():
    report = check_health(_meta(price={}), _reviews(1))
    price = next(r for r in report if r[0] == "цена")
    assert price[1] == "FAIL" and "webPrice" in price[2]
