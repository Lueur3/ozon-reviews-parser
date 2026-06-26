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
    unuseful_count: int = 0
    purchased: bool = False        # куплен ли товар на Ozon (isItemPurchased)
    photos: list = field(default_factory=list)   # ссылки на фото
    videos: list = field(default_factory=list)   # ссылки на видео
    variant: dict = field(default_factory=dict)  # {"Цвет": "чёрный", ...}


@dataclass
class Product:
    url: str
    product_id: str
    name: str = ""
    variant: dict = field(default_factory=dict)          # вариант целевого товара
    price: dict = field(default_factory=dict)            # {price, card_price, original_price, ...}
    characteristics: dict = field(default_factory=dict)
    questions: list = field(default_factory=list)        # вопросы с ответами
    reviews_period_days: int = 0
    reviews: list[Review] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "product_id": self.product_id,
            "name": self.name,
            "variant": self.variant,
            "price": self.price,
            "characteristics": self.characteristics,
            "questions_count": len(self.questions),
            "questions": self.questions,
            "reviews_period_days": self.reviews_period_days,
            "reviews_count": len(self.reviews),
            "reviews": [asdict(r) for r in self.reviews],
        }
