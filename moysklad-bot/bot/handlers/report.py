from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ..config import Config
from ..moysklad import MoySkladClient, MoySkladError

logger = logging.getLogger(__name__)

router = Router(name="report")


async def build_report_text(moysklad: MoySkladClient) -> str:
    """Today's income/expense plus the current cash balance.

    Shared between the /today and /balance commands and the scheduled daily
    push, so both always show the same numbers.
    """
    try:
        income = await moysklad.sum_cash_today("cashin")
        expense = await moysklad.sum_cash_today("cashout")
    except MoySkladError:
        logger.exception("Failed to fetch today's cashin/cashout")
        return "⚠️ Не получилось получить данные из МойСклад, попробуй позже."

    lines = [
        "📊 Отчёт по кассе",
        "",
        f"Доход за сегодня: {income:.2f}",
        f"Расход за сегодня: {expense:.2f}",
        f"Итог за сегодня: {income - expense:.2f}",
        "",
    ]

    balances: list[dict] | None = None
    try:
        balances = await moysklad.get_account_balances()
    except MoySkladError:
        logger.info("byaccount money report unavailable, falling back to manual sum")

    if balances:
        lines.append("💼 Остаток по кассам/счетам:")
        for b in balances:
            lines.append(f"• {b['name']}: {b['balance']:.2f}")
        lines.append(f"Итого остаток: {sum(b['balance'] for b in balances):.2f}")
    else:
        try:
            total = await moysklad.get_total_cash_balance_fallback()
            lines.append(f"💼 Остаток в кассе (по всем ордерам с начала учёта): {total:.2f}")
        except MoySkladError:
            logger.exception("Failed to compute fallback cash balance")
            lines.append("⚠️ Не удалось посчитать остаток в кассе.")

    lines.append("")
    lines.append("Отгрузки и подробности — в МойСклад.")
    return "\n".join(lines)


@router.message(Command("today", "balance"))
async def today_report(message: Message, moysklad: MoySkladClient, config: Config) -> None:
    if not message.from_user or message.from_user.id not in config.owner_ids:
        await message.answer("Эта команда доступна только владельцу.")
        return

    await message.answer(await build_report_text(moysklad))
