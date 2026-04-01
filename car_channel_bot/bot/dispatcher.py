"""Сборка Dispatcher: middleware, роутеры, workflow_data для polling и scheduler."""

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage

from car_channel_bot.bot.drafts import DraftStore
from car_channel_bot.bot.middlewares import AdminOnlyMiddleware, InjectMiddleware
from car_channel_bot.bot.router_auto import router as auto_router
from car_channel_bot.bot.router_main import router as main_entry_router
from car_channel_bot.bot.router_manual import router as manual_router
from car_channel_bot.bot.router_stats import router as stats_router
from car_channel_bot.config.settings import Settings
from car_channel_bot.db.repositories import Database
from car_channel_bot.parsers.factory import get_listing_source
from car_channel_bot.services.llm import LLMService
from car_channel_bot.services.publisher import ChannelPublisher


def _fsm_storage(settings: Settings) -> BaseStorage:
    url = (settings.redis_url or "").strip()
    if not url:
        return MemoryStorage()
    try:
        from aiogram.fsm.storage.redis import RedisStorage
    except ImportError as e:
        raise RuntimeError(
            "Для Redis FSM: pip install 'car-channel-bot[queue]'",
        ) from e
    ttl = settings.fsm_state_ttl_seconds
    return RedisStorage.from_url(url, state_ttl=ttl, data_ttl=ttl)


def build_dispatcher(
    *,
    bot: Bot,
    db: Database,
    settings: Settings,
) -> Dispatcher:
    draft_store = DraftStore()
    listing_source = get_listing_source(settings)
    llm = LLMService(settings)

    def publisher_factory() -> ChannelPublisher:
        return ChannelPublisher(bot, settings.channel_id, settings)

    dp = Dispatcher(storage=_fsm_storage(settings))
    dp.update.outer_middleware(
        InjectMiddleware(
            db=db,
            settings=settings,
            draft_store=draft_store,
            listing_source=listing_source,
            llm=llm,
            publisher_factory=publisher_factory,
        )
    )
    dp.update.outer_middleware(AdminOnlyMiddleware())
    dp.include_router(main_entry_router)
    dp.include_router(auto_router)
    dp.include_router(manual_router)
    dp.include_router(stats_router)
    dp.workflow_data["listing_source"] = listing_source
    dp.workflow_data["draft_store"] = draft_store
    dp.workflow_data["settings"] = settings
    dp.workflow_data["db"] = db
    dp.workflow_data["llm"] = llm
    dp.workflow_data["bot"] = bot
    dp.workflow_data["publisher_factory"] = publisher_factory
    return dp
