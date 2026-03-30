from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# Тексты с reply-клавиатуры: не обрабатывать как «текст объявления» в FSM ручного поста.
MAIN_MENU_TEXTS: frozenset[str] = frozenset({"Ручной пост", "Автопостинг", "Статистика"})


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Ручной пост"), KeyboardButton(text="Автопостинг")],
            [KeyboardButton(text="Статистика")],
        ],
        resize_keyboard=True,
    )


def manual_after_preview_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Опубликовать", callback_data="pub:ok"),
                InlineKeyboardButton(text="Переписать", callback_data="pub:rewrite"),
            ],
            [InlineKeyboardButton(text="Отмена", callback_data="pub:cancel")],
        ]
    )


def auto_batch_summary_kb(batch_id: str) -> InlineKeyboardMarkup:
    """Сводка пакета (callback ≤ 64 байт: uuid 36 + префикс короткий)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Одобрить все",
                    callback_data=f"auto:all:{batch_id}",
                )
            ],
            [InlineKeyboardButton(text="Отмена пакет", callback_data=f"auto:cancel:{batch_id}")],
        ]
    )


def auto_item_kb(batch_id: str, item_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Одобрить",
                    callback_data=f"auto:yes:{batch_id}:{item_key}",
                ),
                InlineKeyboardButton(
                    text="Пропустить",
                    callback_data=f"auto:skip:{batch_id}:{item_key}",
                ),
            ],
        ]
    )


def auto_batch_kb(batch_id: str) -> InlineKeyboardMarkup:
    """Обратная совместимость со старыми сообщениями планировщика."""
    return auto_batch_summary_kb(batch_id)
