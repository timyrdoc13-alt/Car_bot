"""Воркер: BRPOP из Redis, сбор автобатча и уведомление админа (тот же .env что у бота)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from aiogram import Bot

from car_channel_bot.config.settings import clear_settings_cache, get_settings
from car_channel_bot.db.repositories import Database
from car_channel_bot.logging_setup import configure_logging
from car_channel_bot.parsers.factory import get_listing_source
from car_channel_bot.parsers.playwright_shared import shutdown_shared_playwright
from car_channel_bot.services.llm import LLMService
from car_channel_bot.services.pipeline_queue import JOB_OP_SCHEDULER_AUTO_BATCH, pipeline_queue_enabled
from car_channel_bot.services.scheduled_auto_batch import build_batch_and_notify

log = structlog.get_logger()


async def run() -> None:
    clear_settings_cache()
    settings = get_settings()
    configure_logging(settings.log_level)
    if not pipeline_queue_enabled(settings):
        log.error("pipeline_worker_misconfigured", hint="set REDIS_URL and PIPELINE_QUEUE_KEY")
        raise SystemExit(1)

    try:
        import redis.asyncio as redis
    except ImportError as e:
        log.error("pipeline_worker_import_redis", err=str(e))
        raise SystemExit("pip install 'car-channel-bot[queue]'") from e

    db = Database(settings.database_path)
    await db.connect()
    await db.prune_old_listings(settings.dedup_ttl_days)
    bot = Bot(settings.bot_token)
    listing_source = get_listing_source(settings)
    llm = LLMService(settings)
    r = redis.from_url(settings.redis_url.strip(), decode_responses=True)
    log.info("pipeline_worker_started", queue_key=settings.pipeline_queue_key)
    try:
        while True:
            out = await r.brpop(settings.pipeline_queue_key, timeout=60)
            if out is None:
                continue
            _key, raw = out
            try:
                job: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError as e:
                log.warning("pipeline_worker_bad_json", err=str(e), raw_preview=raw[:200])
                continue
            op = job.get("op")
            if op != JOB_OP_SCHEDULER_AUTO_BATCH:
                log.warning("pipeline_worker_unknown_op", op=op)
                continue
            filters = job.get("filters") if isinstance(job.get("filters"), dict) else {}
            skip_dedupe = bool(job.get("skip_dedupe", False))
            try:
                await build_batch_and_notify(
                    bot=bot,
                    db=db,
                    settings=settings,
                    listing_source=listing_source,
                    llm=llm,
                    filters=filters,
                    skip_dedupe=skip_dedupe,
                    intro_prefix="⏰ Автопостинг по расписанию (воркер)\n",
                )
            except Exception as e:
                log.error("pipeline_worker_job_failed", error=str(e), exc_info=True)
    finally:
        await shutdown_shared_playwright()
        await r.aclose()
        await db.close()
        await bot.session.close()
        log.info("pipeline_worker_shutdown")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
