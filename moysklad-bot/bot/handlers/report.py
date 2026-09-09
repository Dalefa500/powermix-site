from __future__ import annotations

import logging
from datetime import datetime

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
    """Income + expense + balance — for owner and director."""
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
    ]
    return "\n".join(lines)


async def build_balance_only_text(moysklad: MoySkladClient) -> str:
    """Just the cash balance — for regular employees, no income/expense figures."""
    lines = ["📊 Остаток кассы", "", *(await _get_balance_lines(moysklad))]
    return "\n".join(lines)


async def build_month_report_text(moysklad: MoySkladClient) -> str:
    """Day-by-day income/expense breakdown for the current calendar month."""
    now = datetime.now()
    start = now.replace(day=1)

    try:
        daily = await moysklad.get_daily_cash_summary(start, now)
    except MoySkladError:
        logger.exception("Failed to build month report")
        return "⚠️ Не получилось получить данные из МойСклад, попробуй позже."

    lines = [f"📅 Доход/расход по дням — {start.strftime('%B %Y')}", ""]

    total_income = 0.0
    total_expense = 0.0
    for day in sorted(daily.keys()):
        income = daily[day]["income"]
        expense = daily[day]["expense"]
        total_income += income
        total_expense += expense
        day_label = day[8:10] + "." + day[5:7]
        lines.append(f"{day_label}: доход {income:.2f} / расход {expense:.2f}")

    if not daily:
        lines.append("(пока нет записей за этот месяц)")

    lines += [
        "",
        f"Итого доход: {total_income:.2f}",
        f"Итого расход: {total_expense:.2f}",
        f"Итого прибыль: {total_income - total_expense:.2f}",
    ]
    return "\n".join(lines)


async def build_stock_text(moysklad: MoySkladClient) -> str:
    """Current stock levels per product/raw material."""
    try:
        stock = await moysklad.get_stock_report()
    except MoySkladError:
        logger.exception("Failed to fetch stock report")
        return "⚠️ Не получилось получить остатки из МойСклад, попробуй позже."

    if not stock:
        return "📦 Остатки пусты — в МойСклад нет товаров с остатком."

    lines = ["📦 Остатки на складе:", ""]
    for item in sorted(stock, key=lambda r: r["name"]):
        lines.append(f"• {item['name']}: {item['stock']:g}")
    return "\n".join(lines)


async def build_debts_text(moysklad: MoySkladClient) -> str:
    """Outstanding balance per counterparty."""
    try:
        debts = await moysklad.get_counterparty_debts()
    except MoySkladError:
        logger.exception("Failed to fetch counterparty debts")
        return "⚠️ Не получилось получить задолженность из МойСклад, попробуй позже."

    if not debts:
        return "📈 Задолженностей нет — все расчёты закрыты."

    they_owe = [d for d in debts if d["balance"] > 0]
    we_owe = [d for d in debts if d["balance"] < 0]

    lines = ["📈 Задолженность контрагентов:", ""]
    if they_owe:
        lines.append("Нам должны:")
        for d in sorted(they_owe, key=lambda r: -r["balance"]):
            lines.append(f"• {d['name']}: {d['balance']:.2f}")
        lines.append("")
    if we_owe:
        lines.append("Мы должны:")
        for d in sorted(we_owe, key=lambda r: r["balance"]):
            lines.append(f"• {d['name']}: {-d['balance']:.2f}")
    return "\n".join(lines).strip()


async def send_balance_report(message: Message, moysklad: MoySkladClient, config: Config) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id

    if user_id in config.management_ids:
        await message.answer(await build_full_report_text(moysklad))
    elif user_id in config.employee_ids:
        await message.answer(await build_balance_only_text(moysklad))
    else:
        await message.answer("Эта команда тебе недоступна.")


async def send_month_report(message: Message, moysklad: MoySkladClient) -> None:
    await message.answer(await build_month_report_text(moysklad))


async def send_stock_report(message: Message, moysklad: MoySkladClient) -> None:
    await message.answer(await build_stock_text(moysklad))


async def send_debts_report(message: Message, moysklad: MoySkladClient) -> None:
    await message.answer(await build_debts_text(moysklad))


@router.message(Command("today", "balance"))
async def balance_report(message: Message, moysklad: MoySkladClient, config: Config) -> None:
    await send_balance_report(message, moysklad, config)


@router.message(Command("month"))
async def month_report(message: Message, moysklad: MoySkladClient) -> None:
    await send_month_report(message, moysklad)


@router.message(Command("stock"))
async def stock_report(message: Message, moysklad: MoySkladClient) -> None:
    await send_stock_report(message, moysklad)


@router.message(Command("debts"))
async def debts_report(message: Message, moysklad: MoySkladClient) -> None:
    await send_debts_report(message, moysklad)
