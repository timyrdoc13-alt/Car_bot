from __future__ import annotations

import asyncio
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Awaitable, Callable, TypeVar
from urllib.parse import urlparse

import httpx
import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import BufferedInputFile, InputMediaPhoto

from car_channel_bot.parsers.common import MOBILE_USER_AGENT
from car_channel_bot.services.listing_images import sanitize_vehicle_image_urls

if TYPE_CHECKING:
    from car_channel_bot.config.settings import Settings

log = structlog.get_logger()

_CLIENT_HEADERS = {"User-Agent": MOBILE_USER_AGENT}

T = TypeVar("T")


async def _telegram_with_flood_retry(
    op: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 8,
) -> T:
    last: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await op()
        except TelegramRetryAfter as e:
            wait = float(e.retry_after) + 1.0
            log.warning(
                "telegram_flood_retry",
                attempt=attempt + 1,
                sleep_s=round(wait, 1),
            )
            await asyncio.sleep(wait)
            last = e
        except TelegramBadRequest:
            raise
    assert last is not None
    raise last


def _filename_for_url(url: str, content_type: str | None, index: int) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if "png" in ct:
        ext = ".png"
    elif "webp" in ct:
        ext = ".webp"
    elif "gif" in ct:
        ext = ".gif"
    else:
        ext = ".jpg"
    path = urlparse(url).path
    if path:
        suf = PurePosixPath(path).suffix.lower()
        if suf in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            ext = suf if suf != ".jpeg" else ".jpg"
    return f"photo_{index}{ext}"


async def fetch_listing_images(
    urls: list[str],
    *,
    limit: int = 10,
    timeout: float = 45.0,
) -> list[BufferedInputFile]:
    """Скачивает картинки на сервер бота — Telegram часто не тянет CDN-URL напрямую."""
    out: list[BufferedInputFile] = []
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers=_CLIENT_HEADERS,
    ) as client:
        for i, u in enumerate(urls[:limit]):
            low = u.lower()
            if low.endswith(".svg") or ".svg?" in low:
                continue
            try:
                r = await client.get(u)
                if r.status_code != 200 or not r.content:
                    continue
                ct = r.headers.get("content-type")
                if ct:
                    ctn = ct.split(";")[0].lower()
                    if "svg" in ctn:
                        continue
                    if "image" not in ctn:
                        continue
                name = _filename_for_url(u, ct, len(out))
                out.append(BufferedInputFile(r.content, filename=name))
            except Exception as e:
                log.debug("listing_image_fetch_failed", url=u[:120], err=str(e))
                continue
    return out


class ChannelPublisher:
    def __init__(
        self,
        bot: Bot,
        channel_id: int,
        settings: Settings | None = None,
    ) -> None:
        self._bot = bot
        self._channel_id = channel_id
        self._settings = settings

    def _gallery_bounds(self) -> tuple[int, int]:
        if self._settings is None:
            return 1, 6
        lo = max(1, min(10, self._settings.channel_gallery_min_photos))
        hi = max(lo, min(10, self._settings.channel_gallery_max_photos))
        return lo, hi

    def _prepare_urls(self, image_urls: list[str]) -> list[str]:
        _, hi = self._gallery_bounds()
        return sanitize_vehicle_image_urls(image_urls or [], max_photos=hi)

    async def publish_photos_with_caption(
        self,
        *,
        image_urls: list[str],
        caption: str,
    ) -> int | None:
        cap = (caption or "")[:1024]
        clean_urls = self._prepare_urls(image_urls)
        _, hi = self._gallery_bounds()
        if len(clean_urls) > hi:
            clean_urls = clean_urls[:hi]
        files = await fetch_listing_images(clean_urls, limit=hi)
        if not files:
            async def _txt() -> int | None:
                msg = await self._bot.send_message(self._channel_id, cap or ".")
                return msg.message_id

            return await _telegram_with_flood_retry(_txt)
        if len(files) == 1:

            async def _one() -> int | None:
                try:
                    msg = await self._bot.send_photo(
                        self._channel_id, files[0], caption=cap or None
                    )
                    return msg.message_id
                except TelegramBadRequest as e:
                    log.warning("channel_photo_rejected_fallback_text", err=str(e))
                    msg = await self._bot.send_message(self._channel_id, cap or ".")
                    return msg.message_id

            return await _telegram_with_flood_retry(_one)

        media: list[InputMediaPhoto] = []
        for i, bf in enumerate(files):
            c = cap if i == 0 else None
            media.append(InputMediaPhoto(media=bf, caption=c))

        async def _album() -> int | None:
            try:
                msgs = await self._bot.send_media_group(self._channel_id, media=media)
                return msgs[0].message_id if msgs else None
            except TelegramBadRequest as e:
                log.warning("channel_album_rejected_try_single", err=str(e))
                try:
                    msg = await self._bot.send_photo(
                        self._channel_id, files[0], caption=cap or None
                    )
                    return msg.message_id
                except TelegramBadRequest as e2:
                    log.warning(
                        "channel_single_photo_rejected_fallback_text",
                        err=str(e2),
                    )
                    msg = await self._bot.send_message(self._channel_id, cap or ".")
                    return msg.message_id

        return await _telegram_with_flood_retry(_album)

    async def publish_from_file_ids(
        self,
        *,
        file_ids: list[str],
        caption: str,
    ) -> int | None:
        cap = (caption or "")[:1024]
        if not file_ids:

            async def _m() -> int | None:
                msg = await self._bot.send_message(self._channel_id, cap or ".")
                return msg.message_id

            return await _telegram_with_flood_retry(_m)
        if len(file_ids) == 1:

            async def _p() -> int | None:
                msg = await self._bot.send_photo(
                    self._channel_id, file_ids[0], caption=cap or None
                )
                return msg.message_id

            return await _telegram_with_flood_retry(_p)
        _, hi = self._gallery_bounds()
        media: list[InputMediaPhoto] = []
        for i, fid in enumerate(file_ids[:hi]):
            c = cap if i == 0 else None
            media.append(InputMediaPhoto(media=fid, caption=c))

        async def _mg() -> int | None:
            msgs = await self._bot.send_media_group(self._channel_id, media=media)
            return msgs[0].message_id if msgs else None

        return await _telegram_with_flood_retry(_mg)
