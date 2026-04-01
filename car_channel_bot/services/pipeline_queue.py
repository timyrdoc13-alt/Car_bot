"""Очередь Redis: вынести тяжёлый автопайплайн из процесса бота (опционально)."""

from __future__ import annotations

import json
from typing import Any

import structlog

from car_channel_bot.config.settings import Settings

log = structlog.get_logger()

JOB_OP_SCHEDULER_AUTO_BATCH = "scheduler_auto_batch"


async def enqueue_scheduler_auto_batch(settings: Settings, filters: dict[str, Any], *, skip_dedupe: bool) -> None:
    url = (settings.redis_url or "").strip()
    if not url:
        raise RuntimeError("redis_url is empty")
    try:
        import redis.asyncio as redis
    except ImportError as e:
        raise RuntimeError("Install queue extra: pip install 'car-channel-bot[queue]'") from e

    payload = json.dumps(
        {
            "op": JOB_OP_SCHEDULER_AUTO_BATCH,
            "filters": filters,
            "skip_dedupe": skip_dedupe,
        },
        ensure_ascii=False,
    )
    r = redis.from_url(url, decode_responses=True)
    try:
        await r.lpush(settings.pipeline_queue_key, payload)
        log.info("pipeline_job_enqueued", key=settings.pipeline_queue_key, op=JOB_OP_SCHEDULER_AUTO_BATCH)
    finally:
        await r.aclose()


def pipeline_queue_enabled(settings: Settings) -> bool:
    r = (settings.redis_url or "").strip()
    k = (settings.pipeline_queue_key or "").strip()
    return bool(r and k)
