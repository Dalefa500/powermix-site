"""Who the "Команда" report tracks.

Keyed by the MoySklad search term, valued by the role label to show
instead. Shared by the Telegram bot and the web app so both stay in sync.
"""

TRACKED_COUNTERPARTIES: dict[str, str] = {
    "Дивиденды": "💼 Инвестор (вы)",
    "Сулаймоншоев Убайд": "👔 Убайд — директор",
}

# Ключевое сырьё, которое всегда на виду на «Балансе».
# Сопоставление по вхождению в название, без учёта регистра —
# чтобы не ломалось от лишнего пробела или уточнения в карточке товара.
KEY_MATERIALS: list[str] = [
    "Химикат ПВА",
    "Химикат Рутосел",
]
