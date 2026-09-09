"""Who the "Команда" report tracks.

Keyed by the MoySklad search term, valued by the role label to show
instead. Shared by the Telegram bot and the web app so both stay in sync.
"""

TRACKED_COUNTERPARTIES: dict[str, str] = {
    "Дивиденды": "💼 Инвестор (вы)",
    "Сулаймоншоев Убайд": "👔 Убайд — директор",
}
