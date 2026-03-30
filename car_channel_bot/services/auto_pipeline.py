from __future__ import annotations

from typing import Any, Optional

import structlog

from car_channel_bot.config.settings import Settings
from car_channel_bot.db.repositories import Database
from car_channel_bot.parsers.base import ListingSource
from car_channel_bot.parsers.quality import validate_listing_detail
from car_channel_bot.services.llm import LLMService
from car_channel_bot.services.text_sanitize import caption_without_urls

log = structlog.get_logger()


async def build_auto_batch_items(
    *,
    listing_source: ListingSource,
    llm: LLMService,
    db: Database,
    settings: Settings,
    filters: dict[str, Any],
    skip_dedupe: bool = False,
    pipeline_stats: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    refs = await listing_source.search(filters)
    log.info(
        "auto_pipeline_search",
        refs_found=len(refs),
        dedup_ttl_days=settings.dedup_ttl_days,
        skip_dedupe=skip_dedupe,
    )

    items: list[dict[str, Any]] = []
    skipped_dedupe = 0
    detail_errors = 0
    quality_skipped = 0

    for ref in refs:
        if (
            not skip_dedupe
            and await db.is_listing_seen_recently(ref.url, settings.dedup_ttl_days)
        ):
            skipped_dedupe += 1
            continue

        try:
            detail = await listing_source.fetch_detail(ref)
        except Exception as e:
            detail_errors += 1
            log.warning(
                "auto_pipeline_detail_error",
                url=ref.url,
                source=ref.source,
                error=str(e),
            )
            continue

        ok, reason = validate_listing_detail(detail, require_photos=True)
        if not ok:
            quality_skipped += 1
            log.info(
                "auto_pipeline_quality_skip",
                url=ref.url,
                source=ref.source,
                reason=reason,
            )
            continue

        raw_blob = LLMService.build_prompt_from_parsed_fields(
            {**detail.fields, "Описание": detail.description}
        )
        cap = caption_without_urls(await llm.generate_caption(raw_blob))
        items.append(
            {
                "url": detail.url,
                "caption": cap,
                "image_urls": list(detail.image_urls),
            }
        )

    log.info(
        "auto_pipeline_batch_complete",
        items_built=len(items),
        skipped_dedupe=skipped_dedupe,
        detail_errors=detail_errors,
        quality_skipped=quality_skipped,
        refs_total=len(refs),
    )
    if pipeline_stats is not None:
        pipeline_stats.clear()
        pipeline_stats.update(
            {
                "listing_source": listing_source.__class__.__name__,
                "refs_found": len(refs),
                "skipped_dedupe": skipped_dedupe,
                "detail_errors": detail_errors,
                "quality_skipped": quality_skipped,
                "items_built": len(items),
            }
        )
    return items
