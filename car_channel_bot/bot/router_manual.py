from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from car_channel_bot.bot.keyboards import MAIN_MENU_TEXTS, main_menu_kb, manual_after_preview_kb
from car_channel_bot.bot.states import ManualPostStates
from car_channel_bot.db.repositories import Database
from car_channel_bot.services.llm import LLMService
from car_channel_bot.services.publisher import ChannelPublisher

router = Router(name="manual")


@router.message(F.text == "Ручной пост")
async def manual_entry(message: Message, state: FSMContext, draft_store) -> None:
    uid = message.from_user.id
    draft_store.clear(uid)
    await state.set_state(ManualPostStates.waiting_photos)
    await message.answer(
        "Пришлите одно или несколько фото (можно альбомом). "
        "Затем одним сообщением — текст объявления.",
    )


@router.message(ManualPostStates.waiting_photos, F.photo)
async def manual_collect_photo(message: Message, draft_store) -> None:
    uid = message.from_user.id
    d = draft_store.get(uid)
    d.photo_file_ids.append(message.photo[-1].file_id)
    await message.answer(
        f"Фото сохранено ({len(d.photo_file_ids)}). Когда закончите — одним сообщением пришлите текст.",
    )


@router.message(ManualPostStates.waiting_photos, F.text, ~F.text.in_(MAIN_MENU_TEXTS))
async def manual_photos_then_text(
    message: Message,
    state: FSMContext,
    draft_store,
    llm: LLMService,
) -> None:
    uid = message.from_user.id
    d = draft_store.get(uid)
    if not d.photo_file_ids:
        await message.answer("Сначала пришлите хотя бы одно фото.")
        return
    d.raw_text = message.text or ""
    await _generate_preview(message, state, draft_store, llm)


@router.message(ManualPostStates.waiting_text, F.text, ~F.text.in_(MAIN_MENU_TEXTS))
async def manual_rewrite_text(
    message: Message,
    state: FSMContext,
    draft_store,
    llm: LLMService,
) -> None:
    uid = message.from_user.id
    d = draft_store.get(uid)
    d.raw_text = message.text or ""
    await _generate_preview(message, state, draft_store, llm)


async def _generate_preview(
    message: Message,
    state: FSMContext,
    draft_store,
    llm: LLMService,
) -> None:
    uid = message.from_user.id
    d = draft_store.get(uid)
    raw = LLMService.build_prompt_from_parsed_fields(
        {"Сырой текст": d.raw_text, "Источник": "ручной пост"}
    )
    cap = await llm.generate_caption(raw)
    await state.set_state(ManualPostStates.preview)
    await state.update_data(preview_caption=cap)
    await message.answer(cap, reply_markup=manual_after_preview_kb())


@router.callback_query(F.data == "pub:ok")
async def manual_publish(
    cb: CallbackQuery,
    state: FSMContext,
    draft_store,
    publisher: ChannelPublisher,
    db: Database,
) -> None:
    data = await state.get_data()
    cap = data.get("preview_caption") or ""
    uid = cb.from_user.id
    d = draft_store.get(uid)
    mid = await publisher.publish_from_file_ids(file_ids=d.photo_file_ids, caption=cap)
    await db.insert_post(
        channel_message_id=mid,
        source="manual",
        admin_id=uid,
        caption=cap,
    )
    draft_store.clear(uid)
    await state.clear()
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer("Опубликовано в канал.", reply_markup=main_menu_kb())
    await cb.answer()


@router.callback_query(F.data == "pub:rewrite")
async def manual_rewrite_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ManualPostStates.waiting_text)
    await cb.message.answer("Пришлите новый текст объявления.")
    await cb.answer()


@router.callback_query(F.data == "pub:cancel")
async def manual_cancel(cb: CallbackQuery, state: FSMContext, draft_store) -> None:
    draft_store.clear(cb.from_user.id)
    await state.clear()
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer("Отменено.", reply_markup=main_menu_kb())
    await cb.answer()
