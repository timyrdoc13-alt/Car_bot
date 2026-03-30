from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from car_channel_bot.bot.drafts import DraftStore
from car_channel_bot.config.settings import Settings
from car_channel_bot.db.repositories import Database
from car_channel_bot.parsers.base import ListingSource
from car_channel_bot.services.llm import LLMService
from car_channel_bot.services.publisher import ChannelPublisher
from car_channel_bot.services.stats import StatsService


def _user_from_event(event: TelegramObject) -> tuple[int | None, Message | CallbackQuery | None]:
    if isinstance(event, Update):
        if event.message and event.message.from_user:
            return event.message.from_user.id, event.message
        if event.edited_message and event.edited_message.from_user:
            return event.edited_message.from_user.id, event.edited_message
        if event.callback_query and event.callback_query.from_user:
            return event.callback_query.from_user.id, event.callback_query
        return None, None
    if isinstance(event, Message):
        return (event.from_user.id if event.from_user else None, event)
    if isinstance(event, CallbackQuery):
        return (event.from_user.id if event.from_user else None, event)
    return None, None


class AdminOnlyMiddleware(BaseMiddleware):
    """Reads allowed admin ids from data['settings'] each request (after InjectMiddleware)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        settings = data.get("settings")
        allowed: set[int] = set(settings.admin_id_list) if isinstance(settings, Settings) else set()

        uid, target = _user_from_event(event)
        if uid is None or uid not in allowed:
            if isinstance(target, Message):
                await target.answer("Доступ только для администраторов.")
            elif isinstance(target, CallbackQuery):
                await target.answer("Нет доступа.", show_alert=True)
            return None
        return await handler(event, data)


class InjectMiddleware(BaseMiddleware):
    def __init__(
        self,
        *,
        db: Database,
        settings: Settings,
        draft_store: DraftStore,
        listing_source: ListingSource,
        llm: LLMService,
        publisher_factory: Callable[[], ChannelPublisher],
    ) -> None:
        self.db = db
        self.settings = settings
        self.draft_store = draft_store
        self.listing_source = listing_source
        self.llm = llm
        self._publisher_factory = publisher_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["db"] = self.db
        data["settings"] = self.settings
        data["draft_store"] = self.draft_store
        data["listing_source"] = self.listing_source
        data["llm"] = self.llm
        data["publisher"] = self._publisher_factory()
        data["stats_svc"] = StatsService(self.db)
        return await handler(event, data)
