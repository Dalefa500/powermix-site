from aiogram.fsm.state import State, StatesGroup


class CashForm(StatesGroup):
    waiting_for_sum = State()
    waiting_for_comment = State()
