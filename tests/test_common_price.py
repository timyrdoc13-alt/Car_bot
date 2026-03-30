from car_channel_bot.parsers.common import extract_usd_price_from_text


def test_extract_usd_dollar_prefix() -> None:
    assert extract_usd_price_from_text("Цена $ 24 000 и сомы") == "24000"


def test_extract_usd_suffix() -> None:
    assert extract_usd_price_from_text("26 000 USD\n") == "26000"


def test_extract_usd_none() -> None:
    assert extract_usd_price_from_text("только сом") is None
