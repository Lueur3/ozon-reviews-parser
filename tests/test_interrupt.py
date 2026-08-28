"""Мягкая остановка по Ctrl+C: первый раз просим, второй — прерываем."""
import signal

import pytest

from ozon import interrupt


def test_flag_is_off_outside_the_context():
    assert interrupt.requested() is False


def test_first_interrupt_only_requests_stop(capsys):
    with interrupt.graceful():
        assert interrupt.requested() is False
        signal.getsignal(signal.SIGINT)(signal.SIGINT, None)   # как будто нажали Ctrl+C
        assert interrupt.requested() is True                   # просьба, не исключение
    assert "Останавливаюсь" in capsys.readouterr().out


def test_second_interrupt_raises():
    with interrupt.graceful():
        handler = signal.getsignal(signal.SIGINT)
        handler(signal.SIGINT, None)
        with pytest.raises(KeyboardInterrupt):
            handler(signal.SIGINT, None)


def test_previous_handler_restored():
    before = signal.getsignal(signal.SIGINT)
    with interrupt.graceful():
        assert signal.getsignal(signal.SIGINT) is not before
    assert signal.getsignal(signal.SIGINT) is before
    assert interrupt.requested() is False


def test_flag_resets_between_runs():
    with interrupt.graceful():
        signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
    with interrupt.graceful():
        assert interrupt.requested() is False
