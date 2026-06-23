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


def variant_map(item_id, products: dict) -> dict:
    p = products.get(str(item_id)) or {}
    return {v.get("name", ""): v.get("value", "") for v in (p.get("variants") or [])}


def ts_to_date(ts) -> str:
    return datetime.fromtimestamp(int(ts or 0), tz=_TZ).date().isoformat()


def cutoff_ts(period_days: int) -> float:
    return (datetime.now(tz=_TZ) - timedelta(days=period_days)).timestamp()


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
        variant=variant_map(raw.get("itemId"), products),
    )
