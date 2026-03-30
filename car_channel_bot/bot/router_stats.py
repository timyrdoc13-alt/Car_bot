from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

router = Router(name="stats")


@router.message(F.text == "Статистика")
async def stats_btn(message: Message, stats_svc) -> None:
    text = await stats_svc.summary_text()
    await message.answer(text)
