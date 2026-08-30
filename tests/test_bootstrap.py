"""Подготовка сессии: без заголовков API сбор обязан падать с понятной ошибкой.

Раньше здесь стоял молчаливый фолбэк `headers or {}`, из-за которого парсер шёл
дальше и возвращал пустой результат. Проверяем на минимальной подделке страницы
(asyncio.run вместо pytest-asyncio — лишняя зависимость не нужна).
"""
import asyncio

import pytest

from ozon.collector import ReviewCollector
from ozon.errors import BootstrapError

URL = "https://www.ozon.ru/product/tovar-1234567890/"


class _Mouse:
    async def wheel(self, dx, dy):
        pass


class FakePage:
    """Минимальная замена Playwright-страницы: только то, что вызывает _bootstrap."""

    def __init__(self, url=URL):
        self.url = url
        self.mouse = _Mouse()

    def on(self, event, cb):
        pass

    def remove_listener(self, event, cb):
        pass

    async def goto(self, url, **kwargs):
        pass

    async def wait_for_timeout(self, ms):
        pass


def _collector(page):
    return ReviewCollector(page, URL, period_days=365, all_variants=True,
                           max_reviews=10, page_delay=(0, 0))


def test_bootstrap_fails_without_api_headers():
    c = _collector(FakePage())
    with pytest.raises(BootstrapError) as e:
        asyncio.run(c._bootstrap())
    assert "заголовки" in str(e.value)
    assert URL in str(e.value)


def test_bootstrap_sets_paths_when_headers_captured():
    c = _collector(FakePage())
    c.headers = {"x-o3-app-name": "dweb_client"}   # как будто перехватили из сессии
    asyncio.run(c._bootstrap())
    assert c.product_id == "1234567890"
    assert c.origin == "https://www.ozon.ru"
    assert c.ppath == "/product/tovar-1234567890/"
    assert c.rpath == "/product/tovar-1234567890/reviews/"


def test_bootstrap_stops_when_the_page_is_not_a_product_card():
    """Снятый с продажи товар и несуществующий артикул одинаково уводят на /search/.

    Раньше сбор шёл дальше по несуществующим путям, получал 403 и пять минут ждал
    капчу, которой нет. Теперь падает до создания клиента, то есть до первого запроса.
    """
    search = ("https://www.ozon.ru/search/?deny_category_prediction=true"
              "&from_global=true&text=&product_id=175082")
    c = _collector(FakePage(url=search))
    c.headers = {"x-o3-app-name": "dweb_client"}   # заголовки есть, но карточки нет
    with pytest.raises(BootstrapError) as e:
        asyncio.run(c._bootstrap())
    assert "карточка товара не открылась" in str(e.value)
    assert search in str(e.value)
    assert c.client is None, "клиент создан — значит запросы всё-таки полетят"
