"""Построение URL мобильной выдачи Mashina.kg: /search/{brand}/all/ или /search/{brand}/{model}/."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# Примеры UI:
# https://m.mashina.kg/search/audi/all/?currency=2&region=all&sort_by=upped_at%20desc
# https://m.mashina.kg/search/audi/a5/?car_condition_multiple=1%2C2&currency=2&price_to=...
DEFAULT_CURRENCY = "2"  # USD
DEFAULT_SORT_BY = "upped_at desc"


def path_search_brand_series(path: str) -> tuple[str | None, str | None]:
    """
    /search/audi/a5/ → ('audi', 'a5')
    /search/audi/all/ → ('audi', None)
    /search/all/ → (None, None)
    """
    segs = [s for s in (path or "").strip("/").split("/") if s]
    if len(segs) < 2 or segs[0].lower() != "search":
        return None, None
    if len(segs) == 2 and segs[1].lower() == "all":
        return None, None
    if len(segs) == 2:
        return segs[1].lower(), None
    if len(segs) >= 3:
        b = segs[1].lower()
        tail = segs[2].lower()
        if tail == "all":
            return b, None
        return b, tail
    return None, None


def path_brand_slug_from_path(path: str) -> str | None:
    """Первый сегмент марки после /search/ — для доверия выдаче без substring-фильтра."""
    b, _ = path_search_brand_series(path)
    return b


def _slug(raw: str) -> str:
    """Slug сегмента пути (марка или модель): Toyota → toyota, A4 allroad → a4-allroad."""
    s = raw.strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-]", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def _brand_series_raw_from_filters(filters: dict[str, Any]) -> tuple[str | None, str | None]:
    """
    (марка как ввод, модель/серия как ввод или None → тогда в URL сегмент all).
    """
    explicit_series = (filters.get("mashina_series") or filters.get("series") or "").strip()
    brand_key = (filters.get("brand") or "").strip()
    model_line = (filters.get("model") or "").strip()
    if model_line == "-":
        model_line = ""

    brand_raw: str | None = None
    series_raw: str | None = explicit_series or None

    if brand_key and brand_key != "-":
        brand_raw = brand_key
        if not series_raw and model_line and model_line.lower() != brand_key.lower():
            series_raw = model_line
    elif model_line:
        parts = model_line.split(None, 1)
        if len(parts) == 2:
            brand_raw = parts[0]
            series_raw = series_raw or parts[1]
        else:
            brand_raw = parts[0]

    if brand_raw == "-":
        brand_raw = None

    return brand_raw, series_raw


def finalize_mashina_list_url(url: str) -> tuple[str, dict[str, Any]]:
    """
    Последняя нормализация перед goto: ?brand=Audi на /search/all/ → /search/audi/all/,
    плюс дефолты currency/sort_by (защита от старого кэша и ручных list_url).
    """
    raw = (url or "").strip()
    if not raw:
        return url, {
            "query": {},
            "path": "/search/all/",
            "path_brand_slug": None,
            "path_series_slug": None,
        }
    p = urlparse(raw if raw.startswith("http") else f"https://{raw}")
    if "mashina.kg" not in (p.netloc or "").lower():
        q0 = dict(parse_qsl(p.query, keep_blank_values=True))
        return url, {
            "query": q0,
            "path": p.path or "",
            "path_brand_slug": None,
            "path_series_slug": None,
        }

    path = p.path if p.path and p.path != "/" else "/search/all/"
    if "/search" not in path:
        path = "/search/all/"
    if not path.endswith("/"):
        path = path + "/"

    q = dict(parse_qsl(p.query, keep_blank_values=True))

    if path_brand_slug_from_path(path) is None and q.get("brand"):
        leg = _slug(str(q["brand"]))
        if leg:
            path = f"/search/{leg}/all/"
            q.pop("brand", None)

    if "currency" not in q:
        q["currency"] = DEFAULT_CURRENCY
    if "sort_by" not in q:
        q["sort_by"] = DEFAULT_SORT_BY

    pb, ps = path_search_brand_series(path)
    query_s = urlencode(sorted(q.items()))
    final = urlunparse(("https", "m.mashina.kg", path, "", query_s, ""))
    meta: dict[str, Any] = {
        "query": dict(q),
        "path": path,
        "path_brand_slug": pb,
        "path_series_slug": ps,
    }
    return final, meta


def _merge_car_condition(q: dict[str, str], filters: dict[str, Any]) -> None:
    cc = filters.get("mashina_car_condition_multiple")
    if cc is None:
        cc = filters.get("car_condition_multiple")
    if cc is None:
        return
    if isinstance(cc, (list, tuple)):
        q["car_condition_multiple"] = ",".join(str(x) for x in cc)
    else:
        q["car_condition_multiple"] = str(cc)


def build_mashina_list_url(default_url: str, filters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """
    /search/{brand}/all/ или /search/{brand}/{model}/ + query как в браузере.
    """
    raw = (default_url or "").strip()
    p = urlparse(raw if raw.startswith("http") else f"https://{raw}")
    path = p.path if p.path and p.path != "/" else "/search/all/"
    if "/search" not in path:
        path = "/search/all/"
    if not path.endswith("/"):
        path = path + "/"

    q: dict[str, str] = dict(parse_qsl(p.query, keep_blank_values=True))

    brand_raw, series_raw = _brand_series_raw_from_filters(filters)
    brand_slug = _slug(brand_raw) if brand_raw else ""
    series_slug = _slug(series_raw) if series_raw else ""

    if brand_slug:
        if series_slug:
            path = f"/search/{brand_slug}/{series_slug}/"
        else:
            path = f"/search/{brand_slug}/all/"
        q.pop("brand", None)
    elif brand_raw:
        path = "/search/all/"
        q["brand"] = brand_raw.strip()

    # Старые закладки: /search/all/?brand=audi → /search/audi/all/
    if path_brand_slug_from_path(path) is None and q.get("brand"):
        leg = _slug(str(q["brand"]))
        if leg:
            path = f"/search/{leg}/all/"
            q.pop("brand", None)

    region = filters.get("region")
    if region is not None and str(region).strip():
        q["region"] = str(region).strip()
    elif "region" not in q:
        q["region"] = "all"

    year_min = int(filters.get("year_min") or 0)
    if year_min > 0:
        q["year_from"] = str(year_min)
    price_max = int(filters.get("price_max") or 0)
    if price_max > 0:
        q["price_to"] = str(price_max)

    _merge_car_condition(q, filters)

    if "currency" not in q:
        q["currency"] = str(filters.get("mashina_currency") or DEFAULT_CURRENCY)
    if "sort_by" not in q:
        q["sort_by"] = str(filters.get("mashina_sort_by") or DEFAULT_SORT_BY)

    host = "m.mashina.kg"
    query = urlencode(sorted(q.items()))
    final = urlunparse(("https", host, path, "", query, ""))
    return finalize_mashina_list_url(final)


def trace_step(
    sink: list[dict[str, Any]] | None,
    *,
    step: str,
    expected: str,
    got: Any,
    ok: bool | None = None,
    note: str | None = None,
) -> None:
    if sink is None:
        return
    row: dict[str, Any] = {
        "step": step,
        "expected": expected,
        "got": got,
    }
    if ok is not None:
        row["ok"] = ok
    if note:
        row["note"] = note
    sink.append(row)
