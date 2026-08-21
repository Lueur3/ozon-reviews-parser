"""Регрессия парсеров на РЕАЛЬНЫХ (обезличенных) ответах Ozon из tests/fixtures.

Ловит поломки в нашем коде (рефактор сломал извлечение). Изменения на стороне
Ozon эти фикстуры заморожены и не заметят — это задача живого `--doctor`.

Проверяем не «больше нуля», а конкретные поля: иначе тест продолжит проходить,
когда Ozon уберёт productScore или вложенность, а парсер вернёт None.
"""
import json
from pathlib import Path

from ozon import parse

FIX = Path(__file__).parent / "fixtures"

REVIEW_FIELDS = {"author", "rating", "date", "text", "pros", "cons", "useful_count",
                 "unuseful_count", "purchased", "photos", "videos", "variant"}


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_reviews_widget_returns_all_four_parts():
    res = parse.extract_reviews_widget(_load("reviews_page.json"))
    assert res is not None, "webListReviews не найден — изменилось имя виджета?"
    reviews, products, score, total = res
    assert len(reviews) >= 1
    assert isinstance(score, (int, float)), "productScore пропал из ответа"
    assert isinstance(total, int) and total > 0, "paging.total пропал из ответа"
    assert products, "products пуст — вариант товара будет не определён"


def test_review_maps_every_field():
    reviews, products, _score, _total = parse.extract_reviews_widget(_load("reviews_page.json"))
    raw = reviews[0]
    rev = parse.to_review(raw, products)

    assert set(vars(rev)) == REVIEW_FIELDS, "состав полей Review изменился"
    assert rev.rating == (raw.get("content") or {}).get("score")
    assert rev.date == parse.ts_to_date(raw["publishedAt"])
    assert rev.date.startswith("20") and len(rev.date) == 10   # ISO YYYY-MM-DD
    assert rev.author and rev.author != "Аноним"               # имя автора разобрано
    assert isinstance(rev.purchased, bool)
    assert isinstance(rev.useful_count, int) and isinstance(rev.unuseful_count, int)
    assert isinstance(rev.photos, list) and isinstance(rev.videos, list)
    assert rev.text or rev.pros or rev.cons                    # отзыв непустой


def test_variant_is_resolved_from_products():
    reviews, products, _s, _t = parse.extract_reviews_widget(_load("reviews_page.json"))
    rev = parse.to_review(reviews[0], products)
    assert rev.variant, "вариант не определился по itemId"
    assert all(k and v for k, v in rev.variant.items())


def test_characteristics_picks_widest_widget():
    chars = parse.parse_characteristics(_load("features.json"))
    assert len(chars) >= 30, "выбран короткий виджет вместо полного"
    assert "Тип" in chars
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in chars.items())
    assert all(k.strip() and v.strip() for k, v in chars.items())


def test_questions_parse_with_answers():
    qs = parse.parse_questions(_load("questions.json"))
    assert len(qs) >= 1
    q = qs[0]
    assert set(q) == {"_id", "_has_more", "author", "text", "date", "answers"}
    assert q["text"] and q["author"] and q["date"]
    assert q["answers"], "answered_only=True, но ответов нет"
    a = q["answers"][0]
    assert set(a) == {"author", "text", "date", "is_best"}
    assert a["text"] and a["author"]
    assert isinstance(a["is_best"], bool)


def test_answered_only_filter_is_effective():
    data = _load("questions.json")
    answered = parse.parse_questions(data, answered_only=True)
    every = parse.parse_questions(data, answered_only=False)
    assert len(answered) <= len(every)
    assert all(q["answers"] for q in answered)
