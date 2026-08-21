"""Запуск браузера для обхода анти-бота Ozon через Patchright.

Patchright — патченный Playwright: убирает детектируемые следы автоматизации
на уровне протокола управления (CDP/Runtime.enable), которые playwright-stealth
не закрывает. По рекомендациям Patchright: реальный Chrome (channel="chrome"),
без подмены user-agent и заголовков, без кастомного viewport.
"""
import contextlib
import shutil
from pathlib import Path

from patchright.async_api import async_playwright

from . import config
from .errors import BrowserNotFound
from .logging_setup import get_logger

log = get_logger("ozon.browser")

# Стандартные места установки Chrome на Windows/macOS/Linux.
_CHROME_PATHS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
)


def chrome_available() -> bool:
    """Есть ли установленный Chrome (в PATH или в стандартном месте)."""
    if shutil.which("chrome") or shutil.which("google-chrome"):
        return True
    return any(Path(p).exists() for p in _CHROME_PATHS)


def reset_profile(profile_dir: Path = config.PROFILE_DIR) -> bool:
    """Удаляет сохранённый профиль браузера. True, если было что удалять."""
    if not profile_dir.exists():
        return False
    shutil.rmtree(profile_dir, ignore_errors=True)
    log.info("профиль сброшен: %s", profile_dir)
    return True


@contextlib.asynccontextmanager
async def launch_browser(headless: bool = False, profile_dir: Path = config.PROFILE_DIR,
                         fresh_profile: bool = False):
    """Контекстный менеджер: даёт (context, page) реального Chrome. Без входа в аккаунт."""
    # Понятная ошибка вместо низкоуровневого "Executable doesn't exist" из Patchright.
    if not chrome_available():
        raise BrowserNotFound(
            "не найден Google Chrome. Установите его с https://www.google.com/chrome/ — "
            "парсер использует реальный Chrome, отдельный браузер не скачивается.")
    if fresh_profile:
        reset_profile(profile_dir)

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
