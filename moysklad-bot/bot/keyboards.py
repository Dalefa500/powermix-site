from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

BTN_EXPENSE = "💸 Расход"
BTN_INCOME = "💰 Доход"
BTN_SHIPMENT = "📦 Отгрузка"
BTN_OTHER = "🧾 Прочий расход"
BTN_BALANCE = "📊 Баланс"

NAV_BUTTONS = (BTN_EXPENSE, BTN_INCOME, BTN_SHIPMENT, BTN_OTHER, BTN_BALANCE)


def main_reply_kb() -> ReplyKeyboardMarkup:
    """Persistent bottom menu — always visible, works like an app's tab bar
    instead of buttons that scroll away in the chat history."""
    builder = ReplyKeyboardBuilder()
    for text in NAV_BUTTONS:
        builder.button(text=text)
    builder.adjust(2, 2, 1)
    return builder.as_markup(resize_keyboard=True)


def confirm_kb(yes_data: str, no_data: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да", callback_data=yes_data)
    builder.button(text="❌ Нет", callback_data=no_data)
    builder.adjust(2)
    return builder.as_markup()


def cancel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="cancel")
    return builder.as_markup()
