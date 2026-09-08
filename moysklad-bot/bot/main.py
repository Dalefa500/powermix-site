from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import TelegramObject, Update

from .config import load_config
from .handlers import routers
from .moysklad import MoySkladClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AccessControlMiddleware(BaseMiddleware):
    """Blocks anyone who isn't a configured owner or employee."""

    def __init__(self, allowed_ids: set[int]) -> None:
        self._allowed_ids = allowed_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is not None and user.id not in self._allowed_ids:
            logger.warning("Blocked access from unknown user_id=%s", user.id)
            if isinstance(event, Update) and event.message:
                await event.message.answer(
                    "Доступ к этому боту ограничен. Обратись к владельцу цеха, "
                    "чтобы добавить твой Telegram ID в список сотрудников."
                )
            return None
        return await handler(event, data)


async def main() -> None:
    config = load_config()
    bot = Bot(token=config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    allowed_ids = set(config.owner_ids) | set(config.employee_ids)
    dp.update.outer_middleware(AccessControlMiddleware(allowed_ids))

    for router in routers:
        dp.include_router(router)

    moysklad = MoySkladClient(config.moysklad_token)

    logger.info(
        "Starting bot: %d owner(s), %d employee(s) allowed",
        len(config.owner_ids),
        len(config.employee_ids),
    )

    try:
        await dp.start_polling(bot, moysklad=moysklad, config=config)
    finally:
        await moysklad.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
