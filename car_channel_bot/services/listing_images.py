"""Отбор URL реальных фото объявления (без иконок/промо Mashina и SVG)."""

from __future__ import annotations

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


def _path_looks_like_photo(path: str) -> bool:
    p = (path or "").split("?", 1)[0].lower()
    return any(p.endswith(s) for s in _IMAGE_SUFFIXES)


def _is_likely_vehicle_photo_url(url: str) -> bool:
    url = (url or "").strip()
    if not url.lower().startswith("http"):
        return False
    low = url.lower()
    if any(bad in low for bad in _DENY_SUBSTRINGS):
        return False
    if low.endswith(".svg") or ".svg?" in low:
        return False
    parsed = urlparse(low)
    path = parsed.path or ""
    # Галерея Mashina
    if "tachka/images" in path or "/tachka/images" in low:
        return True
    if "mashina.kg" in low:
        return _path_looks_like_photo(path) and "/bundles/" not in low
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
