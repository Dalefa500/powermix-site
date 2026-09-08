from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ..config import Config
from ..moysklad import MoySkladClient, MoySkladError

router = Router(name="report")


@router.message(Command("today"))
async def today_report(message: Message, moysklad: MoySkladClient, config: Config) -> None:
    if not message.from_user or message.from_user.id not in config.owner_ids:
        await message.answer("Эта команда доступна только владельцу.")
        return

    try:
        income = await moysklad.sum_cash_today("cashin")
        expense = await moysklad.sum_cash_today("cashout")
    except MoySkladError:
        await message.answer("Не получилось получить данные из МойСклад, попробуй позже.")
        return

    await message.answer(
        "📊 Итоги за сегодня:\n"
        f"Доход: {income:.2f}\n"
        f"Расход: {expense:.2f}\n"
        f"Баланс: {income - expense:.2f}\n\n"
        "Отгрузки и подробности — в МойСклад."
    )
