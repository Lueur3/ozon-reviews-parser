"""Обезличивание выгрузки перед передачей файла наружу."""
from ozon.anonymize import anonymize
from ozon.models import Product, Review


def _product():
    return Product(
        url="https://www.ozon.ru/product/tovar-1234567890/",
        product_id="1234567890",
        name="Название товара",
        variant={"Цвет": "чёрный"},
        price={"price": "100 ₽"},
        stats={"overall": {"avg": 4.8}},
        characteristics={"Тип": "X"},
        questions=[{
            "author": "Пётр П.",
            "text": "Вопрос?",
            "date": "1 мая 2026",
            "answers": [
                {"author": "Магазин", "text": "Ответ.", "date": "2 мая 2026", "is_best": True},
                {"author": "Анна К.", "text": "И моё мнение.", "date": "3 мая 2026", "is_best": False},
            ],
        }],
        reviews_period_days=365,
        reviews=[
            Review(author="Анна К.", rating=5, date="2026-05-01", text="отлично",
                   pros="плюс", cons="минус", useful_count=3, unuseful_count=1,
                   purchased=True, photos=["https://cdn/1.jpg"], videos=["https://cdn/2.mp4"],
                   variant={"Цвет": "чёрный"}),
            Review(author="Пётр П.", rating=2, date="2026-04-01", text="плохо"),
            Review(author="Анна К.", rating=4, date="2026-03-01", text="норм"),
        ],
    )


def test_names_replaced_with_placeholders():
    out = anonymize(_product())
    assert [r.author for r in out.reviews] == ["Автор 1", "Автор 2", "Автор 1"]


def test_same_person_gets_same_alias_across_sections():
    """Анна К. пишет отзывы и отвечает на вопрос — псевдоним должен совпадать."""
    out = anonymize(_product())
    anna = out.reviews[0].author
    assert out.questions[0]["answers"][1]["author"] == anna


def test_user_media_dropped():
    out = anonymize(_product())
    assert all(r.photos == [] and r.videos == [] for r in out.reviews)


def test_product_data_and_review_content_survive():
    src, out = _product(), anonymize(_product())
    assert (out.product_id, out.name, out.price, out.characteristics, out.stats) == \
           (src.product_id, src.name, src.price, src.characteristics, src.stats)
    assert [r.rating for r in out.reviews] == [5, 2, 4]
    assert [r.text for r in out.reviews] == ["отлично", "плохо", "норм"]
    assert out.reviews[0].pros == "плюс" and out.reviews[0].cons == "минус"
    assert (out.reviews[0].useful_count, out.reviews[0].purchased) == (3, True)
    assert out.questions[0]["text"] == "Вопрос?"
    assert out.questions[0]["answers"][0]["text"] == "Ответ."
    assert out.questions[0]["answers"][0]["is_best"] is True


def test_source_product_not_modified():
    src = _product()
    anonymize(src)
    assert src.reviews[0].author == "Анна К."
    assert src.reviews[0].photos == ["https://cdn/1.jpg"]
    assert src.questions[0]["author"] == "Пётр П."


def test_no_personal_names_left_in_output():
    out = anonymize(_product())
    dumped = str(out.to_dict())
    for name in ("Анна К.", "Пётр П.", "Магазин", "cdn/1.jpg"):
        assert name not in dumped
