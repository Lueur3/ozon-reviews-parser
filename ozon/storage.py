"""Сохранение результата в JSON-файл с именем {product_id}.json."""
import json
import os
from pathlib import Path

from .models import Product


def save_product(product: Product, output_dir: Path) -> Path:
    """Пишет атомарно: сначала во временный файл, затем подменяет целевой.

    Прямая запись оставила бы обрезанный (битый) JSON, если процесс упадёт
    посреди дампа — а перезапись идёт поверх прошлого удачного результата.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{product.product_id}.json"
    tmp = path.with_suffix(".json.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(product.to_dict(), f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)   # атомарная подмена в пределах одной ФС
    finally:
        tmp.unlink(missing_ok=True)
    return path
