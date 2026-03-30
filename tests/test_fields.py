from car_channel_bot.parsers import fields as F


def test_pick_price_usd() -> None:
    assert F.pick_price_usd(None, " 12 000 ", "bad") == "12000"
    assert F.pick_price_usd(None, None) is None


def test_build_standard_fields() -> None:
    m = F.build_standard_fields(
        source_label="x",
        title="A",
        year="2020",
        price_usd="100",
    )
    assert m[F.SOURCE] == "x"
    assert m[F.TITLE] == "A"
    assert m[F.YEAR] == "2020"
    assert m[F.PRICE_USD] == "100"
