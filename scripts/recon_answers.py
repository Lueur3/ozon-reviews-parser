r"""Recon догрузки всех ответов (без кликов, через fetch).

ВАЖНО: VPN выключен.

    .\.venv\Scripts\python.exe scripts/recon_answers.py "https://ozon.ru/t/nPDyAby"

Берёт страницу вопросов, находит вопрос с пометкой 'Ещё N ответ'
(getAnswersAction), затем фетчит его личную страницу /question/<id>/ и
смотрит, есть ли там ВСЕ ответы. Сохраняет captures/qa_ans/*.json и _index.txt.
"""
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ozon.browser import launch_browser

API = "/api/entrypoint-api.bx/page/json/v2?url="
DROP = {"host", "cookie", "content-length", "accept-encoding", "connection",
        "user-agent", "origin", "referer"}
FETCH_JS = """async ({u, h}) => {
    const r = await fetch(u, {headers: h, credentials: 'include'});
    return {status: r.status, text: await r.text()};
}"""

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

QA = ROOT / "captures" / "qa_ans"


def widget_states(data):
    out = {}
    for k, v in (data.get("widgetStates") or {}).items():
        if isinstance(v, str):
            try:
                out[k] = json.loads(v)
            except Exception:
                pass
        elif isinstance(v, dict):
            out[k] = v
    return out


def qwidget(data):
    if not isinstance(data, dict):
        return None
    for k, w in widget_states(data).items():
        if k.startswith("webListQuestions"):
            return w
    st = data.get("state")
    if isinstance(st, str):
        try:
            st = json.loads(st)
        except Exception:
            st = None
    if isinstance(st, dict) and "questions" in st:
        return st
    return None


async def main(url):
    QA.mkdir(parents=True, exist_ok=True)
    state = {"headers": None}
    pending = []

    async def on_resp(resp):
        try:
            if "entrypoint-api" in resp.url and state["headers"] is None \
                    and "json" in resp.headers.get("content-type", ""):
                hh = await resp.request.all_headers()
                state["headers"] = {k: v for k, v in hh.items()
                                    if k.lower() not in DROP and not k.startswith(":")}
        except Exception:
            pass

    def schedule(r):
        pending.append(asyncio.ensure_future(on_resp(r)))

    report = []
    async with launch_browser(headless=False) as (ctx, page):
        page.on("response", schedule)
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        pr = urlparse(page.url)
        ppath = pr.path if pr.path.endswith("/") else pr.path + "/"
        origin = f"{pr.scheme}://{pr.netloc}"
        headers = state["headers"] or {}
        report.append(f"headers: {'есть' if headers else 'НЕТ'}")

        async def fetch(u):
            res = await page.evaluate(FETCH_JS, {"u": origin + API + quote(u, safe=""), "h": headers})
            return json.loads(res["text"]) if res.get("status") == 200 else None

        target = None
        w = None
        for page_n in range(1, 10):
            qd = await fetch(ppath + f"questions/?qsort=has_answers_desc&page={page_n}")
            ww = qwidget(qd)
            if not ww:
                report.append(f"page {page_n}: нет webListQuestions")
                break
            qs = ww.get("questions") or {}
            found = [qid for qid, q in qs.items()
                     if isinstance(q, dict) and q.get("getAnswersAction")]
            report.append(f"page {page_n}: вопросов={len(qs)}, с доп.ответами={len(found)}")
            if found and not target:
                target = found[0]
                w = ww
                (QA / "questions_page.json").write_text(
                    json.dumps(qd, ensure_ascii=False), encoding="utf-8")
            if not qs:
                break
        report.append(f"итог: вопрос с доп.ответами = {target}")
        if target:
            q = w["questions"][target]
            report.append("getAnswersAction: " + json.dumps(q.get("getAnswersAction"), ensure_ascii=False))
            report.append("в ленте ответов на этот вопрос: "
                          + str(len((w.get("questionAnswers") or {}).get(str(target), []))))
            qpage = await fetch(ppath + f"question/{target}/")
            (QA / "question_page.json").write_text(
                json.dumps(qpage, ensure_ascii=False) if qpage else "null", encoding="utf-8")
            qw = qwidget(qpage)
            if qw:
                report.append(f"на странице /question/{target}/: "
                              f"questions={len(qw.get('questions') or {})}, "
                              f"answers={len(qw.get('answers') or {})}, "
                              f"questionAnswers={json.dumps(qw.get('questionAnswers'), ensure_ascii=False)[:300]}")
            else:
                report.append("на странице вопроса webListQuestions НЕ найден")

        page.remove_listener("response", schedule)

    (QA / "_index.txt").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))
    print("См. captures/qa_ans/")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('нужна ссылка: python scripts/recon_answers.py "https://ozon.ru/t/nPDyAby"')
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
