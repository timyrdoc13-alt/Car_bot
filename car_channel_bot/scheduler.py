from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from car_channel_bot.config.settings import Settings
from car_channel_bot.services.pipeline_queue import enqueue_scheduler_auto_batch, pipeline_queue_enabled
from car_channel_bot.services.scheduled_auto_batch import build_batch_and_notify, parse_scheduler_filters

if TYPE_CHECKING:
    from aiogram import Dispatcher

log = structlog.get_logger()


def setup_scheduler(_bot: Bot, dp: Dispatcher, settings: Settings) -> AsyncIOScheduler | None:
    cron = (settings.auto_schedule_cron or "").strip()
    if not cron:
        return None

    sched = AsyncIOScheduler()

    async def job() -> None:
        filters = parse_scheduler_filters(settings)
        job_bot: Bot = dp.workflow_data["bot"]
        admins = settings.admin_id_list
        if not admins:
            log.warning("scheduler_skip_no_admins")
            return

        if pipeline_queue_enabled(settings):
            try:
                await enqueue_scheduler_auto_batch(settings, filters, skip_dedupe=False)
            except Exception as e:
                log.error("scheduler_enqueue_failed", error=str(e), exc_info=True)
            return

        db = dp.workflow_data["db"]
        listing_source = dp.workflow_data["listing_source"]
        llm = dp.workflow_data["llm"]
        await build_batch_and_notify(
            bot=job_bot,
            db=db,
            settings=settings,
            listing_source=listing_source,
            llm=llm,
            filters=filters,
            skip_dedupe=False,
            intro_prefix="⏰ Автопостинг по расписанию\n",
        )

    parts = cron.split()
    if len(parts) != 5:
        log.warning("scheduler_bad_cron", cron=cron)
        return None
    sched.add_job(job, "cron", minute=parts[0], hour=parts[1], day=parts[2], month=parts[3], day_of_week=parts[4])
    return sched
