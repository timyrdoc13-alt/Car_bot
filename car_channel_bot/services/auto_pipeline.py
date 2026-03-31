from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

from car_channel_bot.config.settings import Settings
from car_channel_bot.db.repositories import Database
from car_channel_bot.parsers.base import ListingRef, ListingSource
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
        detail_concurrency=settings.auto_detail_concurrency,
        llm_concurrency=settings.auto_llm_concurrency,
    )

    skipped_dedupe = 0
    detail_errors = 0
    quality_skipped = 0
    kept_refs: list[tuple[int, ListingRef]] = []
    for idx, ref in enumerate(refs):
        if not skip_dedupe and await db.is_listing_seen_recently(ref.url, settings.dedup_ttl_days):
            skipped_dedupe += 1
            continue
        kept_refs.append((idx, ref))

    detail_sem = asyncio.Semaphore(max(1, settings.auto_detail_concurrency))
    llm_sem = asyncio.Semaphore(max(1, settings.auto_llm_concurrency))

    async def _process_one(idx: int, ref: ListingRef) -> tuple[int, dict[str, Any] | None, str | None]:
        try:
            async with detail_sem:
                detail = await listing_source.fetch_detail(ref)
        except Exception as e:
            log.warning(
                "auto_pipeline_detail_error",
                url=ref.url,
                source=ref.source,
                error=str(e),
            )
            return idx, None, "detail_error"

        ok, reason = validate_listing_detail(detail, require_photos=True)
        if not ok:
            log.info(
                "auto_pipeline_quality_skip",
                url=ref.url,
                source=ref.source,
                reason=reason,
            )
            return idx, None, "quality_skip"

        raw_blob = LLMService.build_prompt_from_parsed_fields(
            {**detail.fields, "Описание": detail.description}
        )
        async with llm_sem:
            cap = caption_without_urls(await llm.generate_caption(raw_blob))
        return idx, {
            "url": detail.url,
            "caption": cap,
            "image_urls": list(detail.image_urls),
        }, None

    results = await asyncio.gather(*[_process_one(i, r) for i, r in kept_refs], return_exceptions=True)
    items_by_idx: list[tuple[int, dict[str, Any]]] = []
    for res in results:
        if isinstance(res, Exception):
            detail_errors += 1
            log.warning("auto_pipeline_worker_unhandled", error=str(res))
            continue
        idx, item, status = res
        if status == "detail_error":
            detail_errors += 1
            continue
        if status == "quality_skip":
            quality_skipped += 1
            continue
        if item is not None:
            items_by_idx.append((idx, item))

    items_by_idx.sort(key=lambda x: x[0])
    items = [it for _, it in items_by_idx]

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
