from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ..config import Config
from ..moysklad import MoySkladClient, MoySkladError

logger = logging.getLogger(__name__)

router = Router(name="report")


async def _get_balance_lines(moysklad: MoySkladClient) -> list[str]:
    balances: list[dict] | None = None
    try:
        balances = await moysklad.get_account_balances()
    except MoySkladError:
        logger.info("byaccount money report unavailable, falling back to manual sum")

    if balances:
        lines = ["💼 Остаток по кассам/счетам:"]
        for b in balances:
            lines.append(f"• {b['name']}: {b['balance']:.2f}")
        lines.append(f"Итого остаток: {sum(b['balance'] for b in balances):.2f}")
        return lines

    try:
        total = await moysklad.get_total_cash_balance_fallback()
        return [f"💼 Остаток в кассе (по всем ордерам с начала учёта): {total:.2f}"]
    except MoySkladError:
        logger.exception("Failed to compute fallback cash balance")
        return ["⚠️ Не удалось посчитать остаток в кассе."]


async def build_full_report_text(moysklad: MoySkladClient) -> str:
    """Income + expense + balance — for owners and directors only."""
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
        *(await _get_balance_lines(moysklad)),
        "",
        "Отгрузки и подробности — в МойСклад.",
    ]
    return "\n".join(lines)


async def build_balance_only_text(moysklad: MoySkladClient) -> str:
    """Just the cash balance — for regular employees, no income/expense figures."""
    lines = ["📊 Остаток кассы", "", *(await _get_balance_lines(moysklad))]
    return "\n".join(lines)


@router.message(Command("today", "balance"))
async def balance_report(message: Message, moysklad: MoySkladClient, config: Config) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id

    if user_id in config.management_ids:
        await message.answer(await build_full_report_text(moysklad))
    elif user_id in config.employee_ids:
        await message.answer(await build_balance_only_text(moysklad))
    else:
        await message.answer("Эта команда тебе недоступна.")
