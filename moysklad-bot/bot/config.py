from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    bot_token: str
    moysklad_token: str
    owner_ids: list[int]
    director_ids: list[int]
    employee_ids: list[int]
    daily_report_time: str

    @property
    def management_ids(self) -> set[int]:
        """Owners and directors — the only ones who see income figures."""
        return set(self.owner_ids) | set(self.director_ids)

    @property
    def allowed_ids(self) -> set[int]:
        """Everyone allowed to talk to the bot at all."""
        return self.management_ids | set(self.employee_ids)


def _parse_ids(raw: str) -> list[int]:
    return [int(chunk.strip()) for chunk in raw.split(",") if chunk.strip()]


def load_config() -> Config:
    bot_token = os.environ["BOT_TOKEN"]
    moysklad_token = os.environ["MOYSKLAD_TOKEN"]
    owner_ids = _parse_ids(os.environ.get("OWNER_IDS", ""))
    director_ids = _parse_ids(os.environ.get("DIRECTOR_IDS", ""))
    employee_ids = _parse_ids(os.environ.get("EMPLOYEE_IDS", ""))
    daily_report_time = os.environ.get("DAILY_REPORT_TIME", "20:00")

    if not owner_ids:
        raise RuntimeError("OWNER_IDS не задан — некому будет видеть отчёты через /today")

    return Config(
        bot_token=bot_token,
        moysklad_token=moysklad_token,
        owner_ids=owner_ids,
        director_ids=director_ids,
        employee_ids=employee_ids,
        daily_report_time=daily_report_time,
    )
