"""Единая фабрика источника объявлений по настройкам (бот, scheduler)."""

from __future__ import annotations

from car_channel_bot.config.settings import Settings
from car_channel_bot.parsers.base import ListingSource
from car_channel_bot.parsers.lalafo import LalafoListingSource
from car_channel_bot.parsers.mashina import MashinaListingSource
from car_channel_bot.parsers.stub import StubListingSource


def get_listing_source(settings: Settings) -> ListingSource:
    src = (settings.listing_source or "stub").strip().lower()
    if src == "lalafo":
        return LalafoListingSource(settings)
    if src == "mashina":
        return MashinaListingSource(settings)
    return StubListingSource()
