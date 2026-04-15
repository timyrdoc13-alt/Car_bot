from car_channel_bot.parsers.mashina import _extract_gallery_urls_from_html


def test_extract_gallery_urls_from_html_filters_banners_users_and_tiny() -> None:
    html = """
    <script>
      const a = "https://im.mashina.kg/tachka/images//1/2/3/a123_1200x900.jpg";
      const b = "https://im.mashina.kg/tachka/images//1/2/3/a123_640x480.jpg";
      const c = "https://im.mashina.kg/tachka/images//banners/ad_banner.jpeg";
      const d = "https://im.mashina.kg/tachka/images//users/u1/avatar_60x60.jpg";
      const e = "https://im.mashina.kg/tachka/images//9/8/7/pic_180x120.jpg";
    </script>
    """
    out = _extract_gallery_urls_from_html(html, limit=24)
    assert out == [
        "https://im.mashina.kg/tachka/images//1/2/3/a123_1200x900.jpg",
    ]


def test_extract_gallery_urls_from_html_respects_limit_and_dedup() -> None:
    html = """
    https://im.mashina.kg/tachka/images//a/a/a/img1_640x480.jpg
    https://im.mashina.kg/tachka/images//a/a/a/img1_640x480.jpg
    https://im.mashina.kg/tachka/images//b/b/b/img2_640x480.jpg
    """
    out = _extract_gallery_urls_from_html(html, limit=1)
    assert out == ["https://im.mashina.kg/tachka/images//a/a/a/img1_640x480.jpg"]
