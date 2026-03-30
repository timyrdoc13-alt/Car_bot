from car_channel_bot.services.text_sanitize import caption_without_urls


def test_caption_without_urls_strips_http() -> None:
    t = "Цена 5000\nСмотри https://mashina.kg/a/b и www.example.com/x"
    out = caption_without_urls(t)
    assert "http" not in out.lower()
    assert "www." not in out.lower()
    assert "Цена" in out
