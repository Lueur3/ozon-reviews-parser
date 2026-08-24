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
    """Слишком короткое число — не артикул; и как хост оно тоже не проходит."""
    with pytest.raises(ValueError):
        normalize("123")


# --- ограничение схемы и хоста ---

@pytest.mark.parametrize("raw", [
    "file:///C:/Windows/win.ini",       # локальный файл
    "ftp://ozon.ru/x",                  # чужая схема
    "http://127.0.0.1:8000/admin",      # локальная сеть
    "http://169.254.169.254/latest/",   # метаданные облака
    "https://evil.com/ozon.ru",         # домен в пути, а не в хосте
    "https://ozon.ru.evil.com/x",       # хост лишь начинается с ozon.ru
])
def test_foreign_targets_rejected(raw):
    with pytest.raises(ValueError):
        normalize(raw)


@pytest.mark.parametrize("raw", [
    "https://ozon.ru/t/AbCdEfG",
    "https://www.ozon.ru/product/tovar-1234567890/",
    "http://ozon.ru/t/AbCdEfG",
])
def test_ozon_targets_allowed(raw):
    assert normalize(raw) == raw


# --- extract_product_id ---

@pytest.mark.parametrize("url, expected", [
    (FULL, ARTICLE),
    (f"https://www.ozon.ru/product/{ARTICLE}", ARTICLE),
    (f"https://www.ozon.ru/product/tovar-so-slugom-{ARTICLE}/reviews/", ARTICLE),
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
