"""Единые ключи `fields` для LLM (маппинг в адаптерах)."""

from __future__ import annotations

# Используйте только эти ключи в ListingDetail.fields (+ произвольные доп. при необходимости).
TITLE = "Заголовок"
YEAR = "Год"
MILEAGE = "Пробег"
ENGINE = "Двигатель"
GEARBOX = "Коробка"
DRIVE = "Привод"
REGION = "Регион"
PRICE_USD = "Цена USD"
PRICE_RAW = "Цена (как в объявлении)"
SOURCE = "Источник"


def build_standard_fields(
    *,
    source_label: str,
    title: str | None = None,
    year: str | None = None,
    mileage: str | None = None,
    engine: str | None = None,
    gearbox: str | None = None,
    drive: str | None = None,
    region: str | None = None,
    price_usd: str | None = None,
    price_raw: str | None = None,
    extras: dict[str, str | None] | None = None,
) -> dict[str, str | None]:
    """Собирает словарь для LLM; пустые значения опускаются позже в build_prompt_from_parsed_fields."""
    out: dict[str, str | None] = {
        SOURCE: source_label,
        TITLE: title,
        YEAR: year,
        MILEAGE: mileage,
        ENGINE: engine,
        GEARBOX: gearbox,
        DRIVE: drive,
        REGION: region,
        PRICE_USD: price_usd,
        PRICE_RAW: price_raw,
    }
    if extras:
        for k, v in extras.items():
            out[k] = v
    return {k: v for k, v in out.items() if v is not None and str(v).strip() != ""}


def pick_price_usd(*candidates: str | None) -> str | None:
    """Приоритет: первый непустой нормализованный USD-строка (только цифры)."""
    for c in candidates:
        if not c:
            continue
        digits = "".join(ch for ch in str(c) if ch.isdigit())
        if digits:
            return digits
    return None
