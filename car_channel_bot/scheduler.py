from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from car_channel_bot.config.settings import Settings
from car_channel_bot.db.repositories import Database
from car_channel_bot.services.auto_batch_ui import assign_auto_item_keys, send_auto_batch_previews_to_admin
from car_channel_bot.services.auto_pipeline import build_auto_batch_items

if TYPE_CHECKING:
    from aiogram import Dispatcher

log = structlog.get_logger()

def setup_scheduler(_bot: Bot, dp: Dispatcher, settings: Settings) -> AsyncIOScheduler | None:
    cron = (settings.auto_schedule_cron or "").strip()
    if not cron:
        return None

    sched = AsyncIOScheduler()

    async def job() -> None:
        try:
            filters: dict[str, Any] = json.loads(settings.auto_schedule_filters_json or "{}")
        except json.JSONDecodeError:
            filters = {"limit": 5}
        db: Database = dp.workflow_data["db"]
        listing_source = dp.workflow_data["listing_source"]
        llm = dp.workflow_data["llm"]
        job_bot: Bot = dp.workflow_data["bot"]
        admins = settings.admin_id_list
        if not admins:
            log.warning("scheduler_skip_no_admins")
            return

        stats: dict[str, Any] = {}
        items = await build_auto_batch_items(
            listing_source=listing_source,
            llm=llm,
            db=db,
            settings=settings,
            filters=filters,
            skip_dedupe=False,
            pipeline_stats=stats,
        )
        if not items:
            log.info("scheduler_auto_run", count=0, note="no_new_items", **stats)
            return

        admin_id = admins[0]
        keyed = assign_auto_item_keys(items)
        batch_id = await db.create_auto_batch(
            admin_id=admin_id,
            filters=filters,
            items=keyed,
        )
        await db.insert_event(
            "scheduler_batch_ready",
            {"batch_id": batch_id, "count": len(keyed), "admin_id": admin_id},
        )

        try:
            await send_auto_batch_previews_to_admin(
                job_bot,
                admin_id,
                batch_id,
                keyed,
                intro_prefix="⏰ Автопостинг по расписанию\n",
                gallery_max_photos=settings.channel_gallery_max_photos,
            )
        except Exception as e:
            log.error(
                "scheduler_notify_admin_failed",
                admin_id=admin_id,
                error=str(e),
                exc_info=True,
            )
            return

        log.info("scheduler_auto_run", count=len(items), batch_id=batch_id, admin_id=admin_id)

    parts = cron.split()
    if len(parts) != 5:
        log.warning("scheduler_bad_cron", cron=cron)
        return None
    sched.add_job(job, "cron", minute=parts[0], hour=parts[1], day=parts[2], month=parts[3], day_of_week=parts[4])
    return sched
