"""Отбор URL реальных фото объявления (без иконок/промо Mashina и SVG)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# SVG и UI-ассеты Mashina попадают в DOM — Telegram даёт IMAGE_PROCESS_FAILED на альбомах.
_DENY_SUBSTRINGS: tuple[str, ...] = (
    "/bundles/",
    "product-promo",
    "product-vip-listing",
    "product-color-listing",
    "product-autoup-listing",
    "product-urgent-listing",
    "product-premium-listing",
    "/img/product",
    "listing.svg",
    "favicon",
    "avatar",
    "placeholder",
    "logo.svg",
    "/logo",
)

_IMAGE_SUFFIXES: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".webp")
_SMALL_VARIANT_RE = re.compile(r"_(\d{2,4})x(\d{2,4})(?:\.[a-z0-9]+)?(?:\?|$)", re.I)


def _path_looks_like_photo(path: str) -> bool:
    p = (path or "").split("?", 1)[0].lower()
    return any(p.endswith(s) for s in _IMAGE_SUFFIXES)


def _is_too_small_variant(url: str) -> bool:
    m = _SMALL_VARIANT_RE.search(url)
    if not m:
        return False
    try:
        w = int(m.group(1))
        h = int(m.group(2))
    except (TypeError, ValueError):
        return False
    return w <= 200 and h <= 200


def _is_likely_vehicle_photo_url(url: str) -> bool:
    url = (url or "").strip()
    if not url.lower().startswith("http"):
        return False
    low = url.lower()
    if any(bad in low for bad in _DENY_SUBSTRINGS):
        return False
    if _is_too_small_variant(low):
        return False
    if low.endswith(".svg") or ".svg?" in low:
        return False
    parsed = urlparse(low)
    path = parsed.path or ""
    # Галерея Mashina
    if "tachka/images" in path or "/tachka/images" in low:
        if "/tachka/images//users/" in low or "/tachka/images/users/" in low:
            return False
        return True
    if "mashina.kg" in low:
        # Mashina UI may include non-listing images from same domain; keep only explicit photo paths.
        return "/tachka/images" in low and not (
            "/tachka/images//users/" in low or "/tachka/images/users/" in low
        )
    # Прочие источники: только явные растровые расширения
    return _path_looks_like_photo(path)


def sanitize_vehicle_image_urls(
    urls: list[str],
    *,
    max_photos: int = 6,
) -> list[str]:
    """Уникальные URL в исходном порядке, только похожие на фото машины, не больше max_photos."""
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if not u or u in seen:
            continue
        if not _is_likely_vehicle_photo_url(u):
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= max_photos:
            break
    return out
