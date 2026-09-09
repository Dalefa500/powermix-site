from __future__ import annotations

import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ..keyboards import BTN_EXPENSE, BTN_INCOME, cancel_kb, main_reply_kb
from ..moysklad import MoySkladClient, MoySkladError
from ..states import CashForm

logger = logging.getLogger(__name__)

# Flow entry (tapping a menu button) is dispatched centrally from start.py,
# with StateFilter("*"), so a menu tap always wins even if the user was
# mid-way through typing something else. This router only owns the
# in-progress FSM steps.
router = Router(name="cash")

KIND_LABELS = {
    "expense": "Расход",
    "income": "Доход",
}

TEXT_TO_KIND = {
    BTN_EXPENSE: "expense",
    BTN_INCOME: "income",
}


async def enter_cash_flow(message: Message, state: FSMContext, kind: str) -> None:
    await state.update_data(kind=kind)
    await state.set_state(CashForm.waiting_for_sum)
    await message.answer(
        f"{KIND_LABELS[kind]}. Введи сумму (только число, например 1500):",
        reply_markup=cancel_kb(),
    )


@router.message(CashForm.waiting_for_sum)
async def cash_sum_entered(message: Message, state: FSMContext) -> None:
    text = (message.text or "").replace(",", ".").strip()
    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Не похоже на число. Введи сумму ещё раз, например 1500:")
        return

    await state.update_data(amount=amount)
    await state.set_state(CashForm.waiting_for_comment)
    await message.answer("Коротко опиши, за что (например: «аренда за сентябрь»):")


@router.message(CashForm.waiting_for_comment)
async def cash_comment_entered(
    message: Message, state: FSMContext, moysklad: MoySkladClient
) -> None:
    data = await state.get_data()
    kind = data["kind"]
    amount = data["amount"]
    comment = (message.text or "").strip() or "(без комментария)"
    employee = message.from_user.full_name if message.from_user else "неизвестно"

    await message.answer("Сохраняю в МойСклад...")

    try:
        if kind == "income":
            await moysklad.create_cash_in(amount, comment, employee)
        else:
            await moysklad.create_cash_out(amount, comment, employee)
    except MoySkladError:
        logger.exception("Failed to create cash document in MoySklad")
        await message.answer(
            "⚠️ Не получилось сохранить в МойСклад (ошибка API). Сообщи администратору — "
            "запись не потеряна, вот детали, чтобы внести вручную:\n"
            f"{KIND_LABELS[kind]}, {amount:.2f}, «{comment}», от {employee}"
        )
    else:
        await message.answer(
            f"Готово ✅ {KIND_LABELS[kind]}: {amount:.2f} — «{comment}» записано в МойСклад."
        )

    await state.clear()
    await message.answer("Выбери действие в меню внизу 👇", reply_markup=main_reply_kb())
