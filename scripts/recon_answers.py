r"""Recon догрузки всех ответов (без кликов, через fetch).

ВАЖНО: VPN выключен.

    .\.venv\Scripts\python.exe scripts/recon_answers.py "<ссылка на товар>"

Берёт страницу вопросов, находит вопрос с пометкой 'Ещё N ответ'
(getAnswersAction), затем фетчит его личную страницу /question/<id>/ и
смотрит, есть ли там ВСЕ ответы. Сохраняет captures/qa_ans/*.json и _index.txt.
"""
import argparse
import asyncio
import json

from _common import CAPTURES, api, open_session, utf8_stdout

from ozon import parse

utf8_stdout()
QA = CAPTURES / "qa_ans"


async def recon(url: str):
    QA.mkdir(parents=True, exist_ok=True)
    report = []
    async with open_session(url) as s:
        report.append(f"headers: {'есть' if s.client.headers else 'НЕТ'}")
        ppath = s.ppath

        target, widget = None, None
        for page_n in range(1, 10):
            qd = await s.fetch(api.questions_page(ppath, page_n))
            ww = parse._question_widget(qd)      # тот же разбор, что и в проде
            if not ww:
                report.append(f"page {page_n}: нет webListQuestions")
                break
            qs = ww.get("questions") or {}
            found = [qid for qid, q in qs.items()
                     if isinstance(q, dict) and q.get("getAnswersAction")]
            report.append(f"page {page_n}: вопросов={len(qs)}, с доп.ответами={len(found)}")
            if found and not target:
                target, widget = found[0], ww
                (QA / "questions_page.json").write_text(
                    json.dumps(qd, ensure_ascii=False), encoding="utf-8")
            if not qs:
                break

        report.append(f"итог: вопрос с доп.ответами = {target}")
        if target:
            q = widget["questions"][target]
            report.append("getAnswersAction: "
                          + json.dumps(q.get("getAnswersAction"), ensure_ascii=False))
            report.append("в ленте ответов на этот вопрос: "
                          + str(len((widget.get("questionAnswers") or {}).get(str(target), []))))
            qpage = await s.fetch(api.question_page(ppath, target))
            (QA / "question_page.json").write_text(
                json.dumps(qpage, ensure_ascii=False) if qpage else "null", encoding="utf-8")
            qw = parse._question_widget(qpage)
            if qw:
                report.append(f"на странице /question/{target}/: "
                              f"questions={len(qw.get('questions') or {})}, "
                              f"answers={len(qw.get('answers') or {})}, "
                              f"questionAnswers="
                              f"{json.dumps(qw.get('questionAnswers'), ensure_ascii=False)[:300]}")
            else:
                report.append("на странице вопроса webListQuestions НЕ найден")

    (QA / "_index.txt").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))
    print("См. captures/qa_ans/")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Recon догрузки всех ответов на вопрос.")
    p.add_argument("url", help="ссылка на товар")
    asyncio.run(recon(p.parse_args().url))
