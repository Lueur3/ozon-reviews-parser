"""Извлечение id товара из ссылок Ozon."""
import pytest

from ozon.urls import extract_product_id


@pytest.mark.parametrize("url, expected", [
    ("https://www.ozon.ru/product/telefon-bq-2842-2608237202/", "2608237202"),
    ("https://www.ozon.ru/product/2608237202", "2608237202"),
    ("https://www.ozon.ru/product/telefon-bq-2842-2608237202/?at=abc", "2608237202"),
    # id всегда последний числовой блок, даже если в slug есть цифры
    ("https://www.ozon.ru/product/bq-2842-disco-2608237202/reviews/", "2608237202"),
])
def test_extract_product_id_ok(url, expected):
    assert extract_product_id(url) == expected


@pytest.mark.parametrize("url", [
    "https://www.ozon.ru/category/telefony/",
    "https://www.ozon.ru/product/slug-without-digits/",
    "not a url",
])
def test_extract_product_id_none(url):
    assert extract_product_id(url) is None
