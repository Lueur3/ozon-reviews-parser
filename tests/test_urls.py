"""Ввод пользователя: короткая ссылка, полная ссылка, артикул."""
import pytest

from ozon.urls import extract_product_id, normalize

# Синтетические значения: тесты не должны ссылаться на реальную карточку Ozon.
ARTICLE = "1234567890"
SHORT = "https://ozon.ru/t/AbCdEfG"
FULL = (f"https://www.ozon.ru/product/tovar-{ARTICLE}/"
        "?from=share_web&sh=XxYyZz&__rr=1")


# --- normalize: три способа задать товар ---

def test_article_becomes_product_url():
    assert normalize(ARTICLE) == f"https://www.ozon.ru/product/{ARTICLE}/"


@pytest.mark.parametrize("raw", [f" {ARTICLE} ", f'"{ARTICLE}"', f"'{ARTICLE}'"])
def test_article_tolerates_spaces_and_quotes(raw):
    assert normalize(raw) == f"https://www.ozon.ru/product/{ARTICLE}/"


def test_links_pass_through_unchanged():
    assert normalize(SHORT) == SHORT
    assert normalize(FULL) == FULL          # параметры не режем: они нужны Ozon


@pytest.mark.parametrize("raw, expected", [
    ("ozon.ru/t/abc", "https://ozon.ru/t/abc"),
    ("www.ozon.ru/product/x-1/", "https://www.ozon.ru/product/x-1/"),
])
def test_scheme_added_when_missing(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_empty_input_rejected(raw):
    with pytest.raises(ValueError):
        normalize(raw)


def test_short_number_is_not_an_article():
    """Слишком короткое число — не артикул; трактуем как ссылку, а не как товар."""
    assert normalize("123").startswith("https://123")


# --- extract_product_id ---

@pytest.mark.parametrize("url, expected", [
    (FULL, ARTICLE),
    (f"https://www.ozon.ru/product/{ARTICLE}", ARTICLE),
    (f"https://www.ozon.ru/product/bq-2842-disco-{ARTICLE}/reviews/", ARTICLE),
    (normalize(ARTICLE), ARTICLE),          # ссылка, собранная из артикула
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


def test_short_link_id_known_only_after_redirect():
    """У короткой ссылки id нет — его берут из page.url после перехода."""
    assert extract_product_id(SHORT) is None
