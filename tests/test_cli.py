"""Разбор аргументов CLI и перевод сбоев в коды выхода."""
from pathlib import Path

import pytest

from ozon import config
from ozon.cli import guarded, load_urls, main, parse_args
from ozon.errors import BootstrapError


def test_defaults():
    a = parse_args(["https://ozon.ru/t/abc"])
    assert a.url == "https://ozon.ru/t/abc"
    assert a.this_variant is False          # по умолчанию все варианты
    assert a.headless is False              # по умолчанию видимое окно
    assert a.doctor is False
    assert a.fresh_profile is False
    assert a.output_dir == config.OUTPUT_DIR
    assert a.max == config.MAX_REVIEWS_PER_PRODUCT


def test_flags_parsed():
    a = parse_args(["<url>", "--this-variant", "--years", "2", "--max", "50",
                    "--headless", "--fresh-profile", "--output-dir", "out2"])
    assert a.this_variant and a.headless and a.fresh_profile
    assert a.years == 2 and a.max == 50
    assert a.output_dir == Path("out2")


def test_url_and_file_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        parse_args(["<url>", "-f", "urls.txt"])


def test_doctor_needs_explicit_url():
    """Эталонный товар больше не зашит в код — ссылку задаёт пользователь."""
    a = parse_args(["--doctor"])
    assert a.doctor is True and a.url is None      # argparse пропускает
    with pytest.raises(SystemExit) as e:
        main(["--doctor"])                          # а main требует ссылку
    assert "ссылка" in str(e.value)

    a = parse_args(["<url>", "--doctor"])
    assert a.doctor is True and a.url == "<url>"


def test_load_urls_from_file(tmp_path):
    f = tmp_path / "urls.txt"
    f.write_text("# комментарий\nhttps://a\n\n  https://b  \n", encoding="utf-8")
    a = parse_args(["-f", str(f)])
    assert load_urls(a) == ["https://a", "https://b"]


def test_guarded_exit_codes():
    assert guarded(lambda: None) == 0
    assert guarded(lambda: 1) == 1
    assert guarded(lambda: (_ for _ in ()).throw(KeyboardInterrupt())) == 130

    def boom():
        raise BootstrapError("нет заголовков")
    assert guarded(boom) == 1


def test_guarded_lets_unknown_errors_through():
    def boom():
        raise ValueError("неожиданная ошибка")
    with pytest.raises(ValueError):
        guarded(boom)


def test_profile_dir_flag():
    a = parse_args(["<url>", "--profile-dir", "/tmp/ozon_profile"])
    assert a.profile_dir == Path("/tmp/ozon_profile")
    assert parse_args(["<url>"]).profile_dir == config.PROFILE_DIR


def test_doctor_rejects_file_list():
    """--doctor проверяет один товар; со списком это бессмысленно."""
    with pytest.raises(SystemExit) as e:
        main(["--doctor", "-f", "urls.txt"])
    assert "-f" in str(e.value)


def test_article_is_normalized_on_the_way_in():
    a = parse_args(["1234567890"])
    assert load_urls(a) == ["https://www.ozon.ru/product/1234567890/"]
