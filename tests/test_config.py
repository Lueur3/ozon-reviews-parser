"""Настройки: помощник пауз и проверка значений при импорте."""
import pytest

from ozon import config


def test_delay_ms_within_bounds():
    for _ in range(20):
        ms = config.delay_ms((0.15, 0.35))
        assert 150 <= ms <= 350          # секунды -> миллисекунды


def test_delay_ms_fixed_bounds():
    assert config.delay_ms((1.0, 1.0)) == 1000


def test_validate_rejects_reversed_delay(monkeypatch):
    monkeypatch.setattr(config, "PAGE_DELAY", (3.0, 1.0))
    with pytest.raises(ValueError, match="PAGE_DELAY"):
        config._validate()


def test_validate_rejects_nonpositive(monkeypatch):
    monkeypatch.setattr(config, "HEADER_SCROLLS", 0)
    with pytest.raises(ValueError, match="HEADER_SCROLLS"):
        config._validate()


def test_validate_passes_on_shipped_values():
    config._validate()                   # не должно бросать
