r"""Recon для цены, характеристик и вопросов/ответов.

ВАЖНО: запускать с ВЫКЛЮЧЕННЫМ VPN.

    .\.venv\Scripts\python.exe scripts/recon_extra.py "<ссылка на товар>"

Берёт заголовки API из живой сессии и через fetch тянет JSON карточки и
раздела вопросов. Сохраняет сырьё в captures/extra/ и карту виджетов
(layout-компоненты + ключи widgetStates) в captures/extra/_widgets.txt —
по ней найдём, где цена, характеристики и Q&A.
"""
import argparse
import asyncio
import json

from _common import CAPTURES, api, open_session, utf8_stdout

utf8_stdout()
EXTRA = CAPTURES / "extra"


def widget_map(data: dict) -> list[str]:
    out = []
    layout = data.get("layout")
    if isinstance(layout, list):
        for w in layout:
            out.append(f"  layout: {w.get('component')}  stateId={w.get('stateId')}")
    ws = data.get("widgetStates")
    if isinstance(ws, dict):
        for k in ws:
            out.append(f"  state : {k}")
    return out


async def recon(url: str):
    EXTRA.mkdir(parents=True, exist_ok=True)
    report = []
    print("Открываю:", url)
    async with open_session(url) as s:
        print(f"id={s.product_id} | заголовки API: {'есть' if s.client.headers else 'НЕТ'}")

        async def fetch_dump(param, label):
            try:
                data = await s.fetch(param)
            except Exception as e:
                print(f"[{label}] ошибка: {e!r}")
                report.append(f"### {label}  ({param})\n  ОШИБКА: {e!r}")
                return None
            text = json.dumps(data, ensure_ascii=False)
            (EXTRA / f"{label}.json").write_text(text, encoding="utf-8")
            keys = widget_map(data)
            report.append(f"### {label}  ({param})  [{len(text)} байт]\n" + "\n".join(keys))
            print(f"[{label}] сохранено ({len(text)} байт), виджетов: {len(keys)}")
            return data

        # карточка (цена/артикул/краткие характеристики), полные характеристики, вопросы
        ppath = s.ppath
        await fetch_dump(ppath, "product")
        await fetch_dump(api.features_path(ppath), "features")
        await fetch_dump(ppath + "questions/", "questions")

    (EXTRA / "_widgets.txt").write_text("\n\n".join(report), encoding="utf-8")
    print("\nКарта виджетов: captures/extra/_widgets.txt")
    print("Сырьё: captures/extra/*.json")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Recon карточки, характеристик и вопросов.")
    p.add_argument("url", help="ссылка на товар")
    asyncio.run(recon(p.parse_args().url))
