"""Lalafo.kg listings — Playwright; JSON-LD / __NEXT_DATA__ затем DOM."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urldefrag, urlparse, urlunparse

import structlog

from car_channel_bot.config.settings import Settings
from car_channel_bot.parsers import common as C
from car_channel_bot.parsers import embed_json as EJ
from car_channel_bot.parsers import fields as LF
from car_channel_bot.parsers.base import ListingDetail, ListingRef
from car_channel_bot.parsers.playwright_shared import shared_chromium

log = structlog.get_logger()

_AD_RE = re.compile(
    r"https://lalafo\.kg/[^?\s\"']+/ads/[^?\s\"']+-id-(\d+)(?:\?[^\s\"']*)?",
    re.I,
)


def _normalize_ad_url(url: str) -> str:
    base, _frag = urldefrag(url.strip())
    p = urlparse(base)
    clean = urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
    return clean


class LalafoListingSource:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._delay = max(0.5, float(settings.lalafo_request_delay_seconds))

    def _search_url(self, filters: dict[str, Any]) -> str:
        u = filters.get("list_url") or self._settings.lalafo_search_url
        return str(u).strip()

    async def search(self, filters: dict[str, Any]) -> list[ListingRef]:
        limit = int(filters.get("limit", 10))
        limit = max(1, min(limit, 30))
        list_url = self._search_url(filters)

        browser = await shared_chromium(headless=self._settings.playwright_headless)
        ctx = await browser.new_context(user_agent=C.DEFAULT_USER_AGENT, locale="ru-RU")
        try:
            page = await ctx.new_page()
            await page.goto(list_url, wait_until="load", timeout=90_000)
            try:
                await page.wait_for_selector('a[href*="-id-"]', timeout=35_000)
            except Exception:
                log.warning("lalafo_search_no_links_selector_timeout")
            await C.scroll_page(page, rounds=6, step_px=1400, pause_s=0.5)
            await C.delay_after_navigation(page, self._delay)
            hrefs: list[str] = await page.evaluate(
                """() => {
                      const out = new Set();
                      for (const a of document.querySelectorAll('a[href]')) {
                        const h = a.href;
                        if (h && h.includes('-id-')) out.add(h);
                      }
                      return [...out];
                    }"""
            )
        finally:
            await ctx.close()

        seen: set[str] = set()
        refs: list[ListingRef] = []
        for href in hrefs:
            if not _AD_RE.search(href):
                continue
            norm = _normalize_ad_url(href)
            if norm in seen:
                continue
            seen.add(norm)
            refs.append(ListingRef(url=norm, source="lalafo.kg"))
            if len(refs) >= limit:
                break

        log.info(
            "parser_search_done",
            source="lalafo",
            refs_found=len(hrefs),
            refs_kept=len(refs),
            list_url=list_url,
        )
        return refs

    async def fetch_detail(self, ref: ListingRef) -> ListingDetail:
        browser = await shared_chromium(headless=self._settings.playwright_headless)
        ctx = await browser.new_context(user_agent=C.DEFAULT_USER_AGENT, locale="ru-RU")
        try:
            page = await ctx.new_page()
            await page.goto(ref.url, wait_until="domcontentloaded", timeout=90_000)
            await C.delay_after_navigation(page, self._delay)

            html = await C.get_page_html(page)
            next_data = EJ.extract_next_data_json(html)
            ld_blocks = EJ.extract_json_ld_blocks(html)

            price_embed = EJ.usd_price_from_json_ld(ld_blocks)
            if next_data and not price_embed:
                price_embed = EJ.usd_price_from_next_data(next_data)
            title_embed = EJ.title_from_json_ld(ld_blocks)

            title_dom, body_text = await C.extract_title_and_body(page)
            title = (title_embed or title_dom or "").strip()
            price_usd = LF.pick_price_usd(
                price_embed,
                C.extract_usd_price_from_text(body_text),
            )

            img_ld = EJ.images_from_json_ld(ld_blocks, limit=12)
            img_dom = await C.collect_image_urls(
                page,
                ref.url,
                domain_hints=("lalafo", "static", "cdn"),
                limit=12,
            )
            image_urls = _merge_urls(img_ld, img_dom, 12)
        finally:
            await ctx.close()

        desc = C.trim_description(body_text, title_dom)
        field_map = LF.build_standard_fields(
            source_label="lalafo.kg",
            title=title or None,
            price_usd=price_usd,
        )
        return ListingDetail(
            url=ref.url,
            title=title or "Объявление Lalafo",
            description=desc,
            image_urls=image_urls,
            fields=field_map,
        )


def _merge_urls(a: list[str], b: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in a + b:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= limit:
            break
    return out
