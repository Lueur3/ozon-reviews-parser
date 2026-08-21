"""Клиент внутреннего API Ozon: сборка адресов, фильтр заголовков, поведение fetch."""
import asyncio
import json

import pytest

from ozon import api
from ozon.errors import CaptchaTimeout

URL = "https://www.ozon.ru/product/tovar-138342427/?from=share"


def test_path_builders():
    assert api.origin_of(URL) == "https://www.ozon.ru"
    assert api.product_path(URL) == "/product/tovar-138342427/"
    assert api.reviews_path(URL) == "/product/tovar-138342427/reviews/"
    assert api.features_path("/product/x-1/") == "/product/x-1/features/"
    assert api.question_page("/product/x-1/", 42) == "/product/x-1/question/42/"


def test_product_path_adds_trailing_slash():
    assert api.product_path("https://www.ozon.ru/product/x-1") == "/product/x-1/"


def test_feed_and_questions_params():
    feed = api.reviews_feed("/product/x-1/reviews/", api.SORT_SCORE_ASC)
    assert feed == "/product/x-1/reviews/?sort=score_asc&reviewsVariantMode=2"
    assert api.questions_page("/product/x-1/", 3) == \
        "/product/x-1/questions/?qsort=has_answers_desc&page=3"


def test_session_headers_drops_service_and_pseudo():
    raw = {"x-o3-app-name": "dweb_client", "Cookie": "secret", "host": "www.ozon.ru",
           ":authority": "www.ozon.ru", "Accept": "application/json"}
    assert api.session_headers(raw) == {"x-o3-app-name": "dweb_client",
                                        "Accept": "application/json"}


class FakePage:
    """Подделка страницы: отдаёт заранее заданные ответы на page.evaluate."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.gotos = 0

    async def evaluate(self, script, arg):
        self.calls.append(arg["u"])
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    async def wait_for_timeout(self, ms):
        pass

    async def goto(self, url, **kwargs):
        self.gotos += 1


def _client(page, **kw):
    return api.OzonClient(page, "https://www.ozon.ru", {"h": "1"},
                          recovery_url=URL, poll_ms=0, **kw)


def test_fetch_returns_parsed_json():
    page = FakePage([{"status": 200, "text": json.dumps({"widgetStates": {"a": "1"}})}])
    data = asyncio.run(_client(page).fetch("/product/x-1/"))
    assert data == {"widgetStates": {"a": "1"}}
    assert page.calls[0].startswith("https://www.ozon.ru" + api.API_PATH)


def test_fetch_retries_after_block_then_succeeds():
    page = FakePage([
        {"status": 403, "text": "<html>captcha</html>"},        # блок
        {"status": 200, "text": json.dumps({"ok": True})},      # пользователь решил капчу
    ])
    data = asyncio.run(_client(page).fetch("/product/x-1/"))
    assert data == {"ok": True}
    assert page.gotos == 1     # окно с капчей было открыто один раз


def test_fetch_gives_up_with_reason():
    page = FakePage([{"status": 403, "text": "blocked"}] * 3)
    with pytest.raises(CaptchaTimeout) as e:
        asyncio.run(_client(page, captcha_iters=3).fetch("/product/x-1/"))
    assert "403" in str(e.value)      # причина названа, а не «неизвестно»
