"""Запуск парсера из корня проекта: python main.py "<ссылка>".

Сам CLI живёт в пакете (ozon/cli.py) — так он доступен и как `python -m ozon`,
и как установленная команда `ozon-reviews-parser`.
"""
from ozon.cli import main

if __name__ == "__main__":
    main()
