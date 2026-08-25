"""Клиент внутреннего API Ozon: сборка адресов, фильтр заголовков, поведение fetch."""
import asyncio
import json

import pytest

from ozon import api
from ozon.errors import CaptchaTimeout

URL = "https://www.ozon.ru/product/tovar-1234567890/?from=share"


def test_path_builders():
    assert api.origin_of(URL) == "https://www.ozon.ru"
    assert api.product_path(URL) == "/product/tovar-1234567890/"
    assert api.reviews_path(URL) == "/product/tovar-1234567890/reviews/"
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


# --- разовый сбой против настоящей блокировки ---

class _Recording(FakePage):
    """Считает паузы, чтобы отличить тихий повтор от ожидания капчи."""

    def __init__(self, responses):
        super().__init__(responses)
        self.waits = []

    async def wait_for_timeout(self, ms):
        self.waits.append(ms)


def test_transient_failure_retries_silently(capsys):
    """Одиночный 5xx раньше печатал «реши капчу» и дёргал страницу."""
    page = _Recording([
        {"status": 502, "text": "bad gateway"},
        {"status": 200, "text": json.dumps({"ok": True})},
    ])
    data = asyncio.run(_client(page).fetch("/product/x-1/"))
    assert data == {"ok": True}
    assert page.gotos == 0                       # страницу не перезагружали
    assert "Капча" not in capsys.readouterr().out


def test_network_error_retries_silently(capsys):
    page = _Recording([
        RuntimeError("net::ERR_CONNECTION_RESET"),
        {"status": 200, "text": json.dumps({"ok": True})},
    ])
    assert asyncio.run(_client(page).fetch("/product/x-1/")) == {"ok": True}
    assert page.gotos == 0
    assert "Капча" not in capsys.readouterr().out


def test_block_status_announces_captcha_at_once(capsys):
    """403 — это уже блокировка, тянуть с сообщением незачем."""
    page = _Recording([
        {"status": 403, "text": "<html>captcha</html>"},
        {"status": 200, "text": json.dumps({"ok": True})},
    ])
    assert asyncio.run(_client(page).fetch("/product/x-1/")) == {"ok": True}
    assert page.gotos == 1                       # окно для капчи открыли
    assert "Капча" in capsys.readouterr().out


def test_persistent_transient_failures_eventually_announce(capsys):
    page = _Recording([{"status": 502, "text": "bad"}] * 6)
    with pytest.raises(CaptchaTimeout):
        asyncio.run(_client(page, captcha_iters=6).fetch("/product/x-1/"))
    assert "Капча" in capsys.readouterr().out    # сбои не прекратились — сообщаем
