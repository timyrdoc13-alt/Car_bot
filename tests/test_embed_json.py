import json
from pathlib import Path

from car_channel_bot.parsers.embed_json import (
    extract_json_ld_blocks,
    extract_next_data_json,
    images_from_json_ld,
    title_from_json_ld,
    usd_price_from_json_ld,
    usd_price_from_next_data,
)


def test_usd_price_from_json_ld_fixture() -> None:
    raw = Path(__file__).parent / "fixtures" / "jsonld_product_usd.json"
    block = json.loads(raw.read_text(encoding="utf-8"))
    assert usd_price_from_json_ld([block]) == "25000"
    assert title_from_json_ld([block]) == "Toyota Camry 2020"


def test_extract_next_data_and_usd() -> None:
    html = (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"ad":{"price":12000,"currency":"USD"}}}}'
        "</script></html>"
    )
    data = extract_next_data_json(html)
    assert data is not None
    assert usd_price_from_next_data(data) == "12000"


def test_json_ld_in_html() -> None:
    inner = json.dumps(
        {
            "@type": "Product",
            "name": "BMW X5",
            "offers": {"@type": "Offer", "price": "50000", "priceCurrency": "USD"},
        }
    )
    html = f'<html><script type="application/ld+json">{inner}</script></html>'
    blocks = extract_json_ld_blocks(html)
    assert usd_price_from_json_ld(blocks) == "50000"
    imgs = images_from_json_ld(
        [
            {
                "@type": "Product",
                "image": "https://cdn.example.com/a.jpg",
            }
        ]
    )
    assert "https://cdn.example.com/a.jpg" in imgs
