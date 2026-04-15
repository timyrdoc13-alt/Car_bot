"""Извлечение структурированных данных из HTML: __NEXT_DATA__, JSON-LD."""

from __future__ import annotations

import json
import re
from typing import Any

_NEXT_DATA_RE = re.compile(
    r'<script[^>]*\bid=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_JSON_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def extract_next_data_json(html: str) -> dict[str, Any] | None:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return None
    raw = m.group(1).strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def extract_json_ld_blocks(html: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in _JSON_LD_RE.finditer(html):
        chunk = m.group(1).strip()
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            out.extend(x for x in data if isinstance(x, dict))
        elif isinstance(data, dict):
            out.append(data)
    return out


def _normalize_money_digits(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value <= 0:
            return None
        return str(int(value))
    s = str(value).strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits or None


def _currency_usd(cur: Any) -> bool:
    if cur is None:
        return False
    u = str(cur).upper().replace(" ", "")
    return u in ("USD", "US$", "US")


def usd_price_from_json_ld(blocks: list[dict[str, Any]]) -> str | None:
    """Ищет schema.org Offer / price с валютой USD."""
    for block in blocks:
        found = _walk_json_ld_for_usd(block)
        if found:
            return found
    return None


def _walk_json_ld_for_usd(obj: Any) -> str | None:
    if isinstance(obj, dict):
        offers = obj.get("offers")
        if offers is not None:
            for item in _as_offer_list(offers):
                price = item.get("price") or item.get("value")
                cur = item.get("priceCurrency")
                if _currency_usd(cur):
                    d = _normalize_money_digits(price)
                    if d:
                        return d
                spec = item.get("priceSpecification")
                if isinstance(spec, dict):
                    d = _normalize_money_digits(spec.get("price"))
                    if d and _currency_usd(spec.get("priceCurrency")):
                        return d
        if obj.get("@type") in ("Offer", "AggregateOffer", ["Offer"], ["AggregateOffer"]):
            price = obj.get("price") or obj.get("lowPrice") or obj.get("highPrice")
            cur = obj.get("priceCurrency")
            if _currency_usd(cur):
                d = _normalize_money_digits(price)
                if d:
                    return d
        for v in obj.values():
            r = _walk_json_ld_for_usd(v)
            if r:
                return r
    elif isinstance(obj, list):
        for x in obj:
            r = _walk_json_ld_for_usd(x)
            if r:
                return r
    return None


def _as_offer_list(offers: Any) -> list[dict[str, Any]]:
    if isinstance(offers, dict):
        return [offers]
    if isinstance(offers, list):
        return [x for x in offers if isinstance(x, dict)]
    return []


def _ld_type_set(d: dict[str, Any]) -> set[str]:
    t = d.get("@type")
    if t is None:
        return set()
    if isinstance(t, list):
        return {str(x) for x in t if x is not None}
    return {str(t)}


# Не лезем в блоки «похожие», каталоги и служебные схемы — иначе подтягиваются чужие фото.
_LD_SKIP_WHOLE_SUBTREE_TYPES = frozenset(
    {
        "ItemList",
        "OfferCatalog",
        "FAQPage",
        "BreadcrumbList",
        "Question",
        "Answer",
        "WebPage",
        "SearchResultsPage",
    }
)
_LD_SKIP_RECURSE_KEYS = frozenset(
    {
        "itemListElement",
        "relatedProducts",
        "relatedAds",
        "related",
        "similarListings",
        "similar",
        "featuredListings",
        "recommendedListings",
        "recommended",
        "breadcrumb",
    }
)


def images_from_json_ld(blocks: list[dict[str, Any]], limit: int = 12) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for block in blocks:
        _collect_images(block, seen, out, limit)
        if len(out) >= limit:
            break
    return out[:limit]


def _collect_images(obj: Any, seen: set[str], out: list[str], limit: int) -> None:
    if len(out) >= limit:
        return
    if isinstance(obj, dict):
        if _ld_type_set(obj) & _LD_SKIP_WHOLE_SUBTREE_TYPES:
            return
        if obj.get("@type") in ("ImageObject", ["ImageObject"]):
            u = obj.get("url") or obj.get("contentUrl")
            if isinstance(u, str) and u.startswith("http") and u not in seen:
                seen.add(u)
                out.append(u)
        img = obj.get("image")
        if isinstance(img, str) and img.startswith("http") and img not in seen:
            seen.add(img)
            out.append(img)
        elif isinstance(img, list):
            for x in img:
                if isinstance(x, str) and x.startswith("http") and x not in seen:
                    seen.add(x)
                    out.append(x)
                elif isinstance(x, dict):
                    _collect_images(x, seen, out, limit)
        for k, v in obj.items():
            if k in _LD_SKIP_RECURSE_KEYS or k == "image":
                continue
            _collect_images(v, seen, out, limit)
    elif isinstance(obj, list):
        for x in obj:
            _collect_images(x, seen, out, limit)


def usd_price_from_next_data(data: dict[str, Any]) -> str | None:
    """Рекурсивный поиск пар currency+price в дереве Next.js."""
    return _walk_next_for_usd(data)


def _walk_next_for_usd(obj: Any) -> str | None:
    if isinstance(obj, dict):
        cur = obj.get("currency") or obj.get("priceCurrency") or obj.get("currencyCode")
        price = obj.get("price") or obj.get("amount") or obj.get("usdPrice")
        if price is not None and _currency_usd(cur):
            d = _normalize_money_digits(price)
            if d:
                return d
        if isinstance(price, (int, float)) and cur is None:
            pass
        for k, v in obj.items():
            if k in ("props", "pageProps", "query", "ad", "listing", "product", "data"):
                r = _walk_next_for_usd(v)
                if r:
                    return r
        for v in obj.values():
            r = _walk_next_for_usd(v)
            if r:
                return r
    elif isinstance(obj, list):
        for x in obj:
            r = _walk_next_for_usd(x)
            if r:
                return r
    return None


def title_from_json_ld(blocks: list[dict[str, Any]]) -> str | None:
    for b in blocks:
        if b.get("@type") in ("Product", "Vehicle", ["Product"], ["Vehicle"]):
            name = b.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return None
