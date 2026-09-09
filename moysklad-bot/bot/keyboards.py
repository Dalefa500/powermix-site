from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

BTN_EXPENSE = "💸 Расход"
BTN_INCOME = "💰 Доход"
BTN_BALANCE = "📊 Баланс"
BTN_REPORT = "📅 Отчёт"
BTN_STOCK = "📦 Остатки"
BTN_DEBTS = "📈 Долги"
BTN_COUNTERPARTIES = "👥 Команда"

NAV_BUTTONS = (
    BTN_EXPENSE,
    BTN_INCOME,
    BTN_BALANCE,
    BTN_REPORT,
    BTN_STOCK,
    BTN_DEBTS,
    BTN_COUNTERPARTIES,
)

PERIOD_LABELS = {
    "day": "День",
    "month": "Месяц",
    "half": "Полгода",
    "year": "Год",
}

# Finer-grained periods for the "Команда" report: 1/10/20/30 days, then
# every month up to a year.
CP_PERIOD_DAYS: dict[str, tuple[str, int]] = {
    "d1": ("1 день", 1),
    "d10": ("10 дней", 10),
    "d20": ("20 дней", 20),
    "d30": ("30 дней", 30),
    **{f"m{n}": (f"{n} мес.", 30 * n) for n in range(2, 13)},
}


def main_reply_kb() -> ReplyKeyboardMarkup:
    """Persistent bottom menu — always visible, works like an app's tab bar
    instead of buttons that scroll away in the chat history."""
    builder = ReplyKeyboardBuilder()
    for text in NAV_BUTTONS:
        builder.button(text=text)
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup(resize_keyboard=True)


def period_choice_kb(prefix: str = "period") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for period, label in PERIOD_LABELS.items():
        builder.button(text=label, callback_data=f"{prefix}:{period}")
    builder.adjust(4)
    return builder.as_markup()


def cp_period_choice_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, (label, _days) in CP_PERIOD_DAYS.items():
        builder.button(text=label, callback_data=f"cpperiod:{key}")
    builder.adjust(4, 4, 4, 3)
    return builder.as_markup()


def cancel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="cancel")
    return builder.as_markup()
