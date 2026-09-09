from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..config import Config
from ..keyboards import PERIOD_LABELS, period_choice_kb
from ..moysklad import MoySkladClient, MoySkladError

COUNTERPARTY_LOOKBACK_DAYS = 365
COUNTERPARTY_LOOKBACK_LABEL = "последний год"

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


def _period_start(period: str, now: datetime) -> tuple[datetime, str]:
    if period == "day":
        return now.replace(hour=0, minute=0, second=0, microsecond=0), f"за {now.strftime('%d.%m.%Y')}"
    if period == "month":
        return now.replace(day=1), f"за {now.strftime('%B %Y')}"
    if period == "half":
        return now - timedelta(days=182), "за полгода"
    if period == "year":
        return now - timedelta(days=365), "за год"
    raise ValueError(f"Unknown period: {period}")


async def build_period_report_text(moysklad: MoySkladClient, period: str) -> str:
    now = datetime.now()
    start, title = _period_start(period, now)

    try:
        daily = await moysklad.get_daily_cash_summary(start, now)
    except MoySkladError:
        logger.exception("Failed to build period report")
        return "⚠️ Не получилось получить данные из МойСклад, попробуй позже."

    total_income = sum(d["income"] for d in daily.values())
    total_expense = sum(d["expense"] for d in daily.values())

    lines = [f"📅 Отчёт {title}", ""]

    if period in ("day", "month"):
        for day in sorted(daily):
            d = daily[day]
            day_label = day[8:10] + "." + day[5:7]
            lines.append(f"{day_label}: доход {d['income']:.2f} / расход {d['expense']:.2f}")
        if not daily:
            lines.append("(пока нет записей за этот период)")
    else:
        monthly: dict[str, dict[str, float]] = defaultdict(lambda: {"income": 0.0, "expense": 0.0})
        for day, d in daily.items():
            month_key = day[:7]
            monthly[month_key]["income"] += d["income"]
            monthly[month_key]["expense"] += d["expense"]
        for month_key in sorted(monthly):
            m = monthly[month_key]
            lines.append(f"{month_key}: доход {m['income']:.2f} / расход {m['expense']:.2f}")
        if not monthly:
            lines.append("(пока нет записей за этот период)")

    lines += [
        "",
        f"Итого доход: {total_income:.2f}",
        f"Итого расход: {total_expense:.2f}",
        f"Итого прибыль: {total_income - total_expense:.2f}",
    ]
    return "\n".join(lines)


async def build_stock_text(moysklad: MoySkladClient) -> str:
    """Stock levels grouped by product folder (raw materials vs finished
    goods, if the account keeps them in separate MoySklad folders)."""
    try:
        stock = await moysklad.get_stock_report()
    except MoySkladError:
        logger.exception("Failed to fetch stock report")
        return "⚠️ Не получилось получить остатки из МойСклад, попробуй позже."

    if not stock:
        return "📦 Остатки пусты — в МойСклад нет товаров с остатком."

    by_folder: dict[str, list[dict]] = defaultdict(list)
    for item in stock:
        by_folder[item["folder"]].append(item)

    lines = ["📦 Остатки на складе:"]
    for folder in sorted(by_folder):
        lines.append("")
        lines.append(f"— {folder} —")
        for item in sorted(by_folder[folder], key=lambda r: r["name"]):
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


async def build_counterparty_report_text(moysklad: MoySkladClient, entry: dict) -> str:
    """Total / this-month / today expense for one counterparty, plus a
    day-by-day breakdown for the current month — exactly what you'd want to
    know about how much money went to one specific person or category
    (e.g. the director's salary/expenses).
    """
    now = datetime.now()
    month_start = now.replace(day=1)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        month_data = await moysklad.get_counterparty_expense_breakdown(
            entry["href"], month_start, now
        )
        today_data = await moysklad.get_counterparty_expense_breakdown(
            entry["href"], today_start, now
        )
    except MoySkladError:
        logger.exception("Failed to build counterparty report")
        return "⚠️ Не получилось получить данные из МойСклад, попробуй позже."

    lines = [
        f"👤 {entry['name']}",
        "",
        f"За сегодня: {today_data['total']:.2f}",
        f"За этот месяц: {month_data['total']:.2f}",
        f"Всего ({COUNTERPARTY_LOOKBACK_LABEL}): {entry['total']:.2f}",
    ]

    if month_data["daily"]:
        lines.append("")
        lines.append("По дням в этом месяце:")
        for day in sorted(month_data["daily"]):
            day_label = day[8:10] + "." + day[5:7]
            lines.append(f"{day_label}: {month_data['daily'][day]:.2f}")

    return "\n".join(lines)


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


async def send_period_choice(message: Message) -> None:
    await message.answer("За какой период показать отчёт?", reply_markup=period_choice_kb())


async def send_counterparty_choice(
    message: Message, state: FSMContext, moysklad: MoySkladClient
) -> None:
    await message.answer(f"⏳ Считаю расход по контрагентам за {COUNTERPARTY_LOOKBACK_LABEL}...")

    now = datetime.now()
    start = now - timedelta(days=COUNTERPARTY_LOOKBACK_DAYS)
    try:
        top = await moysklad.get_expense_by_counterparty(start, now)
    except MoySkladError:
        logger.exception("Failed to fetch counterparty list")
        await message.answer("⚠️ Не получилось получить данные из МойСклад, попробуй позже.")
        return

    if not top:
        await message.answer("Пока нет расходов, привязанных к контрагенту.")
        return

    await state.update_data(cp_choices=top)
    builder = InlineKeyboardBuilder()
    for i, entry in enumerate(top):
        builder.button(text=f"{entry['name']} — {entry['total']:.0f}", callback_data=f"cpexp:{i}")
    builder.adjust(1)
    await message.answer(
        "По какому контрагенту показать расход по дням/месяцам?",
        reply_markup=builder.as_markup(),
    )


async def send_stock_report(message: Message, moysklad: MoySkladClient) -> None:
    await message.answer(await build_stock_text(moysklad))


async def send_debts_report(message: Message, moysklad: MoySkladClient) -> None:
    await message.answer(await build_debts_text(moysklad))


@router.message(Command("today", "balance"))
async def balance_report(message: Message, moysklad: MoySkladClient, config: Config) -> None:
    await send_balance_report(message, moysklad, config)


@router.message(Command("report"))
async def report_command(message: Message) -> None:
    await send_period_choice(message)


@router.message(Command("stock"))
async def stock_report(message: Message, moysklad: MoySkladClient) -> None:
    await send_stock_report(message, moysklad)


@router.message(Command("debts"))
async def debts_report(message: Message, moysklad: MoySkladClient) -> None:
    await send_debts_report(message, moysklad)


@router.message(Command("counterparties"))
async def counterparties_command(message: Message, state: FSMContext, moysklad: MoySkladClient) -> None:
    await send_counterparty_choice(message, state, moysklad)


@router.callback_query(F.data.startswith("period:"))
async def period_chosen(callback: CallbackQuery, moysklad: MoySkladClient) -> None:
    period = callback.data.split(":", 1)[1]
    if period not in PERIOD_LABELS:
        await callback.answer("Неизвестный период", show_alert=True)
        return
    text = await build_period_report_text(moysklad, period)
    await callback.message.edit_text(text)
    await callback.answer()


@router.callback_query(F.data.startswith("cpexp:"))
async def counterparty_chosen(
    callback: CallbackQuery, state: FSMContext, moysklad: MoySkladClient
) -> None:
    index = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    choices: list[dict] = data.get("cp_choices", [])
    if index >= len(choices):
        await callback.answer("Список устарел, открой «Контрагенты» заново", show_alert=True)
        return
    text = await build_counterparty_report_text(moysklad, choices[index])
    await callback.message.edit_text(text)
    await callback.answer()
