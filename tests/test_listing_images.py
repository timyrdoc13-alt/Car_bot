"""Тесты отбора URL фото объявлений."""

from car_channel_bot.services.listing_images import sanitize_vehicle_image_urls


def test_sanitize_drops_bundles_and_keeps_tachka() -> None:
    urls = [
        "https://m.mashina.kg/bundles/foo/bar.png",
        "https://m.mashina.kg/tachka/images/1.jpg",
        "https://m.mashina.kg/img/product-promo/x.png",
    ]
    out = sanitize_vehicle_image_urls(urls, max_photos=6)
    assert out == ["https://m.mashina.kg/tachka/images/1.jpg"]


def test_sanitize_max_photos_and_dedupe() -> None:
    base = "https://m.mashina.kg/tachka/images/{}.jpg"
    urls = [base.format(i) for i in range(10)]
    urls.insert(1, urls[0])  # duplicate
    out = sanitize_vehicle_image_urls(urls, max_photos=4)
    assert len(out) == 4
    assert out[0] == base.format(0)
    assert out[1] == base.format(1)


def test_sanitize_drops_svg_even_in_other_host() -> None:
    out = sanitize_vehicle_image_urls(
        ["https://example.com/car.svg", "https://example.com/car.jpg"],
        max_photos=6,
    )
    assert out == ["https://example.com/car.jpg"]


def test_sanitize_drops_mashina_tiny_user_avatar() -> None:
    out = sanitize_vehicle_image_urls(
        [
            "https://im.mashina.kg/tachka/images//users/d/c/7/dc720b24e4df0ea2aa787b618f4f1b4d_60x60.jpg",
            "https://im.mashina.kg/tachka/images//e/a/b/eab3233d3a02dc6ee3460a2602b94da6_640x480.jpg",
        ],
        max_photos=6,
    )
    assert out == [
        "https://im.mashina.kg/tachka/images//e/a/b/eab3233d3a02dc6ee3460a2602b94da6_640x480.jpg"
    ]
