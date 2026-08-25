"""Парсинг JSON-ответов Ozon (entrypoint-api page json v2).

Поля читаются защитно (`.get()`), потому что Ozon меняет состав ответа без
предупреждения: строгая схема роняла бы сбор на каждом новом поле. Отсутствие
ожидаемых данных ловится уровнем выше — самопроверкой `--doctor`.
"""
import json
from datetime import datetime, timedelta

from dateutil import tz

from . import api, config
from .logging_setup import get_logger
from .models import Review

log = get_logger("ozon.parse")

_TZ = tz.gettz(config.TIMEZONE) or tz.UTC


def widget_states(data: dict) -> dict:
    out = {}
    for k, v in (data.get("widgetStates") or {}).items():
        if isinstance(v, str):
            try:
                out[k] = json.loads(v)
            except json.JSONDecodeError as e:
                log.debug("виджет %s: значение не JSON (%s)", k, e)
                continue
        elif isinstance(v, dict):
            out[k] = v
    return out


def extract_reviews_widget(data: dict):
    """Из webListReviews возвращает (reviews_raw, products, score, total) или None."""
    for k, w in widget_states(data).items():
        if k.startswith(api.WIDGET_REVIEWS) and isinstance(w, dict) and "reviews" in w:
            return (
                w.get("reviews") or [],
                w.get("products") or {},
                w.get("productScore"),
                (w.get("paging") or {}).get("total"),
            )
    return None


def _find_widget(data: dict, prefix: str):
    for k, w in widget_states(data).items():
        if k.startswith(prefix):
            return w
    return None


def parse_price(data: dict) -> dict:
    """Из виджета webPrice-<id> (не webPriceDecreasedCompact и подобных)."""
    for k, w in widget_states(data).items():
        if not (k.startswith(api.WIDGET_PRICE) and isinstance(w, dict)):
            continue
        if not (w.get("price") or w.get("cardPrice")):
            continue
        out = {
            "price": w.get("price"),
            "card_price": w.get("cardPrice"),
            "is_available": w.get("isAvailable"),
        }
        if w.get("showOriginalPrice"):
            out["original_price"] = w.get("originalPrice")
        return {kk: vv for kk, vv in out.items() if vv is not None}
    return {}


def _chars_from_webchar(w) -> dict:
    out = {}
    if isinstance(w, dict):
        for group in w.get("characteristics", []):
            for item in (group.get("short") or []) + (group.get("long") or []):
                name = (item.get("name") or "").strip()
                values = [v.get("text", "") for v in (item.get("values") or []) if v.get("text")]
                if name and values:
                    out[name] = ", ".join(values)
    return out


def parse_characteristics(data: dict) -> dict:
    """{название: значение}. На /features/ несколько webCharacteristics — берём самый полный."""
    best = {}
    for k, w in widget_states(data).items():
        if k.startswith(api.WIDGET_CHARACTERISTICS):
            c = _chars_from_webchar(w)
            if len(c) > len(best):
                best = c
    if best:
        return best
    # откат: webShortCharacteristics (вложенная структура карточки)
    w = _find_widget(data, api.WIDGET_SHORT_CHARACTERISTICS)
    if isinstance(w, dict):
        for ch in w.get("characteristics", []):
            title = ch.get("title") or {}
            name = "".join(t.get("content", "") for t in title.get("textRs", [])
                           if t.get("type") == "text").strip()
            values = [v.get("text", "") for v in (ch.get("values") or []) if v.get("text")]
            if name and values:
                best[name] = ", ".join(values)
    return best


def question_widget(data: dict):
    """Виджет вопросов в любой из разметок Ozon (см. parse_questions)."""
    for k, w in widget_states(data).items():
        if not isinstance(w, dict):
            continue
        if k.startswith(api.WIDGET_QUESTIONS_PDP) or k.startswith(api.WIDGET_QUESTIONS):
            return w
    st = data.get("state")
    if isinstance(st, str):
        try:
            st = json.loads(st)
        except json.JSONDecodeError as e:
            log.debug("state вопросов не разобран: %s", e)
            st = None
    if isinstance(st, dict) and "questions" in st:
        return st
    return None


def next_page(data: dict) -> str | None:
    """Курсор следующей страницы.

    У ленты отзывов он лежит в корне ответа, а у новой ленты вопросов — в отдельном
    виджете `paginator-*` (внутри base64-ключ с uuid последнего показанного вопроса).
    """
    top = data.get("nextPage")
    if top:
        return top
    for k, w in widget_states(data).items():
        if k.startswith(api.WIDGET_PAGINATOR) and isinstance(w, dict) and w.get("nextPage"):
            return w["nextPage"]
    return None


def _text(node) -> str:
    """Поле Ozon: раньше строка, в новой разметке объект {"text": ..., "textColor": ...}."""
    if isinstance(node, dict):
        return node.get("text", "") or ""
    return node or ""


def _questions_pdp(w: dict, answered_only: bool) -> list:
    """Разметка webPDPListQuestions: questions — список, ответы вложены в вопрос."""
    out = []
    for q in w.get("questions") or []:
        if not isinstance(q, dict):
            continue
        answers = [
            {
                "author": _text(((a.get("author") or {}).get("name"))),
                "text": _text(a.get("text")),
                "date": _text(a.get("createdAt")),
                # признака «лучший ответ» в этой разметке нет
                "is_best": False,
            }
            for a in (q.get("answers") or []) if isinstance(a, dict)
        ]
        if answered_only and not answers:
            continue
        out.append({
            "_id": q.get("questionUuid") or "",
            "_has_more": False,     # отдельной догрузки ответов здесь не предусмотрено
            "author": _text(((q.get("author") or {}).get("name"))),
            "text": _text(q.get("text")),
            "date": _text(q.get("createdAt")),
            "answers": answers,
        })
    return out


def _questions_legacy(w: dict, answered_only: bool) -> list:
    """Разметка webListQuestions: questions/answers раздельно, связь через questionAnswers."""
    questions = w.get("questions") or {}
    answers = w.get("answers") or {}
    qa = w.get("questionAnswers") or {}
    order = w.get("questionsIds") or list(questions.keys())
    out = []
    for qid in order:
        q = questions.get(str(qid)) or questions.get(qid)
        if not isinstance(q, dict):
            continue
        ans = []
        for aid in (qa.get(str(qid)) or qa.get(qid) or []):
            a = answers.get(str(aid)) or answers.get(aid)
            if not isinstance(a, dict):
                continue
            ans.append({
                "author": (a.get("author") or {}).get("name", ""),
                "text": a.get("content", "") or "",
                "date": a.get("createdAt", "") or "",
                "is_best": bool(a.get("isTheBest")),
            })
        if answered_only and not ans:
            continue
        out.append({
            "_id": str(qid),
            "_has_more": bool(q.get("getAnswersAction")),
            "author": (q.get("author") or {}).get("name", ""),
            "text": q.get("content", "") or "",
            "date": q.get("createdAt", "") or "",
            "answers": ans,
        })
    return out


def parse_questions(data: dict, answered_only: bool = True) -> list:
    """Вопросы с ответами: [{author, text, date, answers:[{author,text,date,is_best}]}].

    Ozon держит две разметки Q&A: прежнюю (`webListQuestions`, словари и карта
    `questionAnswers`) и новую (`webPDPListQuestions`, список вопросов с вложенными
    ответами и полями-объектами). Различаем по форме `questions`, чтобы сбор
    работал на обеих.
    """
    w = question_widget(data)
    if not w:
        return []
    if isinstance(w.get("questions"), list):
        return _questions_pdp(w, answered_only)
    return _questions_legacy(w, answered_only)


def variant_map(item_id, products: dict) -> dict:
    p = products.get(str(item_id)) or {}
    return {v.get("name", ""): v.get("value", "") for v in (p.get("variants") or [])}


def ts_to_date(ts) -> str:
    return datetime.fromtimestamp(int(ts or 0), tz=_TZ).date().isoformat()


def now_local() -> datetime:
    """Текущее время в зоне, в которой Ozon отдаёт даты (см. config.TIMEZONE)."""
    return datetime.now(tz=_TZ)


def cutoff_ts(period_days: int, now: datetime | None = None) -> float:
    """Отметка времени, старше которой отзывы отбрасываются.

    `now` инъектируется в тестах, иначе функция зависела бы от системных часов
    и результат нельзя было бы проверить детерминированно.
    """
    return ((now or now_local()) - timedelta(days=period_days)).timestamp()


def _media_urls(items) -> list:
    urls = []
    for it in items or []:
        if isinstance(it, dict):
            u = it.get("url") or it.get("previewUrl") or it.get("image")
            if u:
                urls.append(u)
        elif isinstance(it, str):
            urls.append(it)
    return urls


def to_review(raw: dict, products: dict) -> Review:
    author = raw.get("author") or {}
    name = " ".join(p for p in (author.get("firstName", ""), author.get("lastName", "")) if p).strip()
    content = raw.get("content") or {}
    usefulness = raw.get("usefulness") or {}
    return Review(
        author=name or "Аноним",
        rating=int(content.get("score") or 0),
        date=ts_to_date(raw.get("publishedAt") or raw.get("createdAt")),
        text=content.get("comment", "") or "",
        pros=content.get("positive", "") or "",
        cons=content.get("negative", "") or "",
        useful_count=int(usefulness.get("useful") or 0),
        unuseful_count=int(usefulness.get("unuseful") or 0),
        purchased=bool(raw.get("isItemPurchased")),
        photos=_media_urls(content.get("photos")),
        videos=_media_urls(content.get("videos")),
        variant=variant_map(raw.get("itemId"), products),
    )
