from __future__ import annotations

import asyncio
from typing import Any

import structlog

from car_channel_bot.config.settings import Settings
from car_channel_bot.db.repositories import Database
from car_channel_bot.services.publisher import ChannelPublisher
from car_channel_bot.services.text_sanitize import caption_without_urls

log = structlog.get_logger()


async def publish_one_auto_item(
    *,
    publisher: ChannelPublisher,
    db: Database,
    admin_id: int,
    item: dict[str, Any],
) -> None:
    cap = caption_without_urls(item.get("caption") or "")
    mid = await publisher.publish_photos_with_caption(
        image_urls=item.get("image_urls") or [],
        caption=cap,
    )
    await db.mark_listing_seen(item["url"])
    await db.insert_post(
        channel_message_id=mid,
        source="auto",
        admin_id=admin_id,
        listing_url=item["url"],
        caption=cap,
    )


async def publish_auto_items(
    *,
    publisher: ChannelPublisher,
    db: Database,
    items: list[dict[str, Any]],
    admin_id: int,
    settings: Settings,
) -> tuple[int, list[dict[str, Any]]]:
    """Публикует подряд; при ошибке одного объявления кладёт его в failed и идёт дальше."""
    count = 0
    failed_items: list[dict[str, Any]] = []
    n_items = len(items)
    for idx, it in enumerate(items):
        try:
            await publish_one_auto_item(
                publisher=publisher,
                db=db,
                admin_id=admin_id,
                item=it,
            )
            count += 1
            if idx + 1 < n_items:
                await asyncio.sleep(settings.channel_post_cooldown_seconds)
        except Exception as e:
            failed_items.append(it)
            log.exception(
                "auto_publish_item_failed",
                url=(it.get("url") or "")[:200],
                err=str(e),
            )
    if count:
        await db.insert_event(
            "auto_approved",
            {"count": count, "failed": len(failed_items)},
        )
        log.info("auto_publish_done", count=count, failed=len(failed_items))
    elif failed_items:
        log.warning("auto_publish_all_failed", failed=len(failed_items))
    return count, failed_items
