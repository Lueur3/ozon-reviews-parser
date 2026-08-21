"""Разбор и нормализация пользовательского ввода: ссылка или артикул."""
import re
from urllib.parse import urlparse

from . import api

_ARTICLE_RE = re.compile(r"^\d{5,12}$")     # артикул Ozon — только цифры
_QUOTES = "\"'«»"


def normalize(raw: str) -> str:
    """Приводит ввод к ссылке, по которой можно перейти.

    Поддерживает три способа, которыми пользователь получает товар:
    короткую ссылку «Поделиться» (`ozon.ru/t/...`), полную ссылку карточки
    (с любыми параметрами) и артикул из поиска (`138342427`).
    """
    value = (raw or "").strip().strip(_QUOTES).strip()
    if not value:
        raise ValueError("пустая ссылка")
    if _ARTICLE_RE.match(value):
        # короткий путь Ozon сам разворачивает в полную карточку товара
        return f"{api.BASE_URL}/product/{value}/"
    if "://" not in value:
        return "https://" + value.lstrip("/")   # ozon.ru/t/xxx без схемы
    return value


def extract_product_id(url: str) -> str | None:
    """Извлекает id товара из ссылки Ozon.

    Поддерживает /product/slug-1234567890/ и /product/1234567890.
    Возвращает None, если id не найден (например, у короткой ссылки
    ozon.ru/t/... — её id известен только после перехода).
    """
    path = urlparse(url).path
    m = re.search(r"/product/([^/?#]+)", path)
    if not m:
        return None
    ids = re.findall(r"\d+", m.group(1))
    return ids[-1] if ids else None
