from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.moysklad.ru/api/remap/1.2"


class MoySkladError(RuntimeError):
    """Raised when the MoySklad API returns an error response."""


class MoySkladClient:
    """Thin async wrapper around the MoySklad JSON API (REMAP 1.2).

    Only the handful of endpoints this bot needs are covered. Field names
    follow the documented REMAP 1.2 schema (https://dev.moysklad.ru/doc/api/remap/1.2/);
    verify against a live account on first run since some accounts customize
    required fields (mandatory custom attributes, cost items, etc.).
    """

    def __init__(self, token: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept-Encoding": "gzip",
                "Content-Type": "application/json",
            },
            timeout=20.0,
        )
        self._organization_href: str | None = None
        self._store_href: str | None = None
        self._default_agent_href: str | None = None

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        response = await self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            logger.error("MoySklad API error %s %s: %s", method, path, response.text)
            raise MoySkladError(f"{response.status_code}: {response.text[:500]}")
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    @staticmethod
    def _meta(href: str, type_: str) -> dict:
        return {"meta": {"href": href, "type": type_, "mediaType": "application/json"}}

    async def get_default_organization_href(self) -> str:
        if self._organization_href is None:
            data = await self._request("GET", "/entity/organization", params={"limit": 1})
            rows = data.get("rows", [])
            if not rows:
                raise MoySkladError("В аккаунте МойСклад не найдено ни одной организации")
            self._organization_href = rows[0]["meta"]["href"]
        return self._organization_href

    async def get_default_store_href(self) -> str:
        if self._store_href is None:
            data = await self._request("GET", "/entity/store", params={"limit": 1})
            rows = data.get("rows", [])
            if not rows:
                raise MoySkladError("В аккаунте МойСклад не найден ни один склад")
            self._store_href = rows[0]["meta"]["href"]
        return self._store_href

    async def get_default_agent_href(self) -> str:
        """MoySklad requires an 'agent' (counterparty) on cash orders even
        for internal cash flow not tied to a real client/supplier. Reuse (or
        create once) a generic counterparty for that.
        """
        if self._default_agent_href is None:
            name = "Без контрагента"
            results = await self.search_counterparty(name, limit=1)
            matching = [r for r in results if r.get("name") == name]
            if matching:
                self._default_agent_href = matching[0]["meta"]["href"]
            else:
                created = await self.create_counterparty(name)
                self._default_agent_href = created["meta"]["href"]
        return self._default_agent_href

    async def search_counterparty(self, name: str, limit: int = 5) -> list[dict]:
        data = await self._request(
            "GET", "/entity/counterparty", params={"search": name, "limit": limit}
        )
        return data.get("rows", [])

    async def create_counterparty(self, name: str) -> dict:
        return await self._request("POST", "/entity/counterparty", json={"name": name})

    async def search_products(self, name: str, limit: int = 8) -> list[dict]:
        data = await self._request(
            "GET", "/entity/product", params={"search": name, "limit": limit}
        )
        return data.get("rows", [])

    async def create_cash_in(self, sum_rub: float, comment: str, employee: str) -> dict:
        organization_href = await self.get_default_organization_href()
        agent_href = await self.get_default_agent_href()
        payload = {
            "organization": self._meta(organization_href, "organization"),
            "agent": self._meta(agent_href, "counterparty"),
            "sum": round(sum_rub * 100),
            "description": f"{comment}\n\nВнёс: {employee} (через Telegram-бота)",
        }
        return await self._request("POST", "/entity/cashin", json=payload)

    async def create_cash_out(self, sum_rub: float, comment: str, employee: str) -> dict:
        organization_href = await self.get_default_organization_href()
        agent_href = await self.get_default_agent_href()
        payload = {
            "organization": self._meta(organization_href, "organization"),
            "agent": self._meta(agent_href, "counterparty"),
            "sum": round(sum_rub * 100),
            "description": f"{comment}\n\nВнёс: {employee} (через Telegram-бота)",
        }
        return await self._request("POST", "/entity/cashout", json=payload)

    async def create_demand(
        self,
        counterparty_href: str,
        positions: list[dict],
        employee: str,
        comment: str = "",
    ) -> dict:
        organization_href = await self.get_default_organization_href()
        store_href = await self.get_default_store_href()
        description = f"{comment}\n\nОформил: {employee} (через Telegram-бота)".strip()
        payload = {
            "organization": self._meta(organization_href, "organization"),
            "store": self._meta(store_href, "store"),
            "agent": self._meta(counterparty_href, "counterparty"),
            "description": description,
            "positions": positions,
        }
        return await self._request("POST", "/entity/demand", json=payload)

    async def sum_cash_today(self, entity: str) -> float:
        today = datetime.now().strftime("%Y-%m-%d")
        data = await self._request(
            "GET",
            f"/entity/{entity}",
            params={
                "filter": f"moment>={today} 00:00:00;moment<={today} 23:59:59",
                "limit": 100,
            },
        )
        return sum(row.get("sum", 0) for row in data.get("rows", [])) / 100

    async def get_account_balances(self) -> list[dict]:
        """Current balance per cash register / bank account via MoySklad's
        own money report (/report/money/byaccount). Not available on every
        tariff/account — raises MoySkladError if the endpoint doesn't return
        the expected shape, so callers should fall back to
        get_total_cash_balance_fallback().
        """
        data = await self._request("GET", "/report/money/byaccount")
        rows = data.get("rows") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise MoySkladError("Неожиданный формат ответа /report/money/byaccount")

        balances = []
        for row in rows:
            account = row.get("account") or {}
            balances.append(
                {
                    "name": account.get("name", "Касса"),
                    "balance": row.get("balance", 0) / 100,
                }
            )
        return balances

    async def get_total_cash_balance_fallback(self) -> float:
        """Sums every cashin/cashout document ever recorded in the account
        (paginated). Used when the money-by-account report isn't available.
        Slow on accounts with very long history — fine for an on-demand or
        once-a-day call.
        """
        total = 0.0
        limit = 1000
        for entity, sign in (("cashin", 1), ("cashout", -1)):
            offset = 0
            while True:
                data = await self._request(
                    "GET", f"/entity/{entity}", params={"limit": limit, "offset": offset}
                )
                rows = data.get("rows", [])
                total += sign * sum(row.get("sum", 0) for row in rows) / 100
                if len(rows) < limit:
                    break
                offset += limit
        return total
