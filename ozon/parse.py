"""Парсинг JSON-ответов Ozon (entrypoint-api page json v2)."""
import json
from datetime import datetime, timedelta

from dateutil import tz

from .models import Review

_TZ = tz.gettz("Europe/Moscow") or tz.UTC


def _widget_states(data: dict) -> dict:
    out = {}
    for k, v in (data.get("widgetStates") or {}).items():
        if isinstance(v, str):
            try:
                out[k] = json.loads(v)
            except Exception:
                continue
        elif isinstance(v, dict):
            out[k] = v
    return out


def extract_reviews_widget(data: dict):
    """Из webListReviews возвращает (reviews_raw, products, score, total) или None."""
    for k, w in _widget_states(data).items():
        if k.startswith("webListReviews") and isinstance(w, dict) and "reviews" in w:
            return (
                w.get("reviews") or [],
                w.get("products") or {},
                w.get("productScore"),
                (w.get("paging") or {}).get("total"),
            )
    return None


def _find_widget(data: dict, prefix: str):
    for k, w in _widget_states(data).items():
        if k.startswith(prefix):
            return w
    return None


def parse_price(data: dict) -> dict:
    """Из webPrice: {price, card_price, original_price, is_available}."""
    w = _find_widget(data, "webPrice")
    if not isinstance(w, dict):
        return {}
    out = {
        "price": w.get("price"),
        "card_price": w.get("cardPrice"),
        "is_available": w.get("isAvailable"),
    }
    if w.get("showOriginalPrice"):
        out["original_price"] = w.get("originalPrice")
    return {k: v for k, v in out.items() if v is not None}


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
    for k, w in _widget_states(data).items():
        if k.startswith("webCharacteristics"):
            c = _chars_from_webchar(w)
            if len(c) > len(best):
                best = c
    if best:
        return best
    # откат: webShortCharacteristics (вложенная структура карточки)
    w = _find_widget(data, "webShortCharacteristics")
    if isinstance(w, dict):
        for ch in w.get("characteristics", []):
            title = ch.get("title") or {}
            name = "".join(t.get("content", "") for t in title.get("textRs", [])
                           if t.get("type") == "text").strip()
            values = [v.get("text", "") for v in (ch.get("values") or []) if v.get("text")]
            if name and values:
                best[name] = ", ".join(values)
    return best


def variant_map(item_id, products: dict) -> dict:
    p = products.get(str(item_id)) or {}
    return {v.get("name", ""): v.get("value", "") for v in (p.get("variants") or [])}


def ts_to_date(ts) -> str:
    return datetime.fromtimestamp(int(ts or 0), tz=_TZ).date().isoformat()


def cutoff_ts(period_days: int) -> float:
    return (datetime.now(tz=_TZ) - timedelta(days=period_days)).timestamp()


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
