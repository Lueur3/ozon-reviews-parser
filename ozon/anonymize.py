"""Обезличивание выгрузки: убрать персональные данные третьих лиц.

Отзывы и вопросы пишут живые люди. Для оценки товара их имена и фотографии не
нужны, а вот при передаче файла наружу (в облачную модель, коллеге, в репозиторий)
они превращаются в обработку чужих персональных данных. Флаг `--anonymize`
оставляет только то, что относится к товару.

Компромисс режима: авторы ответов тоже обезличиваются, поэтому различие
«ответил магазин / ответил покупатель» теряется. Если оно нужно для анализа —
собирайте без флага.
"""
from .models import Product, Review

PLACEHOLDER = "Автор {n}"


class _Names:
    """Выдаёт устойчивые псевдонимы: одно и то же имя — один и тот же «Автор N»."""

    def __init__(self):
        self._seen: dict[str, str] = {}

    def alias(self, name: str) -> str:
        real = (name or "").strip()
        if not real:
            return ""
        if real not in self._seen:
            self._seen[real] = PLACEHOLDER.format(n=len(self._seen) + 1)
        return self._seen[real]


def anonymize(product: Product) -> Product:
    """Возвращает копию товара без имён авторов и без пользовательских медиа."""
    names = _Names()

    reviews = [
        Review(
            author=names.alias(r.author),
            rating=r.rating,
            date=r.date,
            text=r.text,
            pros=r.pros,
            cons=r.cons,
            useful_count=r.useful_count,
            unuseful_count=r.unuseful_count,
            purchased=r.purchased,
            photos=[],        # снимки покупателей — их личный контент
            videos=[],
            variant=r.variant,
        )
        for r in product.reviews
    ]

    questions = [
        {
            **q,
            "author": names.alias(q.get("author", "")),
            "answers": [{**a, "author": names.alias(a.get("author", ""))}
                        for a in q.get("answers", [])],
        }
        for q in product.questions
    ]

    return Product(
        url=product.url,
        product_id=product.product_id,
        name=product.name,
        variant=product.variant,
        price=product.price,
        stats=product.stats,
        characteristics=product.characteristics,
        questions=questions,
        reviews_period_days=product.reviews_period_days,
        reviews=reviews,
    )
