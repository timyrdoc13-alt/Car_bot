from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import urlparse

import httpx
import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, InputMediaPhoto

from car_channel_bot.parsers.common import MOBILE_USER_AGENT

log = structlog.get_logger()

_CLIENT_HEADERS = {"User-Agent": MOBILE_USER_AGENT}


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
            try:
                r = await client.get(u)
                if r.status_code != 200 or not r.content:
                    continue
                ct = r.headers.get("content-type")
                if ct and "image" not in ct.split(";")[0].lower():
                    continue
                name = _filename_for_url(u, ct, len(out))
                out.append(BufferedInputFile(r.content, filename=name))
            except Exception as e:
                log.debug("listing_image_fetch_failed", url=u[:120], err=str(e))
                continue
    return out


class ChannelPublisher:
    def __init__(self, bot: Bot, channel_id: int) -> None:
        self._bot = bot
        self._channel_id = channel_id

    async def publish_photos_with_caption(
        self,
        *,
        image_urls: list[str],
        caption: str,
    ) -> int | None:
        cap = (caption or "")[:1024]
        files = await fetch_listing_images(image_urls or [], limit=10)
        if not files:
            msg = await self._bot.send_message(self._channel_id, cap or ".")
            return msg.message_id
        if len(files) == 1:
            try:
                msg = await self._bot.send_photo(
                    self._channel_id, files[0], caption=cap or None
                )
                return msg.message_id
            except TelegramBadRequest as e:
                log.warning("channel_photo_rejected_fallback_text", err=str(e))
                msg = await self._bot.send_message(self._channel_id, cap or ".")
                return msg.message_id
        media: list[InputMediaPhoto] = []
        for i, bf in enumerate(files):
            c = cap if i == 0 else None
            media.append(InputMediaPhoto(media=bf, caption=c))
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
                log.warning("channel_single_photo_rejected_fallback_text", err=str(e2))
                msg = await self._bot.send_message(self._channel_id, cap or ".")
                return msg.message_id

    async def publish_from_file_ids(
        self,
        *,
        file_ids: list[str],
        caption: str,
    ) -> int | None:
        cap = (caption or "")[:1024]
        if not file_ids:
            msg = await self._bot.send_message(self._channel_id, cap or ".")
            return msg.message_id
        if len(file_ids) == 1:
            msg = await self._bot.send_photo(
                self._channel_id, file_ids[0], caption=cap or None
            )
            return msg.message_id
        media: list[InputMediaPhoto] = []
        for i, fid in enumerate(file_ids[:10]):
            c = cap if i == 0 else None
            media.append(InputMediaPhoto(media=fid, caption=c))
        msgs = await self._bot.send_media_group(self._channel_id, media=media)
        return msgs[0].message_id if msgs else None
