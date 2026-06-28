"""Регрессия парсеров на РЕАЛЬНЫХ (обезличенных) ответах Ozon из tests/fixtures.

Ловит поломки в нашем коде (рефактор сломал извлечение). Изменения на стороне
Ozon эти фикстуры заморожены и не заметят — это задача живого `--doctor`.
"""
import json
from pathlib import Path

from ozon import parse

FIX = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_reviews_widget_extracts_and_maps():
    res = parse.extract_reviews_widget(_load("reviews_page.json"))
    assert res is not None
    reviews, products, score, total = res
    assert len(reviews) >= 1
    assert score is not None and total is not None
    rev = parse.to_review(reviews[0], products)
    assert rev.rating in range(1, 6)
    assert rev.date  # ISO-дата извлечена из publishedAt
    assert rev.author  # автор (обезличенный) непустой


def test_characteristics_picks_widest_widget():
    chars = parse.parse_characteristics(_load("features.json"))
    assert len(chars) >= 30  # выбран полный виджет (~35), а не короткий (~5)
    assert "Тип" in chars


def test_questions_parse_with_answers():
    qs = parse.parse_questions(_load("questions.json"))
    assert len(qs) >= 1
    q = qs[0]
    assert q["text"] and q["answers"]
    assert "is_best" in q["answers"][0]
    assert "_has_more" in q  # служебный флаг для догрузки ответов присутствует
