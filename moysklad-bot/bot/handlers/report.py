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
from ..tables import render_table, render_table_chunks

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


async def _balance_block(moysklad: MoySkladClient) -> str:
    balances: list[dict] | None = None
    try:
        balances = await moysklad.get_account_balances()
    except MoySkladError:
        logger.info("byaccount money report unavailable, falling back to manual sum")

    if balances:
        table = render_table(
            ["Счёт", "Остаток"],
            [[b["name"], fmt(b["balance"])] for b in balances],
        )
        total = fmt(sum(b["balance"] for b in balances))
        return f"💼 Остаток по кассам/счетам:\n{table}\nИтого остаток: {total}"

    try:
        total = await moysklad.get_total_cash_balance_fallback()
        return f"💼 Остаток в кассе (по всем ордерам с начала учёта): {fmt(total)}"
    except MoySkladError:
        logger.exception("Failed to compute fallback cash balance")
        return "⚠️ Не удалось посчитать остаток в кассе."


async def build_full_report_text(moysklad: MoySkladClient) -> str:
    """Income + expense + balance — for owner and director."""
    try:
        income = await moysklad.sum_cash_today("cashin")
        expense = await moysklad.sum_cash_today("cashout")
    except MoySkladError:
        logger.exception("Failed to fetch today's cashin/cashout")
        return "⚠️ Не получилось получить данные из МойСклад, попробуй позже."

    today_table = render_table(
        ["Сегодня", "Сумма"],
        [
            ["Доход", fmt(income)],
            ["Расход", fmt(expense)],
            ["Итог", fmt(income - expense)],
        ],
    )

    return (
        f"📊 Отчёт по кассе\n\n{today_table}\n\n{await _balance_block(moysklad)}"
    )


async def build_balance_only_text(moysklad: MoySkladClient) -> str:
    """Just the cash balance — for regular employees, no income/expense figures."""
    return f"📊 Остаток кассы\n\n{await _balance_block(moysklad)}"


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

    if days <= 92:
        rows = [
            [day[8:10] + "." + day[5:7], fmt(daily[day]["income"]), fmt(daily[day]["expense"])]
            for day in sorted(daily)
        ]
        table_headers = ["Дата", "Доход", "Расход"]
    else:
        monthly: dict[str, dict[str, float]] = defaultdict(lambda: {"income": 0.0, "expense": 0.0})
        for day, d in daily.items():
            month_key = day[:7]
            monthly[month_key]["income"] += d["income"]
            monthly[month_key]["expense"] += d["expense"]
        rows = [
            [month_key, fmt(monthly[month_key]["income"]), fmt(monthly[month_key]["expense"])]
            for month_key in sorted(monthly)
        ]
        table_headers = ["Месяц", "Доход", "Расход"]

    body = render_table(table_headers, rows) if rows else "(пока нет записей за этот период)"

    totals = render_table(
        ["Итого", "Сумма"],
        [
            ["Доход", fmt(total_income)],
            ["Расход", fmt(total_expense)],
            ["Прибыль", fmt(total_income - total_expense)],
        ],
    )

    return f"📅 Отчёт {title}\n\n{body}\n\n{totals}"


async def build_stock_blocks(moysklad: MoySkladClient) -> list[str]:
    """Stock levels grouped by product folder (raw materials vs finished
    goods, if the account keeps them in separate MoySklad folders).

    Returns a list of ready-to-send message texts rather than one big
    string — a long inventory (years of accumulated products) can easily
    exceed Telegram's ~4096 character message limit, so each folder (and,
    if a folder alone is too long, each chunk of it) becomes its own
    message.
    """
    try:
        stock = await moysklad.get_stock_report()
    except MoySkladError:
        logger.exception("Failed to fetch stock report")
        return ["⚠️ Не получилось получить остатки из МойСклад, попробуй позже."]

    if not stock:
        return ["📦 Остатки пусты — в МойСклад нет товаров с остатком."]

    by_folder: dict[str, list[dict]] = defaultdict(list)
    for item in stock:
        by_folder[item["folder"]].append(item)

    blocks = ["📦 Остатки на складе:"]
    for folder in sorted(by_folder):
        rows = [
            [item["name"], f"{item['stock']:g}"]
            for item in sorted(by_folder[folder], key=lambda r: r["name"])
        ]
        tables = render_table_chunks(["Товар", "Остаток"], rows)
        for i, table in enumerate(tables):
            title = f"— {folder} —" if i == 0 else f"— {folder} (продолжение) —"
            blocks.append(f"{title}\n{table}")
    return blocks


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

    blocks = ["📈 Задолженность контрагентов:"]
    if they_owe:
        table = render_table(
            ["Нам должны", "Сумма"],
            [[d["name"], fmt(d["balance"])] for d in sorted(they_owe, key=lambda r: -r["balance"])],
        )
        blocks.append(table)
    if we_owe:
        table = render_table(
            ["Мы должны", "Сумма"],
            [[d["name"], fmt(-d["balance"])] for d in sorted(we_owe, key=lambda r: r["balance"])],
        )
        blocks.append(table)
    return "\n\n".join(blocks)


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

    summary = render_table(
        ["Период", "Сумма"],
        [
            ["Сегодня", fmt(today_data["total"])],
            [period_label, fmt(period_data["total"])],
        ],
    )

    result = f"{entry['name']}\n\n{summary}"

    daily = period_data["daily"]
    if daily:
        span_days = (now - period_start).days
        if span_days <= 92:
            rows = [[day[8:10] + "." + day[5:7], fmt(daily[day])] for day in sorted(daily)]
            table = render_table(["Дата", "Сумма"], rows)
        else:
            monthly: dict[str, float] = defaultdict(float)
            for day, amount in daily.items():
                monthly[day[:7]] += amount
            rows = [[month_key, fmt(monthly[month_key])] for month_key in sorted(monthly)]
            table = render_table(["Месяц", "Сумма"], rows)
        result += f"\n\n{table}"

    return result


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
    for block in await build_stock_blocks(moysklad):
        await message.answer(block)


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
