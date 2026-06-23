"""Запуск браузера для обхода анти-бота Ozon через Patchright.

Patchright — патченный Playwright: убирает детектируемые следы автоматизации
на уровне протокола управления (CDP/Runtime.enable), которые playwright-stealth
не закрывает. По рекомендациям Patchright: реальный Chrome (channel="chrome"),
без подмены user-agent и заголовков, без кастомного viewport.
"""
import contextlib
from pathlib import Path

from patchright.async_api import async_playwright

import config


@contextlib.asynccontextmanager
async def launch_browser(headless: bool = False, profile_dir: Path = config.PROFILE_DIR):
    """Контекстный менеджер: даёт (context, page) реального Chrome. Без входа в аккаунт."""
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome",
            headless=headless,
            no_viewport=True,
        )
        context.set_default_navigation_timeout(config.NAV_TIMEOUT_MS)
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            yield context, page
        finally:
            await context.close()
