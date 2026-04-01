"""Один Chromium на процесс: меньше RAM и времени старта при параллельных fetch_detail."""

from __future__ import annotations

import asyncio

import structlog
from playwright.async_api import Browser, Playwright, async_playwright

log = structlog.get_logger()

_playwright: Playwright | None = None
_browser: Browser | None = None
_browser_headless: bool | None = None
_lock = asyncio.Lock()


async def shared_chromium(*, headless: bool) -> Browser:
    """Возвращает общий браузер; новый контекст на каждую операцию — закрывайте ctx сами."""
    global _playwright, _browser, _browser_headless
    async with _lock:
        if _browser is not None and _browser_headless == headless:
            return _browser
        if _browser is not None:
            await _browser.close()
            _browser = None
        if _playwright is not None:
            await _playwright.stop()
            _playwright = None
        log.info("playwright_shared_launch", headless=headless)
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(headless=headless)
        _browser_headless = headless
        return _browser


async def shutdown_shared_playwright() -> None:
    """Вызывать при остановке процесса (бот / воркер)."""
    global _playwright, _browser, _browser_headless
    async with _lock:
        if _browser is not None:
            try:
                await _browser.close()
            except Exception as e:
                log.warning("playwright_shared_browser_close", error=str(e))
            _browser = None
        if _playwright is not None:
            try:
                await _playwright.stop()
            except Exception as e:
                log.warning("playwright_shared_stop", error=str(e))
            _playwright = None
        _browser_headless = None
