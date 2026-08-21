"""Капча обрывает сбор целиком, а не роняет секции по очереди.

Раньше CaptchaTimeout ловился каждым `except Exception` в collector: сбор шёл
к следующему запросу и ждал капчу ещё 5 минут — до полутора часов впустую на
уже мёртвой сессии. Теперь исключение проходит наружу.
"""
import asyncio

import pytest

from ozon import config
from ozon.collector import ReviewCollector
from ozon.errors import CaptchaTimeout

URL = "https://www.ozon.ru/product/tovar-1/"


class DeadSessionClient:
    """Клиент, у которого капча уже не снимается: считает попытки."""

    def __init__(self):
        self.calls = 0
        self.headers = {"h": "1"}

    async def fetch(self, param):
        self.calls += 1
        raise CaptchaTimeout("за 5 мин доступ не восстановился (последняя причина: HTTP 403)")


def _collector():
    c = ReviewCollector(page=None, url=URL, period_days=365, all_variants=True,
                        max_reviews=10, page_delay=(0, 0))
    c.client = DeadSessionClient()
    c.ppath, c.rpath = "/product/tovar-1/", "/product/tovar-1/reviews/"
    return c


def test_extras_do_not_swallow_captcha():
    c = _collector()
    with pytest.raises(CaptchaTimeout):
        asyncio.run(c._collect_extras())
    assert c.client.calls == 1          # не пошёл за features/ после провала


def test_questions_do_not_swallow_captcha():
    c = _collector()
    with pytest.raises(CaptchaTimeout):
        asyncio.run(c._collect_questions())
    assert c.client.calls == 1          # не перебрал все 12 страниц


def test_cursor_does_not_swallow_captcha():
    c = _collector()
    with pytest.raises(CaptchaTimeout):
        asyncio.run(c._run_cursor("/product/tovar-1/reviews/?sort=x", "reviews", True))
    assert c.client.calls == 1


def test_other_errors_are_still_tolerated():
    """Обычный сбой секции по-прежнему не валит весь сбор."""
    class Flaky:
        headers = {"h": "1"}

        async def fetch(self, param):
            raise ValueError("Ozon вернул неожиданную структуру")

    c = _collector()
    c.client = Flaky()
    price, chars = asyncio.run(c._collect_extras())
    assert price == {} and chars == {}          # секция пустая, исключения наружу нет
    assert asyncio.run(c._collect_questions()) == []
