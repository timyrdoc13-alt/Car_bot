"""Общая логика: собрать автобатч и отправить превью админу (scheduler и воркер очереди)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog

from car_channel_bot.config.settings import Settings
from car_channel_bot.db.repositories import Database
from car_channel_bot.services.auto_batch_ui import assign_auto_item_keys, send_auto_batch_previews_to_admin
from car_channel_bot.services.auto_pipeline import build_auto_batch_items
from car_channel_bot.services.llm import LLMService

if TYPE_CHECKING:
    from aiogram import Bot

    from car_channel_bot.parsers.base import ListingSource

log = structlog.get_logger()


async def build_batch_and_notify(
    *,
    bot: "Bot",
    db: Database,
    settings: Settings,
    listing_source: "ListingSource",
    llm: LLMService,
    filters: dict[str, Any],
    skip_dedupe: bool = False,
    intro_prefix: str = "",
) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    items = await build_auto_batch_items(
        listing_source=listing_source,
        llm=llm,
        db=db,
        settings=settings,
        filters=filters,
        skip_dedupe=skip_dedupe,
        pipeline_stats=stats,
    )
    if not items:
        log.info("scheduled_auto_batch_empty", note="no_new_items", **stats)
        return {"batch_id": None, **stats}

    admins = settings.admin_id_list
    if not admins:
        log.warning("scheduled_auto_batch_skip_no_admins", **stats)
        return {"batch_id": None, **stats}

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
            bot,
            admin_id,
            batch_id,
            keyed,
            intro_prefix=intro_prefix,
            gallery_max_photos=settings.channel_gallery_max_photos,
        )
    except Exception as e:
        log.error(
            "scheduled_auto_batch_notify_failed",
            admin_id=admin_id,
            error=str(e),
            exc_info=True,
        )
        return {"batch_id": batch_id, "notify_error": str(e), **stats}

    log.info("scheduled_auto_batch_ok", count=len(items), batch_id=batch_id, admin_id=admin_id, **stats)
    return {"batch_id": batch_id, **stats}


def parse_scheduler_filters(settings: Settings) -> dict[str, Any]:
    try:
        return json.loads(settings.auto_schedule_filters_json or "{}")
    except json.JSONDecodeError:
        return {"limit": 5}
