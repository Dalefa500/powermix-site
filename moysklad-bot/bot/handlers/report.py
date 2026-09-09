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
from ..currency import fmt
from ..keyboards import CP_PERIOD_DAYS, cp_period_choice_kb
from ..moysklad import MoySkladClient, MoySkladError

# Only these counterparties matter for the "Команда" report — everyone
# else is noise for this view (there are dozens of expense categories in
# the account's 5-year history). Keyed by the MoySklad search term, valued
# by the role label to actually show in the bot.
TRACKED_COUNTERPARTIES = {
    "Дивиденды": "💼 Инвестор (вы)",
    "Сулаймоншоев Убайд": "👔 Убайд — директор",
}

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
            lines.append(f"• {b['name']}: {fmt(b['balance'])}")
        lines.append(f"Итого остаток: {fmt(sum(b['balance'] for b in balances))}")
        return lines

    try:
        total = await moysklad.get_total_cash_balance_fallback()
        return [f"💼 Остаток в кассе (по всем ордерам с начала учёта): {fmt(total)}"]
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
        f"Доход за сегодня: {fmt(income)}",
        f"Расход за сегодня: {fmt(expense)}",
        f"Итог за сегодня: {fmt(income - expense)}",
        "",
        *(await _get_balance_lines(moysklad)),
    ]
    return "\n".join(lines)


async def build_balance_only_text(moysklad: MoySkladClient) -> str:
    """Just the cash balance — for regular employees, no income/expense figures."""
    lines = ["📊 Остаток кассы", "", *(await _get_balance_lines(moysklad))]
    return "\n".join(lines)


async def build_period_report_text(moysklad: MoySkladClient, period_key: str) -> str:
    now = datetime.now()
    label, days = CP_PERIOD_DAYS[period_key]
    start = now - timedelta(days=days)
    title = f"за {label.lower()}"

    try:
        daily = await moysklad.get_daily_cash_summary(start, now)
    except MoySkladError:
        logger.exception("Failed to build period report")
        return "⚠️ Не получилось получить данные из МойСклад, попробуй позже."

    total_income = sum(d["income"] for d in daily.values())
    total_expense = sum(d["expense"] for d in daily.values())

    lines = [f"📅 Отчёт {title}", ""]

    if days <= 92:
        for day in sorted(daily):
            d = daily[day]
            day_label = day[8:10] + "." + day[5:7]
            lines.append(f"{day_label}: доход {fmt(d['income'])} / расход {fmt(d['expense'])}")
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
            lines.append(f"{month_key}: доход {fmt(m['income'])} / расход {fmt(m['expense'])}")
        if not monthly:
            lines.append("(пока нет записей за этот период)")

    lines += [
        "",
        f"Итого доход: {fmt(total_income)}",
        f"Итого расход: {fmt(total_expense)}",
        f"Итого прибыль: {fmt(total_income - total_expense)}",
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
            lines.append(f"• {d['name']}: {fmt(d['balance'])}")
        lines.append("")
    if we_owe:
        lines.append("Мы должны:")
        for d in sorted(we_owe, key=lambda r: r["balance"]):
            lines.append(f"• {d['name']}: {fmt(-d['balance'])}")
    return "\n".join(lines).strip()


async def build_counterparty_report_text(
    moysklad: MoySkladClient, entry: dict, period_label: str, period_start: datetime
) -> str:
    """Today's expense plus a breakdown of the whole selected period (the
    same one chosen in the "Команда" list — day-by-day if it's a month or
    less, month-by-month if longer) for one counterparty.
    """
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        period_data = await moysklad.get_counterparty_expense_breakdown(
            entry["href"], period_start, now
        )
        today_data = await moysklad.get_counterparty_expense_breakdown(
            entry["href"], today_start, now
        )
    except MoySkladError:
        logger.exception("Failed to build counterparty report")
        return "⚠️ Не получилось получить данные из МойСклад, попробуй позже."

    lines = [
        entry["name"],
        "",
        f"За сегодня: {fmt(today_data['total'])}",
        f"Всего ({period_label}): {fmt(period_data['total'])}",
    ]

    daily = period_data["daily"]
    if daily:
        span_days = (now - period_start).days
        lines.append("")
        if span_days <= 92:
            lines.append("По дням:")
            for day in sorted(daily):
                day_label = day[8:10] + "." + day[5:7]
                lines.append(f"{day_label}: {fmt(daily[day])}")
        else:
            monthly: dict[str, float] = defaultdict(float)
            for day, amount in daily.items():
                monthly[day[:7]] += amount
            lines.append("По месяцам:")
            for month_key in sorted(monthly):
                lines.append(f"{month_key}: {fmt(monthly[month_key])}")

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
    await message.answer(
        "За какой период показать отчёт?", reply_markup=cp_period_choice_kb("period")
    )


async def send_counterparty_period_choice(message: Message) -> None:
    await message.answer(
        "За какой период показать расход по команде?",
        reply_markup=cp_period_choice_kb(),
    )


async def _show_counterparty_list(
    edit_target: Message, state: FSMContext, moysklad: MoySkladClient, period_key: str
) -> None:
    label, days = CP_PERIOD_DAYS[period_key]
    now = datetime.now()
    start = now - timedelta(days=days)
    title = f"за {label.lower()}"

    await edit_target.edit_text(f"⏳ Считаю расход по команде {title}...")

    try:
        top = await moysklad.get_named_counterparty_expenses(TRACKED_COUNTERPARTIES, start, now)
    except MoySkladError:
        logger.exception("Failed to fetch counterparty list")
        await edit_target.edit_text("⚠️ Не получилось получить данные из МойСклад, попробуй позже.")
        return

    if not top:
        await edit_target.edit_text(f"Нет расходов у отслеживаемых людей {title}.")
        return

    await state.update_data(cp_choices=top, cp_period_label=title, cp_start=start.isoformat())
    builder = InlineKeyboardBuilder()
    for i, entry in enumerate(top):
        builder.button(
            text=f"{entry['name']} — {entry['total']:.0f} с.", callback_data=f"cpexp:{i}"
        )
    builder.adjust(1)
    await edit_target.edit_text(
        f"Команда {title}. По кому показать расход по дням?",
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
async def counterparties_command(message: Message) -> None:
    await send_counterparty_period_choice(message)


@router.callback_query(F.data.startswith("period:"))
async def period_chosen(callback: CallbackQuery, moysklad: MoySkladClient) -> None:
    period_key = callback.data.split(":", 1)[1]
    if period_key not in CP_PERIOD_DAYS:
        await callback.answer("Неизвестный период", show_alert=True)
        return
    text = await build_period_report_text(moysklad, period_key)
    await callback.message.edit_text(text)
    await callback.answer()


@router.callback_query(F.data.startswith("cpperiod:"))
async def counterparty_period_chosen(
    callback: CallbackQuery, state: FSMContext, moysklad: MoySkladClient
) -> None:
    period_key = callback.data.split(":", 1)[1]
    if period_key not in CP_PERIOD_DAYS:
        await callback.answer("Неизвестный период", show_alert=True)
        return
    await callback.answer()
    await _show_counterparty_list(callback.message, state, moysklad, period_key)


@router.callback_query(F.data.startswith("cpexp:"))
async def counterparty_chosen(
    callback: CallbackQuery, state: FSMContext, moysklad: MoySkladClient
) -> None:
    index = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    choices: list[dict] = data.get("cp_choices", [])
    period_label = data.get("cp_period_label", "за выбранный период")
    period_start_iso = data.get("cp_start")
    if index >= len(choices) or not period_start_iso:
        await callback.answer("Список устарел, открой «Команда» заново", show_alert=True)
        return
    period_start = datetime.fromisoformat(period_start_iso)
    text = await build_counterparty_report_text(moysklad, choices[index], period_label, period_start)
    await callback.message.edit_text(text)
    await callback.answer()
