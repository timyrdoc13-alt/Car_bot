"""Общие хелперы Playwright: скролл, ожидание, цена из текста, сбор изображений."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urljoin

from playwright.async_api import Page

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
)
IPHONE_SAFARI_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"
)


def extract_usd_price_from_text(text: str) -> str | None:
    """Первая сумма в USD из текста (доллары / USD / $)."""
    patterns = (
        r"(?:USD|долл|\$)\s*[:\s]*([\d][\d\s\u00a0]*)",
        r"([\d][\d\s\u00a0]*)\s*USD\b",
    )
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if not m:
            continue
        digits = re.sub(r"\D+", "", m.group(1))
        if digits:
            return digits
    return None


async def scroll_page(page: Page, *, rounds: int, step_px: int, pause_s: float) -> None:
    for _ in range(max(1, rounds)):
        await page.evaluate(f"window.scrollBy(0, {step_px})")
        await asyncio.sleep(max(0.1, pause_s))


async def scroll_until_height_stable(
    page: Page,
    *,
    step_px: int = 1400,
    pause_s: float = 1.8,
    max_rounds: int = 14,
    stable_needed: int = 2,
) -> tuple[int, int]:
    """
    Скролл до стабилизации scrollHeight (infinite scroll).
    Возвращает (число раундов скролла, финальный scrollHeight).
    """
    last_h = 0
    stable = 0
    rounds = 0
    for _ in range(max(1, max_rounds)):
        rounds += 1
        h = await page.evaluate("document.body ? document.body.scrollHeight : 0")
        try:
            h_int = int(h)
        except (TypeError, ValueError):
            h_int = 0
        if h_int == last_h and h_int > 0:
            stable += 1
            if stable >= max(1, stable_needed):
                break
        else:
            stable = 0
        last_h = h_int
        await page.mouse.wheel(0, step_px)
        await asyncio.sleep(max(0.35, pause_s))
    final = await page.evaluate("document.body ? document.body.scrollHeight : 0")
    try:
        final_int = int(final)
    except (TypeError, ValueError):
        final_int = 0
    return rounds, final_int


async def delay_after_navigation(page: Page, seconds: float) -> None:
    await asyncio.sleep(max(0.5, seconds))


async def extract_title_and_body(page: Page) -> tuple[str, str]:
    title = ""
    h1 = page.locator("h1").first
    if await h1.count():
        title = (await h1.inner_text()).strip()

    body_text = ""
    main = page.locator("main").first
    if await main.count():
        body_text = (await main.inner_text()).strip()
    if not body_text:
        body_text = (await page.locator("body").inner_text()).strip()
    return title, body_text


def trim_description(body_text: str, title: str, max_len: int = 4500) -> str:
    t = body_text.strip()
    if title and t.startswith(title):
        t = t[len(title) :].strip()
    return t[:max_len]


async def collect_image_urls(
    page: Page,
    base_url: str,
    *,
    domain_hints: tuple[str, ...],
    limit: int = 12,
) -> list[str]:
    """Собирает img[src], фильтруя по подстрокам домена/пути (нижний регистр)."""
    hints_js = list(domain_hints)
    raw: list[str | None] = await page.evaluate(
        """(hints) => {
          const out = [];
          const hl = hints.map(h => h.toLowerCase());
          for (const el of document.querySelectorAll('img[src]')) {
            const s = el.getAttribute('src');
            if (!s) continue;
            const l = s.toLowerCase();
            if (l.includes('logo') || l.includes('avatar') || l.includes('favicon')) continue;
            if (hl.some(h => l.includes(h))) out.push(s);
          }
          return out;
        }""",
        hints_js,
    )
    seen: set[str] = set()
    out: list[str] = []
    for s in raw:
        if not s:
            continue
        full = urljoin(base_url, s)
        if not full.lower().startswith("http"):
            continue
        if full in seen:
            continue
        seen.add(full)
        out.append(full)
        if len(out) >= limit:
            break
    return out


async def get_page_html(page: Page) -> str:
    return await page.content()
