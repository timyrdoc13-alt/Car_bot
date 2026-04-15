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

_MAX_TELEGRAM_PHOTO_BYTES = 9_000_000  # guardrail: oversized photos often break albums
_JPEG_MAX_SIDE = 1600
_MIN_PHOTO_SIDE = 260


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


def _try_normalize_image_bytes(raw: bytes) -> bytes:
    """Best-effort resize/compress to make Telegram albums more reliable."""
    # Avoid importing Pillow unless actually used.
    try:
        from io import BytesIO

        from PIL import Image, ImageOps
    except Exception:
        return raw

    try:
        with Image.open(BytesIO(raw)) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode not in {"RGB", "L"}:
                im = im.convert("RGB")
            w, h = im.size
            m = max(w, h)
            if m > _JPEG_MAX_SIDE:
                scale = _JPEG_MAX_SIDE / float(m)
                nw = max(1, int(w * scale))
                nh = max(1, int(h * scale))
                im = im.resize((nw, nh), resample=Image.Resampling.LANCZOS)

            buf = BytesIO()
            # Start with a good quality; if still too big, step down.
            for q in (88, 82, 76, 70, 65):
                buf.seek(0)
                buf.truncate(0)
                im.save(buf, format="JPEG", quality=q, optimize=True, progressive=True)
                out = buf.getvalue()
                if len(out) <= _MAX_TELEGRAM_PHOTO_BYTES:
                    return out
            return out
    except Exception:
        return raw


def _normalize_or_drop_image(raw: bytes) -> bytes | None:
    """Normalize image and drop obvious UI/thumbnail artifacts."""
    try:
        from io import BytesIO

        from PIL import Image, ImageOps
    except Exception:
        # Without Pillow we cannot validate dimensions; keep original behavior.
        return raw

    try:
        with Image.open(BytesIO(raw)) as im:
            im = ImageOps.exif_transpose(im)
            w, h = im.size
            # Drop tiny assets (icons, scroll controls, avatars).
            if min(w, h) < _MIN_PHOTO_SIDE:
                return None
            norm = _try_normalize_image_bytes(raw)
            if not norm:
                return None
            return norm
    except Exception:
        return None


async def _fetch_one_listing_image(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    ordinal: int,
    u: str,
) -> tuple[int, BufferedInputFile | None]:
    low = u.lower()
    if low.endswith(".svg") or ".svg?" in low:
        return ordinal, None
    try:
        async with sem:
            r = await client.get(u)
        if r.status_code != 200 or not r.content:
            return ordinal, None
        ct = r.headers.get("content-type")
        if ct:
            ctn = ct.split(";")[0].lower()
            if "svg" in ctn:
                return ordinal, None
            if "image" not in ctn:
                return ordinal, None
        name = _filename_for_url(u, ct, ordinal)
        content = await asyncio.to_thread(_normalize_or_drop_image, r.content)
        if not content:
            return ordinal, None
        if len(content) > _MAX_TELEGRAM_PHOTO_BYTES:
            return ordinal, None
        if (ct and "image/" in ct and "jpeg" not in ct.lower()) or name.lower().endswith(
            (".png", ".webp", ".gif")
        ):
            name = f"photo_{ordinal}.jpg"
        return ordinal, BufferedInputFile(content, filename=name)
    except Exception as e:
        log.debug("listing_image_fetch_failed", url=u[:120], err=str(e))
        return ordinal, None


async def fetch_listing_images(
    urls: list[str],
    *,
    limit: int = 10,
    timeout: float = 45.0,
    download_concurrency: int = 4,
) -> list[BufferedInputFile]:
    """Скачивает картинки на сервер бота — Telegram часто не тянет CDN-URL напрямую."""
    capped = urls[:limit]
    sem = asyncio.Semaphore(max(1, download_concurrency))
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers=_CLIENT_HEADERS,
    ) as client:
        pairs = await asyncio.gather(
            *[
                _fetch_one_listing_image(client, sem, i, u)
                for i, u in enumerate(capped)
            ],
            return_exceptions=True,
        )
    out_ord: list[tuple[int, BufferedInputFile]] = []
    for p in pairs:
        if isinstance(p, Exception):
            log.warning("listing_image_worker_error", err=str(p))
            continue
        ord_i, bf = p
        if bf is not None:
            out_ord.append((ord_i, bf))
    out_ord.sort(key=lambda x: x[0])
    return [bf for _, bf in out_ord]


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
        # Берём расширенный пул кандидатов, чтобы компенсировать битые/недоступные URL.
        # Иначе первые 4-6 ссылок могут дать только 1 валидный файл.
        candidate_cap = 12
        return sanitize_vehicle_image_urls(image_urls or [], max_photos=candidate_cap)

    async def publish_photos_with_caption(
        self,
        *,
        image_urls: list[str],
        caption: str,
    ) -> int | None:
        cap = (caption or "")[:1024]
        clean_urls = self._prepare_urls(image_urls)
        _, hi = self._gallery_bounds()
        log.info(
            "channel_publish_prepare",
            urls_in=len(image_urls or []),
            urls_clean=len(clean_urls),
            gallery_max=hi,
        )
        conc = 4
        if self._settings is not None:
            conc = self._settings.image_download_concurrency
        files = await fetch_listing_images(
            clean_urls,
            limit=len(clean_urls),
            download_concurrency=conc,
        )
        if len(files) > hi:
            files = files[:hi]
        log.info(
            "channel_publish_files",
            urls_clean=len(clean_urls),
            files=len(files),
            bytes=[len(f.data) for f in files[:6]],
        )
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

        async def _album() -> int | None:
            attempt_files = list(files)
            while len(attempt_files) >= 2:
                media: list[InputMediaPhoto] = []
                for i, bf in enumerate(attempt_files):
                    c = cap if i == 0 else None
                    media.append(InputMediaPhoto(media=bf, caption=c))
                try:
                    msgs = await self._bot.send_media_group(self._channel_id, media=media)
                    return msgs[0].message_id if msgs else None
                except TelegramBadRequest as e:
                    log.warning(
                        "channel_album_rejected_retry_smaller",
                        err=str(e),
                        try_files=len(attempt_files),
                        urls_clean=len(clean_urls),
                        bytes=[len(f.data) for f in attempt_files[:6]],
                    )
                    # If one bad file is not the last one, tail-chop is often insufficient.
                    # Try removing largest file first to quickly bypass problematic assets.
                    drop_idx = max(range(len(attempt_files)), key=lambda i: len(attempt_files[i].data))
                    attempt_files = [f for i, f in enumerate(attempt_files) if i != drop_idx]

            try:
                msg = await self._bot.send_photo(
                    self._channel_id, files[0], caption=cap or None
                )
                return msg.message_id
            except TelegramBadRequest as e:
                log.warning(
                    "channel_album_rejected_try_single",
                    err=str(e),
                    urls_clean=len(clean_urls),
                    files=len(files),
                    bytes=[len(f.data) for f in files[:6]],
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
