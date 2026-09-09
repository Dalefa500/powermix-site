from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..config import Config
from ..keyboards import BTN_BALANCE, BTN_COUNTERPARTIES, BTN_DEBTS, BTN_REPORT, BTN_STOCK, main_reply_kb
from ..moysklad import MoySkladClient
from .cash import TEXT_TO_KIND, enter_cash_flow
from .report import (
    send_balance_report,
    send_counterparty_period_choice,
    send_debts_report,
    send_period_choice,
    send_stock_report,
)

# This router is included first (see handlers/__init__.py), so its
# StateFilter("*") navigation handlers below always get first look at every
# message — a menu tap wins even if the user was mid-way through typing
# something in another flow, instead of being swallowed by that flow's step
# handler.
router = Router(name="start")

WELCOME = (
    "Привет! Я бот учёта цеха.\n\n"
    "Меню закреплено внизу экрана — им и пользуйся. Кнопку можно нажать "
    "в любой момент, даже посреди ввода: я пойму, что нужно начать заново."
)


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(WELCOME, reply_markup=main_reply_kb())


@router.message(StateFilter("*"), F.text.in_(TEXT_TO_KIND.keys()))
async def nav_cash(message: Message, state: FSMContext) -> None:
    await state.clear()
    await enter_cash_flow(message, state, TEXT_TO_KIND[message.text])


@router.message(StateFilter("*"), F.text == BTN_BALANCE)
async def nav_balance(
    message: Message, state: FSMContext, moysklad: MoySkladClient, config: Config
) -> None:
    await state.clear()
    await send_balance_report(message, moysklad, config)


@router.message(StateFilter("*"), F.text == BTN_REPORT)
async def nav_report(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_period_choice(message)


@router.message(StateFilter("*"), F.text == BTN_STOCK)
async def nav_stock(message: Message, state: FSMContext, moysklad: MoySkladClient) -> None:
    await state.clear()
    await send_stock_report(message, moysklad)


@router.message(StateFilter("*"), F.text == BTN_DEBTS)
async def nav_debts(message: Message, state: FSMContext, moysklad: MoySkladClient) -> None:
    await state.clear()
    await send_debts_report(message, moysklad)


@router.message(StateFilter("*"), F.text == BTN_COUNTERPARTIES)
async def nav_counterparties(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_counterparty_period_choice(message)


@router.callback_query(F.data == "cancel")
async def cancel_any(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Отменено.", reply_markup=None)
    await callback.message.answer(
        "Выбери действие в меню внизу 👇", reply_markup=main_reply_kb()
    )
    await callback.answer()
