from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

BTN_EXPENSE = "💸 Расход"
BTN_INCOME = "💰 Доход"
BTN_BALANCE = "📊 Баланс"
BTN_MONTH = "📅 За месяц"
BTN_STOCK = "📦 Остатки"
BTN_DEBTS = "📈 Долги"

NAV_BUTTONS = (BTN_EXPENSE, BTN_INCOME, BTN_BALANCE, BTN_MONTH, BTN_STOCK, BTN_DEBTS)


def main_reply_kb() -> ReplyKeyboardMarkup:
    """Persistent bottom menu — always visible, works like an app's tab bar
    instead of buttons that scroll away in the chat history."""
    builder = ReplyKeyboardBuilder()
    for text in NAV_BUTTONS:
        builder.button(text=text)
    builder.adjust(2, 2, 2)
    return builder.as_markup(resize_keyboard=True)


def cancel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="cancel")
    return builder.as_markup()
