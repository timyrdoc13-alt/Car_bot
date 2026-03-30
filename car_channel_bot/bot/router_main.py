from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from car_channel_bot.bot.keyboards import main_menu_kb

router = Router(name="main")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Выберите режим ниже.",
        reply_markup=main_menu_kb(),
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message, stats_svc) -> None:
    text = await stats_svc.summary_text()
    await message.answer(text)
