"""Разбор ссылок Ozon."""
import re
from urllib.parse import urlparse


def extract_product_id(url: str) -> str | None:
    """Извлекает id товара из ссылки Ozon.

    Поддерживает /product/slug-1234567890/ и /product/1234567890.
    Возвращает None, если id не найден.
    """
    path = urlparse(url).path
    m = re.search(r"/product/([^/?#]+)", path)
    if not m:
        return None
    ids = re.findall(r"\d+", m.group(1))
    return ids[-1] if ids else None
