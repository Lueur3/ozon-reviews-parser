"""Сохранение результата: атомарность и корректность JSON."""
import json

from ozon.models import Product, Review
from ozon.storage import save_product


def _product():
    return Product(url="https://ozon.ru/product/x-1/", product_id="1", name="Товар",
                   reviews=[Review(author="А", rating=5, date="2026-01-01", text="ок")])


def test_saves_valid_json(tmp_path):
    path = save_product(_product(), tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "1.json"
    assert data["product_id"] == "1"
    assert data["reviews_count"] == 1
    assert data["reviews"][0]["author"] == "А"


def test_no_temp_file_left(tmp_path):
    save_product(_product(), tmp_path)
    assert list(tmp_path.glob("*.tmp")) == []


def test_overwrite_keeps_file_valid(tmp_path):
    save_product(_product(), tmp_path)
    p = _product()
    p.name = "Обновлённый"
    path = save_product(p, tmp_path)
    assert json.loads(path.read_text(encoding="utf-8"))["name"] == "Обновлённый"
    assert list(tmp_path.glob("*.tmp")) == []


def test_creates_missing_output_dir(tmp_path):
    target = tmp_path / "nested" / "out"
    path = save_product(_product(), target)
    assert path.exists()
