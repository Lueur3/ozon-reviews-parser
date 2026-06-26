"""Парсинг JSON-ответов Ozon. Фикстуры повторяют реальную форму widgetStates."""
import json

from ozon import parse


# --- _widget_states: значения бывают строкой (JSON) или dict ---

def test_widget_states_decodes_string_and_keeps_dict():
    data = {"widgetStates": {
        "asString": json.dumps({"a": 1}),
        "asDict": {"b": 2},
        "broken": "{not json",
    }}
    ws = parse._widget_states(data)
    assert ws["asString"] == {"a": 1}
    assert ws["asDict"] == {"b": 2}
    assert "broken" not in ws  # битый JSON пропускается


# --- parse_price ---

def test_parse_price_picks_webprice_and_drops_decoy():
    data = {"widgetStates": {
        "webPriceDecreasedCompact-1-default-1": {"price": "999 ₽"},  # decoy, не webPrice-
        "webPrice-3121879-default-1": {
            "price": "1 244 ₽", "cardPrice": "1 140 ₽",
            "isAvailable": True, "showOriginalPrice": True, "originalPrice": "4 082 ₽",
        },
    }}
    assert parse.parse_price(data) == {
        "price": "1 244 ₽", "card_price": "1 140 ₽",
        "is_available": True, "original_price": "4 082 ₽",
    }


def test_parse_price_omits_original_when_flag_off():
    data = {"widgetStates": {"webPrice-1-default-1": {
        "price": "100 ₽", "cardPrice": "90 ₽", "isAvailable": True,
        "showOriginalPrice": False, "originalPrice": "200 ₽",
    }}}
    out = parse.parse_price(data)
    assert "original_price" not in out
    assert out["price"] == "100 ₽"


def test_parse_price_empty_when_no_price_fields():
    data = {"widgetStates": {"webPrice-1-default-1": {"isAvailable": True}}}
    assert parse.parse_price(data) == {}


# --- parse_characteristics ---

def _char_widget(items):
    return {"characteristics": [{"short": [
        {"name": n, "values": [{"text": v}]} for n, v in items
    ]}]}


def test_parse_characteristics_picks_widest():
    data = {"widgetStates": {
        "webCharacteristics-1-default-1": _char_widget([("Тип", "Телефон")]),
        "webCharacteristics-2-default-1": _char_widget(
            [("Тип", "Телефон"), ("Бренд", "BQ"), ("Цвет", "чёрный")]),
    }}
    chars = parse.parse_characteristics(data)
    assert len(chars) == 3
    assert chars["Бренд"] == "BQ"


def test_parse_characteristics_fallback_to_short():
    data = {"widgetStates": {"webShortCharacteristics-1-default-1": {"characteristics": [
        {"title": {"textRs": [{"type": "text", "content": "Бренд"}]},
         "values": [{"text": "BQ"}]},
    ]}}}
    assert parse.parse_characteristics(data) == {"Бренд": "BQ"}


# --- parse_questions ---

def _questions_data():
    return {"widgetStates": {"webListQuestions-1-default-1": {
        "questions": {
            "100": {"author": {"name": "Андрей"}, "content": "Вопрос?",
                    "createdAt": "7 мая 2026", "getAnswersAction": {"x": 1}},
            "200": {"author": {"name": "Тихий"}, "content": "Без ответа?",
                    "createdAt": "1 мая 2026"},
        },
        "answers": {
            "900": {"author": {"name": "OZON"}, "content": "Ответ.",
                    "createdAt": "7 мая 2026", "isTheBest": True},
            "901": {"author": {"name": "P&G"}, "content": "Ещё ответ.",
                    "createdAt": "8 мая 2026", "isTheBest": False},
        },
        "questionAnswers": {"100": ["900", "901"]},
        "questionsIds": [100, 200],
    }}}


def test_parse_questions_answered_only():
    out = parse.parse_questions(_questions_data(), answered_only=True)
    assert len(out) == 1
    q = out[0]
    assert q["text"] == "Вопрос?"
    assert q["_id"] == "100"
    assert q["_has_more"] is True  # есть getAnswersAction
    assert [a["author"] for a in q["answers"]] == ["OZON", "P&G"]
    assert q["answers"][0]["is_best"] is True


def test_parse_questions_includes_unanswered_when_flag_off():
    out = parse.parse_questions(_questions_data(), answered_only=False)
    texts = {q["text"] for q in out}
    assert texts == {"Вопрос?", "Без ответа?"}
    unanswered = next(q for q in out if q["text"] == "Без ответа?")
    assert unanswered["answers"] == []
    assert unanswered["_has_more"] is False


# --- variant_map / ts_to_date / _media_urls ---

def test_variant_map_handles_int_item_id():
    products = {"1": {"variants": [{"name": "Цвет", "value": "чёрный"}]}}
    assert parse.variant_map(1, products) == {"Цвет": "чёрный"}
    assert parse.variant_map(999, products) == {}


def test_ts_to_date_moscow():
    assert parse.ts_to_date(1781631970) == "2026-06-16"  # реальная дата из захвата
    assert parse.ts_to_date(0) == "1970-01-01"
    assert parse.ts_to_date(None) == "1970-01-01"


def test_media_urls_variants():
    items = [{"url": "a"}, {"previewUrl": "b"}, {"image": "c"}, "d", {"nope": 1}]
    assert parse._media_urls(items) == ["a", "b", "c", "d"]
    assert parse._media_urls(None) == []


# --- to_review ---

def _raw(**over):
    raw = {
        "uuid": "u1", "itemId": 1,
        "publishedAt": 1781631970, "createdAt": 1781631970,
        "isItemPurchased": True,
        "author": {"firstName": "Денис", "lastName": "Б."},
        "usefulness": {"useful": 3, "unuseful": 1},
        "content": {"comment": "текст", "positive": "плюс", "negative": "минус",
                    "photos": [{"url": "http://p1"}], "videos": [{"url": "http://v1"}],
                    "score": 5},
    }
    raw.update(over)
    return raw


def test_to_review_full():
    products = {"1": {"variants": [{"name": "Цвет", "value": "чёрный"}]}}
    r = parse.to_review(_raw(), products)
    assert r.author == "Денис Б."
    assert r.rating == 5
    assert r.date == "2026-06-16"
    assert (r.text, r.pros, r.cons) == ("текст", "плюс", "минус")
    assert (r.useful_count, r.unuseful_count) == (3, 1)
    assert r.purchased is True
    assert r.photos == ["http://p1"]
    assert r.videos == ["http://v1"]
    assert r.variant == {"Цвет": "чёрный"}


def test_to_review_anonymous_author():
    r = parse.to_review(_raw(author={"firstName": "", "lastName": ""}), {})
    assert r.author == "Аноним"
