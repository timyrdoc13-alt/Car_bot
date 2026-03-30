from __future__ import annotations

import json
from typing import Any

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from car_channel_bot.bot.keyboards import main_menu_kb
from car_channel_bot.bot.states import AutoWizardStates
from car_channel_bot.config.settings import Settings
from car_channel_bot.db.repositories import Database
from car_channel_bot.parsers.base import ListingSource
from car_channel_bot.services.auto_batch_ui import (
    assign_auto_item_keys,
    auto_item_key_for_url,
    send_auto_batch_previews_to_admin,
)
from car_channel_bot.services.auto_pipeline import build_auto_batch_items
from car_channel_bot.services.auto_publish import publish_auto_items, publish_one_auto_item
from car_channel_bot.services.llm import LLMService

router = Router(name="auto")

log = structlog.get_logger()

_PENDING = frozenset({"pending"})


def _explain_auto_batch_empty(stats: dict[str, Any], settings: Settings) -> str:
    """Почему 0 черновиков: другой парсер чем монитор :8765, дедуп, ошибки карточки."""
    src = str(stats.get("listing_source") or "")
    refs = int(stats.get("refs_found") or 0)
    ded = int(stats.get("skipped_dedupe") or 0)
    de = int(stats.get("detail_errors") or 0)
    q = int(stats.get("quality_skipped") or 0)
    parts: list[str] = []
    if src != "MashinaListingSource":
        parts.append(
            f"В .env сейчас не Mashina (активен {src}). "
            "Страница :8765 всегда дергает только Mashina.kg — для тех же URL в боте выставьте LISTING_SOURCE=mashina."
        )
    if refs == 0:
        parts.append("Парсер вернул 0 ссылок по этим фильтрам.")
    elif ded >= refs > 0:
        parts.append(
            f"Ссылок найдено: {refs}, все уже учтены в дедупе ({settings.dedup_ttl_days} дн.). "
            "Смените фильтры или подождите."
        )
    elif de or q:
        parts.append(f"Отсеяно при разборе: карточка {de}, проверка качества {q}. Детали — в логах.")
    else:
        parts.append("Черновики не собрались (например LLM). Смотрите логи.")
    return "\n\n".join(parts)


def _normalize_batch_items(raw: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        d = dict(it)
        if "item_key" not in d:
            d["item_key"] = auto_item_key_for_url(str(d.get("url") or ""))
        out.append(d)
    return out


def _batch_id_from_prefix(data: str, prefix: str) -> str | None:
    if not data.startswith(prefix):
        return None
    return data[len(prefix) :]


@router.message(F.text == "Автопостинг")
async def auto_start(message: Message, state: FSMContext, draft_store) -> None:
    if message.from_user:
        draft_store.clear(message.from_user.id)
    await state.set_state(AutoWizardStates.model)
    await message.answer("Модель (или «-» для любой):")


@router.message(AutoWizardStates.model, F.text)
async def auto_model(message: Message, state: FSMContext) -> None:
    await state.update_data(model=message.text.strip())
    await state.set_state(AutoWizardStates.year)
    await message.answer("Год от (число или 0):")


@router.message(AutoWizardStates.year, F.text)
async def auto_year(message: Message, state: FSMContext) -> None:
    await state.update_data(year_min=message.text.strip())
    await state.set_state(AutoWizardStates.price)
    await message.answer("Цена макс. USD (0 = не важно):")


@router.message(AutoWizardStates.price, F.text)
async def auto_price(message: Message, state: FSMContext) -> None:
    await state.update_data(price_max=message.text.strip())
    await state.set_state(AutoWizardStates.limit)
    await message.answer("Сколько объявлений взять (лимит, 1–30):")


@router.message(AutoWizardStates.limit, F.text)
async def auto_limit(
    message: Message,
    state: FSMContext,
    listing_source: ListingSource,
    llm: LLMService,
    db: Database,
    settings: Settings,
) -> None:
    try:
        lim = max(1, min(30, int((message.text or "5").strip())))
    except ValueError:
        lim = 5
    data = await state.get_data()

    def _i(key: str) -> int:
        try:
            return int(str(data.get(key, "0") or "0").strip())
        except ValueError:
            return 0

    filters: dict[str, Any] = {
        "model": data.get("model", "-"),
        "year_min": _i("year_min"),
        "price_max": _i("price_max"),
        "limit": lim,
    }
    await message.answer("Собираю черновики…")
    stats: dict[str, Any] = {}
    items = await build_auto_batch_items(
        listing_source=listing_source,
        llm=llm,
        db=db,
        settings=settings,
        filters=filters,
        skip_dedupe=False,
        pipeline_stats=stats,
    )
    if not items:
        await state.clear()
        hint = _explain_auto_batch_empty(stats, settings)
        await message.answer(
            "Нет готовых черновиков.\n\n" + hint,
            reply_markup=main_menu_kb(),
        )
        return
    keyed = assign_auto_item_keys(items)
    batch_id = await db.create_auto_batch(
        admin_id=message.from_user.id,
        filters=filters,
        items=keyed,
    )
    await state.clear()
    if message.bot and message.chat:
        await send_auto_batch_previews_to_admin(
            message.bot,
            message.chat.id,
            batch_id,
            keyed,
            gallery_max_photos=settings.channel_gallery_max_photos,
        )


@router.callback_query(
    (F.data.startswith("auto:all:")) | (F.data.startswith("auto:approve:"))
)
async def auto_approve_all(
    cb: CallbackQuery,
    db: Database,
    publisher,
    settings: Settings,
) -> None:
    data = cb.data or ""
    if data.startswith("auto:all:"):
        batch_id = _batch_id_from_prefix(data, "auto:all:")
    else:
        batch_id = (data.split(":", 2) + [""])[2]
    if not batch_id:
        await cb.answer("Некорректная кнопка.", show_alert=True)
        return
    row = await db.get_auto_batch(batch_id)
    if not row or row["status"] not in _PENDING:
        await cb.answer("Пакет не найден или уже обработан.", show_alert=True)
        return
    items = _normalize_batch_items(json.loads(row["items_json"]))
    if not items:
        await cb.answer("В пакете нечего публиковать.", show_alert=True)
        return
    await cb.answer("Публикую в канал, подождите…")
    try:
        n, failed = await publish_auto_items(
            publisher=publisher,
            db=db,
            items=items,
            admin_id=cb.from_user.id,
            settings=settings,
        )
    except Exception:
        log.exception("auto_approve_all_fatal")
        if cb.message:
            await cb.message.answer(
                "Ошибка публикации. Проверьте права бота в канале и логи.",
                reply_markup=main_menu_kb(),
            )
        return
    if failed:
        await db.update_auto_batch_items(batch_id, failed)
    else:
        await db.update_auto_batch_items(batch_id, [])
        await db.update_auto_batch_status(batch_id, "published")
    if cb.message:
        await cb.message.edit_reply_markup(reply_markup=None)
    if cb.message:
        if failed:
            msg = (
                f"В канал опубликовано: {n} из {len(items)}. "
                f"Не вышло: {len(failed)} — проверьте логи и права бота. Остаток можно добить кнопками."
            )
        else:
            msg = f"Опубликовано в канал: {n}."
        await cb.message.answer(msg, reply_markup=main_menu_kb())


@router.callback_query(F.data.startswith("auto:yes:"))
async def auto_approve_one(cb: CallbackQuery, db: Database, publisher) -> None:
    parts = (cb.data or "").split(":")
    if len(parts) != 4 or parts[0] != "auto" or parts[1] != "yes":
        await cb.answer("Некорректная кнопка.", show_alert=True)
        return
    _, _, batch_id, item_key = parts
    row = await db.get_auto_batch(batch_id)
    if not row or row["status"] not in _PENDING:
        await cb.answer("Пакет не найден или уже обработан.", show_alert=True)
        return
    items = _normalize_batch_items(json.loads(row["items_json"]))
    chosen: dict[str, Any] | None = None
    rest: list[dict[str, Any]] = []
    for it in items:
        k = str(it.get("item_key") or auto_item_key_for_url(str(it.get("url") or "")))
        if k == item_key and chosen is None:
            chosen = it
        else:
            rest.append(it)
    if not chosen:
        await cb.answer("Объявление уже убрано из пакета.", show_alert=True)
        return
    await cb.answer("Публикую…")
    try:
        await publish_one_auto_item(
            publisher=publisher,
            db=db,
            admin_id=cb.from_user.id,
            item=chosen,
        )
    except Exception:
        log.exception("auto_approve_one_failed", url=(chosen.get("url") or "")[:120])
        if cb.message:
            await cb.message.answer(
                "Не удалось опубликовать (канал / фото). См. логи.",
            )
        return
    if rest:
        await db.update_auto_batch_items(batch_id, rest)
    else:
        await db.update_auto_batch_items(batch_id, [])
        await db.update_auto_batch_status(batch_id, "published")
    if cb.message:
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.message.answer("Опубликовано.")


@router.callback_query(F.data.startswith("auto:skip:"))
async def auto_skip_one(cb: CallbackQuery, db: Database) -> None:
    parts = (cb.data or "").split(":")
    if len(parts) != 4 or parts[0] != "auto" or parts[1] != "skip":
        await cb.answer("Некорректная кнопка.", show_alert=True)
        return
    _, _, batch_id, item_key = parts
    row = await db.get_auto_batch(batch_id)
    if not row or row["status"] not in _PENDING:
        await cb.answer("Пакет не найден или уже обработан.", show_alert=True)
        return
    items = _normalize_batch_items(json.loads(row["items_json"]))
    rest = [
        it
        for it in items
        if str(it.get("item_key") or auto_item_key_for_url(str(it.get("url") or ""))) != item_key
    ]
    if len(rest) == len(items):
        await cb.answer("Позиция не найдена.", show_alert=True)
        return
    if rest:
        await db.update_auto_batch_items(batch_id, rest)
    else:
        await db.update_auto_batch_items(batch_id, [])
        await db.update_auto_batch_status(batch_id, "closed")
    if cb.message:
        await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer("Пропущено")


@router.callback_query(F.data.startswith("auto:cancel:"))
async def auto_cancel_batch(cb: CallbackQuery, db: Database) -> None:
    batch_id = _batch_id_from_prefix(cb.data or "", "auto:cancel:")
    if not batch_id:
        await cb.answer("Некорректная кнопка.", show_alert=True)
        return
    row = await db.get_auto_batch(batch_id)
    if not row or row["status"] not in _PENDING:
        await cb.answer("Пакет не найден или уже обработан.", show_alert=True)
        return
    await db.update_auto_batch_status(batch_id, "cancelled")
    if cb.message:
        await cb.message.edit_reply_markup(reply_markup=None)
    if cb.message:
        await cb.message.answer(
            "Пакет отменён. Кнопки под отдельными черновиками могут ещё отображаться — "
            "повторное нажатие скажет, что пакет уже обработан.",
        )
    await cb.answer("Отменено")


@router.callback_query(F.data == "auto:cancel")
async def auto_cancel_legacy(cb: CallbackQuery) -> None:
    if cb.message:
        await cb.message.edit_reply_markup(reply_markup=None)
    if cb.message:
        await cb.message.answer(
            "Отменено (старая кнопка). Для новых пакетов используйте «Отмена пакет».",
            reply_markup=main_menu_kb(),
        )
    await cb.answer()
