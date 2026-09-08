from aiogram.fsm.state import State, StatesGroup


class CashForm(StatesGroup):
    waiting_for_sum = State()
    waiting_for_comment = State()


class ShipmentForm(StatesGroup):
    waiting_for_client_query = State()
    choosing_client = State()
    waiting_for_new_client_name = State()
    waiting_for_product_query = State()
    choosing_product = State()
    waiting_for_quantity = State()
    waiting_for_price = State()
    asking_add_more = State()
    waiting_for_comment = State()
