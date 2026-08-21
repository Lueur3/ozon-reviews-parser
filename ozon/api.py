"""Доступ к внутреннему API Ozon и знание о его адресах — в одном месте.

Раньше путь эндпоинта, JS-сниппет fetch, список отбрасываемых заголовков и
логика ожидания капчи были скопированы в collector.py и в четыре скрипта
scripts/*. Смена версии API означала правку в пяти файлах.

Здесь же собраны все строки, зависящие от структуры сайта (пути страниц,
параметры сортировок) — при изменениях на стороне Ozon правится только этот
модуль.
"""
import json
from urllib.parse import quote, urlparse

from . import config
from .errors import CaptchaTimeout
from .logging_setup import get_logger

log = get_logger("ozon.api")

# --- адреса и параметры Ozon ------------------------------------------------
API_PATH = "/api/entrypoint-api.bx/page/json/v2?url="
VARIANT_MODE = "reviewsVariantMode=2"        # отдать отзывы всех вариантов товара
SORT_NEWEST = "published_at_desc"
SORT_SCORE_ASC = "score_asc"
SORT_SCORE_DESC = "score_desc"
QUESTIONS_SORT = "has_answers_desc"          # «сначала с ответом»

# Имена виджетов в ответе Ozon. Меняются при редизайне их фронта — тогда парсинг
# соответствующего блока замолкает, и это ловит `--doctor`.
WIDGET_REVIEWS = "webListReviews"
WIDGET_PRICE = "webPrice-"                   # дефис обязателен: без него совпадёт
                                             # декоративный webPriceDecreasedCompact
WIDGET_CHARACTERISTICS = "webCharacteristics"
WIDGET_SHORT_CHARACTERISTICS = "webShortCharacteristics"
WIDGET_QUESTIONS = "webListQuestions"

# Заголовки, которые браузер выставит сам: свои значения ломают fetch.
DROP_HEADERS = {"host", "cookie", "content-length", "accept-encoding", "connection",
                "user-agent", "origin", "referer"}

# Выполняется в контексте страницы, поэтому несёт куки и отпечаток живой сессии.
FETCH_JS = """async ({u, h}) => {
    const r = await fetch(u, {headers: h, credentials: 'include'});
    return {status: r.status, text: await r.text()};
}"""




def origin_of(url: str) -> str:
    pr = urlparse(url)
    return f"{pr.scheme}://{pr.netloc}"


def product_path(url: str) -> str:
    """Путь карточки товара со слэшем на конце: /product/<slug>-<id>/."""
    path = urlparse(url).path
    return path if path.endswith("/") else path + "/"


def reviews_path(url: str) -> str:
    return product_path(url) + "reviews/"


def features_path(ppath: str) -> str:
    return ppath + "features/"


def reviews_feed(rpath: str, sort: str) -> str:
    return f"{rpath}?sort={sort}&{VARIANT_MODE}"


def questions_page(ppath: str, page: int) -> str:
    return f"{ppath}questions/?qsort={QUESTIONS_SORT}&page={page}"


def question_page(ppath: str, question_id) -> str:
    return f"{ppath}question/{question_id}/"


def session_headers(raw_headers: dict) -> dict:
    """Заголовки живой сессии, пригодные для fetch (без служебных и HTTP/2-псевдо)."""
    return {k: v for k, v in raw_headers.items()
            if k.lower() not in DROP_HEADERS and not k.startswith(":")}


class OzonClient:
    """Запросы к entrypoint-api в контексте страницы, с ожиданием решения капчи."""

    def __init__(self, page, origin: str, headers: dict, recovery_url: str = "",
                 captcha_iters: int = config.CAPTCHA_WAIT_ITERS,
                 poll_ms: int = config.CAPTCHA_POLL_MS):
        self.page = page
        self.origin = origin
        self.headers = headers
        self.recovery_url = recovery_url    # что открыть в окне, чтобы пользователь решил капчу
        self.captcha_iters = captcha_iters
        self.poll_ms = poll_ms

    async def fetch(self, param: str) -> dict:
        """GET JSON по внутреннему пути. При капче/блоке ждёт и повторяет."""
        url = self.origin + API_PATH + quote(param, safe="")
        waited = False
        reason = "неизвестно"
        for _ in range(self.captcha_iters):
            try:
                res = await self.page.evaluate(FETCH_JS, {"u": url, "h": self.headers})
                if isinstance(res, dict) and res.get("status") == 200:
                    return json.loads(res["text"])
                reason = f"HTTP {res.get('status') if isinstance(res, dict) else '?'}"
            except json.JSONDecodeError as e:
                reason = f"ответ не JSON ({e})"        # обычно HTML страницы капчи
            except Exception as e:
                reason = repr(e)                        # сеть/страница закрыта/JS упал
            log.debug("fetch %s не удался: %s", param, reason)
            if not waited:
                print(">>> Капча/блокировка Ozon. Реши капчу в открытом окне Chrome — "
                      "жду и продолжу сам...")
                log.warning("captcha/block (%s): жду решения пользователя в окне", reason)
                await self._open_recovery()
                waited = True
            await self.page.wait_for_timeout(self.poll_ms)
        raise CaptchaTimeout(
            f"за {self.captcha_iters * self.poll_ms // 60000} мин доступ не восстановился "
            f"(последняя причина: {reason}). Проверь VPN и решённую капчу в окне Chrome.")

    async def _open_recovery(self):
        if not self.recovery_url:
            return
        try:
            await self.page.goto(self.recovery_url, wait_until="domcontentloaded")
        except Exception as e:
            log.warning("не удалось открыть страницу для капчи: %r", e)
