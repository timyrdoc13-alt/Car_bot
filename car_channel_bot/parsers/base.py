from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ListingRef:
    url: str
    source: str = "unknown"


@dataclass
class ListingDetail:
    url: str
    title: str
    description: str
    image_urls: list[str] = field(default_factory=list)
    fields: dict[str, str | None] = field(default_factory=dict)


class ListingSource(Protocol):
    async def search(self, filters: dict[str, Any]) -> list[ListingRef]: ...

    async def fetch_detail(self, ref: ListingRef) -> ListingDetail: ...
