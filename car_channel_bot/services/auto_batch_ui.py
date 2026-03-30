"""Черновики автопоста: ключи для callback и рассылка превью админу."""

from __future__ import annotations

import hashlib
from typing import Any

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from car_channel_bot.bot.keyboards import auto_batch_summary_kb, auto_item_kb
from car_channel_bot.services.publisher import fetch_listing_images
from car_channel_bot.services.text_sanitize import caption_without_urls

log = structlog.get_logger()


def auto_item_key_for_url(url: str) -> str:
    return hashlib.sha256((url or "").encode()).hexdigest()[:12]


def assign_auto_item_keys(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for it in items:
        d = dict(it)
        d["item_key"] = auto_item_key_for_url(str(d.get("url") or ""))
        out.append(d)
    return out


def preview_caption(text: str, *, max_len: int = 1024) -> str:
    c = caption_without_urls(text or "")
    return c if len(c) <= max_len else c[: max_len - 1].rstrip() + "…"


async def send_auto_batch_previews_to_admin(
    bot: Bot,
    admin_chat_id: int,
    batch_id: str,
    items: list[dict[str, Any]],
    *,
    intro_prefix: str = "",
) -> None:
    n = len(items)
    intro = (
        intro_prefix
        + f"Черновиков: {n}. Ниже — каждое объявление с фото (если скачалось) "
        "и кнопками «Одобрить» / «Пропустить». Можно «Одобрить все» здесь."
    )
    await bot.send_message(
        admin_chat_id,
        intro,
        reply_markup=auto_batch_summary_kb(batch_id),
    )
    for it in items:
        cap = preview_caption(it.get("caption") or "")
        kb = auto_item_kb(batch_id, str(it["item_key"]))
        urls = it.get("image_urls") or []
        try:
            files = await fetch_listing_images(urls, limit=1)
            if files:
                try:
                    await bot.send_photo(
                        admin_chat_id,
                        files[0],
                        caption=cap or None,
                        reply_markup=kb,
                    )
                except TelegramBadRequest as e:
                    log.warning(
                        "admin_preview_photo_rejected",
                        batch_id=batch_id,
                        err=str(e),
                    )
                    await bot.send_message(
                        admin_chat_id,
                        cap or "(без текста)",
                        reply_markup=kb,
                    )
            else:
                await bot.send_message(
                    admin_chat_id,
                    cap or "(без текста)",
                    reply_markup=kb,
                )
        except Exception as e:
            log.warning(
                "admin_preview_send_failed",
                batch_id=batch_id,
                err=str(e),
            )
            await bot.send_message(
                admin_chat_id,
                cap or "Ошибка превью",
                reply_markup=kb,
            )
