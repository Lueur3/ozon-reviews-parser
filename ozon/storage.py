"""Сохранение результата в JSON-файл с именем {product_id}.json."""
import json
from pathlib import Path

from .models import Product


def save_product(product: Product, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{product.product_id}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(product.to_dict(), f, ensure_ascii=False, indent=2)
    return path
