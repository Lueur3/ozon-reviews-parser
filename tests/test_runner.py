"""Оркестрация пакетного запуска: что прекращает список, а что нет."""
import asyncio
import contextlib
from unittest.mock import patch

import pytest

from ozon import runner
from ozon.errors import CaptchaTimeout
from ozon.models import Product, Review


class FakePage:
    async def wait_for_timeout(self, ms):
        pass


@contextlib.asynccontextmanager
async def fake_browser(**kwargs):
    yield None, FakePage()


def _meta(pid="1"):
    return {"product_id": pid, "resolved_url": f"https://ozon.ru/product/x-{pid}/",
            "name": "Товар", "variant": {}, "price": {}, "stats": {},
            "characteristics": {}, "questions": [], "score": 5, "total": 10}


def _run(collect_side_effect, urls, saver=None, saved=None):
    """Гоняет runner с подменённым сбором и сохранением; возвращает список сохранённых id."""
    saved = saved if saved is not None else []
    calls = {"n": 0}

    class FakeCollector:
        def __init__(self, *a, **kw):
            pass

        async def collect(self):
            calls["n"] += 1
            return collect_side_effect(calls["n"])

    def fake_save(product: Product, output_dir):
        if saver:
            saver(product)
        saved.append(product.product_id)
        return f"{output_dir}/{product.product_id}.json"

    with patch.object(runner, "launch_browser", fake_browser), \
         patch.object(runner, "ReviewCollector", FakeCollector), \
         patch.object(runner, "save_product", fake_save):
        runner.run(urls, period_days=365, all_variants=True, headless=True, max_reviews=10)
    return saved, calls["n"]


def _ok(n):
    return [Review(author="a", rating=5, date="2026-01-01", text="t")], _meta(str(n))


def test_all_products_collected_when_healthy():
    saved, calls = _run(_ok, ["u1", "u2", "u3"])
    assert saved == ["1", "2", "3"] and calls == 3


def test_ordinary_failure_skips_only_that_product():
    def side(n):
        if n == 2:
            raise ValueError("Ozon отдал неожиданную структуру")
        return _ok(n)

    saved, calls = _run(side, ["u1", "u2", "u3"])
    assert saved == ["1", "3"]          # второй пропущен, остальные собраны
    assert calls == 3


def test_captcha_aborts_the_whole_batch():
    """Капча не снята — остальные товары ждали бы её по 5 минут каждый."""
    def side(n):
        if n == 2:
            raise CaptchaTimeout("за 5 мин доступ не восстановился")
        return _ok(n)

    with pytest.raises(CaptchaTimeout):
        _run(side, ["u1", "u2", "u3", "u4"])


def test_write_failure_does_not_lose_remaining_products():
    def failing_saver(product):
        if product.product_id == "1":
            raise OSError("нет места на диске")

    saved, calls = _run(_ok, ["u1", "u2"], saver=failing_saver)
    assert saved == ["2"]               # первый не записался, второй — да
    assert calls == 2


def test_remaining_products_skipped_after_interrupt(monkeypatch):
    """Первый Ctrl+C: текущий товар дописывается, остальные не начинаются."""
    from ozon import interrupt

    calls = {"n": 0}

    def side(n):
        calls["n"] = n
        if n == 1:
            monkeypatch.setattr(interrupt, "_requested", True)   # нажали во время сбора
        return _ok(n)

    saved, _ = _run(side, ["u1", "u2", "u3"])
    assert saved == ["1"]          # первый сохранён
    assert calls["n"] == 1         # второй даже не начали
