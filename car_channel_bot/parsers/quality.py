"""Quality gate для ListingDetail перед вызовом LLM."""

from __future__ import annotations

from car_channel_bot.parsers import fields as F
from car_channel_bot.parsers.base import ListingDetail


def validate_listing_detail(
    detail: ListingDetail,
    *,
    require_photos: bool = False,
) -> tuple[bool, str]:
    """
    Returns (ok, reason).
    Минимум: непустой title ИЛИ ≥2 заполненных поля в fields (кроме Источник).
    Опционально: хотя бы одно фото.
    """
    t = (detail.title or "").strip()
    title_ok = bool(t) and not t.startswith("Объявление ") and len(t) >= 3

    filled = sum(
        1
        for k, v in detail.fields.items()
        if k != F.SOURCE and v and str(v).strip()
    )
    fields_ok = filled >= 2

    if not title_ok and not fields_ok:
        return False, "no_title_and_few_fields"

    if require_photos and not detail.image_urls:
        return False, "no_photos"

    if not (detail.description or "").strip() and not fields_ok:
        return False, "empty_description_and_few_fields"

    return True, "ok"
