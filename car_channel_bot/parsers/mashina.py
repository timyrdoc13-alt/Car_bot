"""Mashina.kg mobile — Playwright; JSON-LD / __NEXT_DATA__ затем DOM."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import structlog
from playwright.async_api import async_playwright

from car_channel_bot.config.settings import Settings
from car_channel_bot.parsers import common as C
from car_channel_bot.parsers import embed_json as EJ
from car_channel_bot.parsers import fields as LF
from car_channel_bot.parsers.base import ListingDetail, ListingRef
from car_channel_bot.parsers.mashina_search_url import (
    build_mashina_list_url,
    finalize_mashina_list_url,
    trace_step,
)

log = structlog.get_logger()


def _normalize_mashina_url(url: str) -> str:
    raw = url.strip().split("?", maxsplit=1)[0]
    if raw.startswith("//"):
        raw = "https:" + raw
    if not raw.lower().startswith("http"):
        raw = urljoin("https://m.mashina.kg/", raw)
    p = urlparse(raw)
    if "mashina.kg" not in (p.netloc or "").lower():
        return raw
    path = p.path or ""
    return f"https://m.mashina.kg{path}"


def _is_listing_details_url(url: str) -> bool:
    u = url.lower()
    if "/details/" not in u or "mashina.kg" not in u:
        return False
    tail = u.split("/details/", 1)[-1].split("?")[0].strip("/")
    if len(tail) < 12:
        return False
    skip = {"login", "register", "help", "search", "all"}
    first = tail.split("/")[0].split("-")[0]
    return first not in skip


def _trace_sink(filters: dict[str, Any]) -> list[dict[str, Any]] | None:
    t = filters.get("_trace")
    return t if isinstance(t, list) else None


def _with_page(url: str, page_num: int) -> str:
    """Ставит ?page=N для пагинации Mashina mobile."""
    p = urlparse(url)
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    if page_num <= 1:
        q.pop("page", None)
    else:
        q["page"] = str(page_num)
    return urlunparse((p.scheme, p.netloc, p.path, "", urlencode(sorted(q.items())), ""))


class MashinaListingSource:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._delay = max(0.5, float(settings.mashina_request_delay_seconds))
        self._trace_sink: list[dict[str, Any]] | None = None

    def attach_debug_trace(self, sink: list[dict[str, Any]] | None) -> None:
        """Для мониторинга: трассировка без filters['_trace']."""
        self._trace_sink = sink

    def _search_url(self, filters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        base = filters.get("list_url") or self._settings.mashina_search_url
        return build_mashina_list_url(str(base).strip(), filters)

    async def search(self, filters: dict[str, Any]) -> list[ListingRef]:
        limit = int(filters.get("limit", 10))
        limit = max(1, min(limit, 30))
        # Собираем расширенный пул: после дедупа в БД могут отвалиться первые N ссылок.
        collect_target = int(filters.get("mashina_collect_target") or max(limit * 4, 40))
        collect_target = max(limit, min(collect_target, 160))
        pages = int(filters.get("mashina_pages") or max(2, min(8, (collect_target + 19) // 20)))
        pages = max(1, min(pages, 12))
        list_url, applied = self._search_url(filters)
        list_url, applied = finalize_mashina_list_url(list_url)
        applied_qs = applied.get("query") or {}
        path_brand_slug = applied.get("path_brand_slug")
        path_series_slug = applied.get("path_series_slug")
        model_filter = (filters.get("model") or "").strip().lower()
        sink = _trace_sink(filters)
        if sink is not None:
            self._trace_sink = sink
        trace = self._trace_sink

        trace_step(
            trace,
            step="build_list_url",
            expected="/search/{brand}/all/ или /search/all/ + region, year_from, price_to, currency, sort_by",
            got={
                "url": list_url,
                "query": applied_qs,
                "path_brand_slug": path_brand_slug,
                "path_series_slug": path_series_slug,
                "pages": pages,
                "collect_target": collect_target,
            },
            ok=True,
        )

        use_iphone = bool(filters.get("mashina_use_iphone_ua", False))
        ua = C.IPHONE_SAFARI_UA if use_iphone else C.MOBILE_USER_AGENT
        trace_step(
            trace,
            step="user_agent",
            expected="mobile UA (Pixel или iPhone по флагу)",
            got={"iphone": use_iphone, "ua_prefix": ua[:48] + "…"},
        )

        scroll_pause = max(self._delay, 1.5)
        max_rounds = int(filters.get("mashina_scroll_max_rounds") or 14)
        stable_needed = int(filters.get("mashina_scroll_stable_needed") or 2)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self._settings.playwright_headless)
            try:
                ctx = await browser.new_context(
                    user_agent=ua,
                    locale="ru-RU",
                    viewport={"width": 390, "height": 844},
                )
                page = await ctx.new_page()
                hrefs: list[str] = []
                href_seen: set[str] = set()
                page_probe: list[dict[str, Any]] = []
                for page_num in range(1, pages + 1):
                    paged_url = _with_page(list_url, page_num)
                    resp = await page.goto(paged_url, wait_until="load", timeout=90_000)
                    final_url = page.url
                    status = resp.status if resp else None
                    if page_num == 1:
                        trace_step(
                            trace,
                            step="goto_list",
                            expected="HTTP 200, редирект на m.mashina.kg",
                            got={"status": status, "final_url": final_url},
                            ok=status == 200 if status is not None else None,
                        )
                    details_ok = False
                    try:
                        await page.wait_for_selector('a[href*="/details/"]', timeout=35_000)
                        details_ok = True
                    except Exception:
                        log.warning("mashina_search_no_details_timeout", page=page_num)
                    if page_num == 1:
                        trace_step(
                            trace,
                            step="wait_details_links",
                            expected="есть a[href*=\"/details/\"] на выдаче",
                            got=details_ok,
                            ok=details_ok,
                        )
                    if page_num == 1:
                        ad_item_ok = False
                        try:
                            await page.wait_for_selector('[data-testid="ad-item"]', timeout=4_000)
                            ad_item_ok = True
                        except Exception:
                            pass
                        trace_step(
                            trace,
                            step="wait_ad_item_optional",
                            expected="опционально [data-testid=\"ad-item\"]",
                            got=ad_item_ok,
                            note="не критично если нет",
                        )

                    rounds, final_h = await C.scroll_until_height_stable(
                        page,
                        step_px=1400,
                        pause_s=scroll_pause,
                        max_rounds=max_rounds,
                        stable_needed=stable_needed,
                    )
                    if page_num == 1:
                        trace_step(
                            trace,
                            step="scroll_infinite",
                            expected="scrollHeight стабилизируется после подгрузки карточек",
                            got={"rounds": rounds, "scroll_height": final_h, "pause_s": scroll_pause},
                        )
                    await C.scroll_page(page, rounds=3, step_px=900, pause_s=min(0.6, scroll_pause))
                    await C.delay_after_navigation(page, self._delay)

                    page_hrefs: list[str] = await page.evaluate(
                        """() => {
                          const out = new Set();
                          for (const a of document.querySelectorAll('a[href*="/details/"]')) {
                            if (a.href) out.add(a.href);
                          }
                          return [...out];
                        }"""
                    )
                    added = 0
                    for h in page_hrefs:
                        if h in href_seen:
                            continue
                        href_seen.add(h)
                        hrefs.append(h)
                        added += 1
                    page_probe.append(
                        {"page": page_num, "url": paged_url, "status": status, "hrefs": len(page_hrefs), "new": added}
                    )
                    if len(hrefs) >= collect_target:
                        break
            finally:
                await browser.close()

        trace_step(
            trace,
            step="collect_hrefs_dom",
            expected="> 0 уникальных /details/ после скролла (несколько страниц)",
            got={"count": len(hrefs), "sample": hrefs[:3], "pages_probe": page_probe},
            ok=len(hrefs) > 0,
        )

        # Если марка уже в пути /search/audi/all/, доверяем выдаче сайта (без фильтра по подстроке в URL).
        use_url_substring_model_filter = bool(
            model_filter and model_filter != "-" and path_brand_slug is None
        )

        seen: set[str] = set()
        refs: list[ListingRef] = []
        for href in hrefs:
            if not _is_listing_details_url(href):
                continue
            norm = _normalize_mashina_url(href)
            if norm in seen:
                continue
            seen.add(norm)
            if use_url_substring_model_filter and model_filter not in norm.lower():
                continue
            refs.append(ListingRef(url=norm, source="mashina.kg"))
            if len(refs) >= collect_target:
                break

        trace_step(
            trace,
            step="filter_model_limit",
            expected=f"пул до {collect_target} ссылок (для дедупа/вариативности), лимит UI={limit}",
            got={
                "kept": len(refs),
                "limit": limit,
                "collect_target": collect_target,
                "model_filter": model_filter or "(none)",
                "path_brand_slug": path_brand_slug,
                "substring_filter": use_url_substring_model_filter,
            },
            ok=len(refs) > 0,
        )

        log.info(
            "parser_search_done",
            source="mashina",
            refs_found=len(hrefs),
            refs_kept=len(refs),
            list_url=list_url,
        )
        return refs

    async def fetch_detail(self, ref: ListingRef) -> ListingDetail:
        trace = self._trace_sink
        title_dom = ""
        body_text = ""
        title = ""
        price_usd: str | None = None
        image_urls: list[str] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self._settings.playwright_headless)
            try:
                ctx = await browser.new_context(
                    user_agent=C.MOBILE_USER_AGENT,
                    locale="ru-RU",
                    viewport={"width": 390, "height": 844},
                )
                page = await ctx.new_page()
                trace_step(
                    trace,
                    step="detail_goto",
                    expected="страница объявления загрузилась",
                    got={"url": ref.url},
                )
                resp = await page.goto(ref.url, wait_until="domcontentloaded", timeout=90_000)
                status = resp.status if resp else None
                trace_step(
                    trace,
                    step="detail_response",
                    expected="HTTP 200",
                    got={"status": status, "final_url": page.url},
                    ok=status == 200 if status is not None else None,
                )
                await C.delay_after_navigation(page, self._delay)

                html = await C.get_page_html(page)
                next_data = EJ.extract_next_data_json(html)
                ld_blocks = EJ.extract_json_ld_blocks(html)

                trace_step(
                    trace,
                    step="detail_embed_parse",
                    expected="__NEXT_DATA__ и/или JSON-LD",
                    got={
                        "next_data_keys_sample": list(next_data.keys())[:8] if isinstance(next_data, dict) else None,
                        "json_ld_blocks": len(ld_blocks),
                    },
                    ok=bool(next_data) or len(ld_blocks) > 0,
                )

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

                trace_step(
                    trace,
                    step="detail_fields",
                    expected="title и price_usd из embed или DOM",
                    got={
                        "title_len": len(title),
                        "price_usd": price_usd,
                        "body_len": len(body_text),
                    },
                    ok=bool(title.strip()),
                )

                img_ld = EJ.images_from_json_ld(ld_blocks, limit=12)
                img_dom = await C.collect_image_urls(
                    page,
                    ref.url,
                    domain_hints=("mashina", "cdn", "photo", "product", "upload"),
                    limit=12,
                )
                image_urls = _merge_urls(img_ld, img_dom, 12)
                trace_step(
                    trace,
                    step="detail_images",
                    expected="1+ картинок из LD или DOM",
                    got={"count": len(image_urls), "json_ld": len(img_ld), "dom": len(img_dom)},
                    ok=len(image_urls) > 0,
                )
            finally:
                await browser.close()

        desc = C.trim_description(body_text, title_dom)
        field_map = LF.build_standard_fields(
            source_label="mashina.kg",
            title=title or None,
            price_usd=price_usd,
        )
        return ListingDetail(
            url=ref.url,
            title=title or "Объявление Mashina.kg",
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
