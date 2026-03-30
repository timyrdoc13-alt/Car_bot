from car_channel_bot.parsers import fields as F
from car_channel_bot.parsers.base import ListingDetail
from car_channel_bot.parsers.quality import validate_listing_detail


def test_quality_ok_with_fields() -> None:
    d = ListingDetail(
        url="https://x",
        title="Объявление Lalafo",
        description="",
        fields={
            F.SOURCE: "t",
            F.TITLE: "Toyota",
            F.PRICE_USD: "10000",
        },
    )
    ok, reason = validate_listing_detail(d)
    assert ok and reason == "ok"


def test_quality_fail_empty() -> None:
    d = ListingDetail(
        url="https://x",
        title="Объявление Lalafo",
        description="",
        fields={F.SOURCE: "t"},
    )
    ok, reason = validate_listing_detail(d)
    assert not ok


def test_quality_require_photos() -> None:
    d = ListingDetail(
        url="https://x",
        title="Real title",
        description="text",
        image_urls=[],
        fields={F.SOURCE: "t", F.PRICE_USD: "1"},
    )
    ok, _ = validate_listing_detail(d, require_photos=True)
    assert not ok
