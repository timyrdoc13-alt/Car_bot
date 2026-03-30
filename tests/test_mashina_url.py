"""Юнит-тесты URL выдачи Mashina (без сети)."""

from __future__ import annotations

from urllib.parse import urlparse

from car_channel_bot.parsers.mashina_search_url import (
    build_mashina_list_url,
    finalize_mashina_list_url,
    path_brand_slug_from_path,
    path_search_brand_series,
)


def test_path_search_brand_series() -> None:
    assert path_search_brand_series("/search/audi/a5/") == ("audi", "a5")
    assert path_search_brand_series("/search/audi/all/") == ("audi", None)
    assert path_search_brand_series("/search/all/") == (None, None)
    assert path_brand_slug_from_path("/search/audi/a5/") == "audi"


def test_build_mashina_list_url_brand_only_in_path() -> None:
    url, meta = build_mashina_list_url(
        "https://m.mashina.kg/search/all/?region=all",
        {
            "year_min": 2018,
            "price_max": 30000,
            "model": "Toyota",
        },
    )
    assert "/search/toyota/all/" in url
    assert "brand=" not in url.lower()
    q = meta["query"]
    assert q["region"] == "all"
    assert q["year_from"] == "2018"
    assert q["price_to"] == "30000"
    assert q["currency"] == "2"
    assert q["sort_by"] == "upped_at desc"
    assert meta["path_brand_slug"] == "toyota"
    assert meta["path_series_slug"] is None


def test_build_mashina_list_url_brand_and_series_in_path() -> None:
    url, meta = build_mashina_list_url(
        "https://m.mashina.kg/search/all/?region=all",
        {
            "model": "Audi A5",
            "year_min": 2021,
            "price_max": 45000,
            "mashina_car_condition_multiple": [1, 2],
        },
    )
    assert "/search/audi/a5/" in url
    assert meta["path_brand_slug"] == "audi"
    assert meta["path_series_slug"] == "a5"
    q = meta["query"]
    assert q["year_from"] == "2021"
    assert q["price_to"] == "45000"
    assert q["car_condition_multiple"] == "1,2"


def test_build_mashina_list_url_custom_region_no_brand() -> None:
    _, meta = build_mashina_list_url(
        "https://m.mashina.kg/search/all/",
        {"region": "1", "model": "-"},
    )
    assert meta["path_brand_slug"] is None
    assert meta["query"]["region"] == "1"


def test_build_mashina_brand_when_no_model() -> None:
    url, meta = build_mashina_list_url(
        "https://m.mashina.kg/search/all/?region=all",
        {"model": "-", "brand": "BMW"},
    )
    assert "/search/bmw/all/" in url
    assert meta["path_brand_slug"] == "bmw"


def test_brand_key_plus_series_in_model_field() -> None:
    url, meta = build_mashina_list_url(
        "https://m.mashina.kg/search/all/?region=all",
        {"model": "X5", "brand": "BMW"},
    )
    assert "/search/bmw/x5/" in url
    assert meta["path_series_slug"] == "x5"


def test_legacy_query_brand_promoted_to_path() -> None:
    url, meta = build_mashina_list_url(
        "https://m.mashina.kg/search/all/?brand=audi&region=all",
        {},
    )
    p = urlparse(url)
    assert "/search/audi/all/" in p.path
    assert "brand=" not in url.lower()
    assert meta["path_brand_slug"] == "audi"


def test_preserves_custom_list_path_when_no_brand_in_filters() -> None:
    url, meta = build_mashina_list_url(
        "https://m.mashina.kg/search/audi/all/?currency=2&region=all",
        {"year_min": 2010},
    )
    assert "/search/audi/all/" in url
    assert meta["path_brand_slug"] == "audi"
    assert meta["query"]["year_from"] == "2010"


def test_finalize_moves_brand_query_to_path() -> None:
    url, meta = finalize_mashina_list_url(
        "https://m.mashina.kg/search/all/?brand=Audi&price_to=45000&region=all&year_from=2020",
    )
    assert "/search/audi/all/" in url
    assert "brand=" not in url.lower()
    assert meta["path_brand_slug"] == "audi"
    assert "currency=2" in url
    assert "sort_by=" in url


def test_preserves_custom_series_path() -> None:
    url, meta = build_mashina_list_url(
        "https://m.mashina.kg/search/audi/a5/?currency=2",
        {"price_max": 40000},
    )
    assert "/search/audi/a5/" in url
    assert meta["path_series_slug"] == "a5"
    assert meta["query"]["price_to"] == "40000"
