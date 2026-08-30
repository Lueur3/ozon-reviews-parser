r"""Recon ответов: приходят ли все ответы вместе с вопросом или часть теряется.

ВАЖНО: VPN выключен.

    .\.venv\Scripts\python.exe scripts/recon_answers.py "<ссылка или артикул>"
    .\.venv\Scripts\python.exe scripts/recon_answers.py "<ссылка>" --pages 5 --clicks 5

Парсер исходит из того, что ответы приходят вложенными в вопрос и отдельно их
догружать не нужно. Скрипт это допущение проверяет в три фазы:

1. Листает ленту вопросов и считает, по сколько ответов приходит на вопрос;
   для самого «богатого» вопроса пробует его личную страницу и сравнивает.
2. Открывает страницу вопросов, жмёт «Ещё N ответов» и записывает запросы, которые
   при этом уходят: метод, адрес, тело и заголовки. Числа «ещё N» в ответе ленты нет,
   поэтому найти способ догрузки по сохранённому сырью невозможно — он проявляется
   только при клике. Пойманные догрузки целиком ложатся в captures/qa_ans/expand_requests.json:
   по ним и пишется реализация.
3. Догружает ответы самостоятельно по всем вопросам первой страницы и сверяет с лентой:
   сколько пришло сверх неё и не повторяется ли уже известный ответ. Курсор в запросе
   обязателен, но одно из его полей непрозрачно — берём базовое значение, оно принимается.

Разбор идёт через `parse.parse_questions`, то есть ровно тем же кодом, что и в
проде: скрипт не может разойтись с парсером и не устаревает отдельно от него.

Сохраняет captures/qa_ans/: сырьё страниц и _index.txt с отчётом.
"""
import argparse
import asyncio
import base64
import collections
import json

from _common import CAPTURES, api, open_session, utf8_stdout

from ozon import parse

utf8_stdout()
QA = CAPTURES / "qa_ans"


def _dump(name: str, data) -> None:
    (QA / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


async def _catch_expand_requests(s, clicks: int = 3):
    """Фаза 2: раскрыть «Ещё N ответов» на странице и записать, что при этом ушло в сеть.

    Числа «ещё N» в ответе ленты нет, значит остальные ответы подтягиваются отдельным
    запросом. Найти его по сохранённому сырью нельзя — он случается только при клике,
    поэтому кликаем и слушаем.
    """
    out = ["--- раскрытие «Ещё N ответов» ---"]
    caught = []
    pending = []

    async def capture(resp):
        """Снять с ответа всё, что понадобится для реализации: метод, тело, заголовки."""
        req = resp.request
        rec = {"status": resp.status, "method": req.method, "url": resp.url}
        try:
            rec["post_data"] = req.post_data
        except Exception as e:
            rec["post_data"] = f"<не снято: {e.__class__.__name__}>"
        try:
            rec["headers"] = await req.all_headers()
        except Exception:
            rec["headers"] = {}
        try:
            rec["body"] = await resp.json()
        except Exception:
            rec["body"] = None
        caught.append(rec)

    def on_response(resp):
        u = resp.url
        if "entrypoint-api" in u or "composer-api" in u:
            pending.append(asyncio.ensure_future(capture(resp)))

    page = s.page
    page.on("response", on_response)
    try:
        await page.goto(s.resolved_url.split("?")[0].rstrip("/") + "/questions/",
                        wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        await asyncio.gather(*pending, return_exceptions=True)
        pending.clear()
        before = len(caught)
        # Текст кнопки пишут и через «Ещё», и через «Еще»; число и окончание любые.
        expanders = page.locator("text=/Ещ[её]\\s+\\d+\\s+ответ/")
        found = await expanders.count()
        out.append(f"кнопок «Ещё N ответов» на странице: {found}")
        for i in range(min(found, clicks)):
            try:
                await expanders.nth(i).scroll_into_view_if_needed()
                await expanders.nth(i).click()
                await page.wait_for_timeout(2500)
            except Exception as e:
                out.append(f"  клик {i + 1} не удался: {e.__class__.__name__}")
        await asyncio.gather(*pending, return_exceptions=True)
        pending.clear()

        new = caught[before:]
        out.append(f"запросов после кликов: {len(new)}")
        for rec in new[:20]:
            out.append(f"  {rec['status']} {rec['method']} {rec['url'][:150]}")
            if rec["post_data"]:
                out.append(f"       тело: {str(rec['post_data'])[:400]}")
        if not new:
            out.append("  сеть молчит — ответы, вероятно, уже лежали в состоянии страницы")

        # Запросы догрузки складываем целиком: по ним и пишется реализация.
        answers = [r for r in new if "getanswers" in r["url"].lower()]
        if answers:
            _dump("expand_requests.json", answers)
            out.append(f"догрузок ответов поймано: {len(answers)} "
                       f"-> captures/qa_ans/expand_requests.json")
            first = answers[0]
            body = first.get("body")
            if isinstance(body, dict):
                out.append(f"  ключи ответа: {sorted(body)[:12]}")
            hdrs = {k: v for k, v in (first.get("headers") or {}).items()
                    if k.lower().startswith("x-o3") or k.lower() == "content-type"}
            out.append(f"  заголовки запроса (значимые): {json.dumps(hdrs, ensure_ascii=False)[:200]}")
        else:
            out.append("  запросов догрузки не видно — искать в списке выше")
    except Exception as e:
        out.append(f"фаза 2 не отработала: {e!r}")
    finally:
        page.remove_listener("response", on_response)
    return out


POST_JS = """async ({u, h, b}) => {
    const r = await fetch(u, {method: 'POST', headers: h, body: b, credentials: 'include'});
    return {status: r.status, text: await r.text()};
}"""

ANSWERS_ACTION = "/api/composer-api.bx/_action/v2/getAnswers"
# Базовое значение непрозрачного поля курсора: страница шлёт его со смещением,
# но и базовое принимается — проверено, 200 против 503/400 у прочих вариантов.
BASE_USEFULNESS = 2 ** 62


async def _probe_answer_variants(s, questions):
    """Фаза 3: собрать ответы своими силами и сверить с тем, что даёт лента.

    Курсор в запросе обязателен (без него 503, с обнулённым 400), но подделывается:
    значение usefulness можно взять базовым, и запрос принимается. Проверяем на всех
    вопросах страницы, сколько ответов возвращается сверх ленты и не повторяет ли
    выдача уже известный ответ.
    """
    out = ["--- догрузка своими силами ---"]
    headers = dict(s.client.headers or {})
    headers["content-type"] = "application/json"
    totals = {"feed": 0, "loaded": 0, "new": 0}

    for q in questions[:10]:
        item_id, quuid = q.get("itemId"), q.get("questionUuid")
        feed = q.get("answers") or []
        if not (item_id and quuid and feed):
            continue
        known = {a.get("answerUuid") for a in feed}
        cursor = base64.b64encode(json.dumps(
            {"last_usefulness": BASE_USEFULNESS, "last_uuid": feed[-1].get("answerUuid") or ""},
            separators=(",", ":")).encode()).decode()
        try:
            res = await s.page.evaluate(POST_JS, {
                "u": s.client.origin + ANSWERS_ACTION, "h": headers,
                "b": json.dumps({"itemId": str(item_id), "questionUuid": quuid,
                                 "pagingParams": cursor}, ensure_ascii=False)})
            if res.get("status") != 200:
                out.append(f"  {quuid[:8]}: HTTP {res.get('status')}")
                continue
            got = ((json.loads(res["text"]).get("data") or {}).get("answers") or [])
            fresh = [a for a in got if a.get("answerUuid") not in known]
            totals["feed"] += len(feed)
            totals["loaded"] += len(got)
            totals["new"] += len(fresh)
            out.append(f"  {quuid[:8]}: в ленте {len(feed)}, догружено {len(got)}, "
                       f"из них новых {len(fresh)}")
        except Exception as e:
            out.append(f"  {quuid[:8]}: не отработал {e!r}")
        await s.page.wait_for_timeout(600)

    out.append(f"итого: в ленте {totals['feed']}, догружено {totals['loaded']}, "
               f"новых {totals['new']}")
    if totals["new"]:
        out.append(f"ВЫВОД: догрузка работает и даёт в {(totals['feed'] + totals['new']) / max(totals['feed'], 1):.1f} "
                   f"раза больше ответов. Сверить с надписями «Ещё N» на странице: если "
                   f"совпадает — одного запроса на вопрос достаточно, пагинация не нужна.")
    else:
        out.append("ВЫВОД: новых ответов не пришло — курсор понят иначе, чем ожидалось.")
    return out


async def recon(url: str, max_pages: int, clicks: int):
    QA.mkdir(parents=True, exist_ok=True)
    report = []
    best = None          # вопрос с наибольшим числом ответов
    total = 0
    flagged = 0          # вопросы, у которых парсер сам подозревает недогруз
    spread = collections.Counter()   # сколько вопросов с каким числом ответов
    raw_questions = []    # сырые вопросы для фазы 3: нужны itemId и answerUuid

    async with open_session(url) as s:
        report.append(f"headers: {'есть' if s.client.headers else 'НЕТ'}")
        ppath = s.ppath

        # Листаем курсором из ответа — тем же способом, что и основной сбор.
        param = api.questions_page(ppath, 1)
        for page_n in range(1, max_pages + 1):
            if not param:
                report.append(f"страница {page_n}: курсора нет, лента закончилась")
                break
            qdata = await s.fetch(param)
            if page_n == 1:
                _dump("questions_page.json", qdata)
            questions = parse.parse_questions(qdata, answered_only=False)
            if page_n == 1:
                w = parse.question_widget(qdata) or {}
                raw_qs = w.get("questions")
                raw_questions = raw_qs if isinstance(raw_qs, list) else []
            if not questions:
                report.append(f"страница {page_n}: вопросов не разобрано")
                break
            total += len(questions)
            flagged += sum(1 for q in questions if q["_has_more"])
            counts = sorted((len(q["answers"]) for q in questions), reverse=True)
            spread.update(counts)
            report.append(f"страница {page_n}: вопросов={len(questions)}, "
                          f"ответов максимум={counts[0]}, без ответов="
                          f"{sum(1 for c in counts if c == 0)}")
            top = max(questions, key=lambda q: len(q["answers"]))
            if best is None or len(top["answers"]) > len(best["answers"]):
                best = top
            param = parse.next_page(qdata)

        report.append("")
        report.append(f"всего вопросов просмотрено: {total}")
        report.append(f"из них помечены как «есть ещё ответы»: {flagged}")
        report.append("распределение числа ответов: "
                      + ", ".join(f"{k}->{v}" for k, v in sorted(spread.items())))
        if total and len(spread) == 1:
            only = next(iter(spread))
            report.append(f"ВНИМАНИЕ: у всех вопросов ровно {only} ответ(ов). Либо лента "
                          f"отдаёт не больше, либо столько и есть — сверить глазами на сайте.")

        if not best or not best["_id"]:
            report.append("ВЫВОД: сравнивать не с чем — вопрос с ответами не найден.")
        else:
            inline = len(best["answers"])
            report.append(f"проверяем вопрос {best['_id']}: в ленте ответов={inline}")
            qpage = await s.fetch(api.question_page(ppath, best["_id"]))
            _dump("question_page.json", qpage)
            alone = parse.parse_questions(qpage, answered_only=False)
            if not alone:
                # Личная страница вопроса может отдавать не вопрос, а карточку товара —
                # тогда сравнивать не с чем и вывод делается только по самой ленте.
                widgets = list((qpage or {}).get("widgetStates") or {})
                report.append(f"личная страница вопроса вопрос не содержит "
                              f"(виджетов в ответе: {len(widgets)}) — сравнить не с чем. "
                              f"Сырьё: captures/qa_ans/question_page.json")
            else:
                own = max(len(q["answers"]) for q in alone)
                report.append(f"на личной странице ответов={own}")
                if own > inline:
                    report.append(f"ВЫВОД: НЕДОГРУЗ — вместе с вопросом приходит {inline} "
                                  f"из {own}. Нужна отдельная догрузка ответов.")
                else:
                    report.append("ВЫВОД: ответы приходят полностью вместе с вопросом, "
                                  "отдельная догрузка не нужна.")

        report.append("")
        report.extend(await _catch_expand_requests(s, clicks))
        if raw_questions:
            report.append("")
            report.extend(await _probe_answer_variants(s, raw_questions))

    (QA / "_index.txt").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))
    print("См. captures/qa_ans/")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Проверка полноты ответов на вопросы.")
    p.add_argument("url", help="ссылка на товар или артикул")
    p.add_argument("--pages", type=int, default=5,
                   help="сколько страниц ленты просмотреть (по умолчанию 5)")
    p.add_argument("--clicks", type=int, default=3,
                   help="сколько кнопок «Ещё N ответов» раскрыть (по умолчанию 3)")
    args = p.parse_args()
    asyncio.run(recon(args.url, args.pages, args.clicks))
