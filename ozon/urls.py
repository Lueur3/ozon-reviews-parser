"""Разбор и нормализация пользовательского ввода: ссылка или артикул."""
import re
from urllib.parse import urlparse

from . import api, config

_ARTICLE_RE = re.compile(r"^\d{5,12}$")     # артикул Ozon — только цифры
_QUOTES = "\"'«»"


def normalize(raw: str) -> str:
    """Приводит ввод к ссылке, по которой можно перейти.

    Поддерживает три способа, которыми пользователь получает товар:
    короткую ссылку «Поделиться» (`ozon.ru/t/...`), полную ссылку карточки
    (с любыми параметрами) и артикул из поиска (`1234567890`).
    """
    value = (raw or "").strip().strip(_QUOTES).strip()
    if not value:
        raise ValueError("пустая ссылка")
    if _ARTICLE_RE.match(value):
        # короткий путь Ozon сам разворачивает в полную карточку товара
        return f"{api.BASE_URL}/product/{value}/"
    if "://" not in value:
        value = "https://" + value.lstrip("/")   # ozon.ru/t/xxx без схемы
    return _checked(value)


def _checked(url: str) -> str:
    """Пропускает только http(s) на домен Ozon.

    Ввод может прийти из чужого файла со списком: без этой проверки `page.goto`
    открыл бы в настоящем браузере пользователя локальный файл (`file://`),
    адрес внутренней сети или сервис метаданных облака.
    """
    pr = urlparse(url)
    if pr.scheme not in config.ALLOWED_SCHEMES:
        raise ValueError(f"поддерживаются только http/https, получено: {url}")
    host = (pr.hostname or "").lower()
    suffix = config.ALLOWED_HOST_SUFFIX
    if not (host == suffix or host.endswith("." + suffix)):
        raise ValueError(f"ожидалась ссылка на {suffix}, получено: {url}")
    return url


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
