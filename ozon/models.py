"""Модели данных: товар и отзыв."""
from dataclasses import dataclass, field, asdict


@dataclass
class Review:
    author: str
    rating: int          # 1..5
    date: str            # ISO: YYYY-MM-DD
    text: str = ""
    pros: str = ""       # достоинства
    cons: str = ""       # недостатки
    useful_count: int = 0
    variant: dict = field(default_factory=dict)  # {"Цвет": "чёрный", ...}


@dataclass
class Product:
    url: str
    product_id: str
    name: str = ""
    variant: dict = field(default_factory=dict)          # вариант целевого товара
    characteristics: dict = field(default_factory=dict)
    reviews_period_days: int = 0
    reviews: list[Review] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "product_id": self.product_id,
            "name": self.name,
            "variant": self.variant,
            "characteristics": self.characteristics,
            "reviews_period_days": self.reviews_period_days,
            "reviews_count": len(self.reviews),
            "reviews": [asdict(r) for r in self.reviews],
        }
