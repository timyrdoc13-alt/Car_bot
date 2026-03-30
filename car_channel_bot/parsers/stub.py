from __future__ import annotations

from typing import Any

from car_channel_bot.parsers import fields as LF
from car_channel_bot.parsers.base import ListingDetail, ListingRef


class StubListingSource:
    async def search(self, filters: dict[str, Any]) -> list[ListingRef]:
        limit = int(filters.get("limit", 5))
        model = (filters.get("model") or "Demo").strip()
        refs: list[ListingRef] = []
        for i in range(max(1, min(limit, 20))):
            refs.append(
                ListingRef(
                    url=f"https://stub.example/listing/{model.lower()}-{i + 1}",
                    source="stub",
                )
            )
        return refs

    async def fetch_detail(self, ref: ListingRef) -> ListingDetail:
        raw = ref.url.rsplit("/", 1)[-1]
        title = raw.replace("-", " ").title()
        desc = (
            f"Тестовое описание для {title}. Год 2020, пробег 80 000 км, 2.0 бензин."
        )
        field_map = LF.build_standard_fields(
            source_label="stub",
            title=title,
            year="2020",
            mileage="80000",
            engine="2.0 бензин",
            price_usd="15000",
        )
        return ListingDetail(
            url=ref.url,
            title=title,
            description=desc,
            image_urls=[f"https://picsum.photos/seed/stub{hash(ref.url) % 1000}/800/600"],
            fields=field_map,
        )
