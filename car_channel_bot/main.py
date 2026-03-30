from __future__ import annotations

import asyncio

import structlog
from aiogram import Bot

from car_channel_bot.bot.dispatcher import build_dispatcher
from car_channel_bot.config.settings import clear_settings_cache, get_settings
from car_channel_bot.db.repositories import Database
from car_channel_bot.logging_setup import configure_logging
from car_channel_bot.scheduler import setup_scheduler

log = structlog.get_logger()


async def run() -> None:
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)
    db = Database(settings.database_path)
    await db.connect()
    await db.prune_old_listings(settings.dedup_ttl_days)
    bot = Bot(settings.bot_token)
    dp = build_dispatcher(bot=bot, db=db, settings=settings)
    sched = setup_scheduler(bot, dp, settings)
    if sched:
        sched.start()
    try:
        await dp.start_polling(bot)
    finally:
        if sched and sched.running:
            sched.shutdown(wait=False)
        await db.close()
        await bot.session.close()
        log.info("shutdown_complete")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
