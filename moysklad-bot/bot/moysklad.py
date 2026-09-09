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
            # Some hosts hand containers a dual-stack DNS answer but no
            # working outbound IPv6 route, which stalls every request while
            # it tries (and fails) the IPv6 candidate first. Binding to the
            # IPv4 wildcard address forces IPv4-only connections.
            transport=httpx.AsyncHTTPTransport(local_address="0.0.0.0"),
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

    async def create_cash_in(self, sum_rub: float, comment: str, employee: str) -> dict:
        organization_href = await self.get_default_organization_href()
        agent_href = await self.get_default_agent_href()
        payload = {
            "organization": self._meta(organization_href, "organization"),
            "agent": self._meta(agent_href, "counterparty"),
            "sum": round(sum_rub * 100),
            "description": f"{comment}\n\nВнёс: {employee}",
        }
        return await self._request("POST", "/entity/cashin", json=payload)

    async def create_cash_out(self, sum_rub: float, comment: str, employee: str) -> dict:
        organization_href = await self.get_default_organization_href()
        agent_href = await self.get_default_agent_href()
        payload = {
            "organization": self._meta(organization_href, "organization"),
            "agent": self._meta(agent_href, "counterparty"),
            "sum": round(sum_rub * 100),
            "description": f"{comment}\n\nВнёс: {employee}",
        }
        return await self._request("POST", "/entity/cashout", json=payload)

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

    async def get_stock_report(self, limit: int = 100) -> list[dict]:
        """Current stock quantity per product/material (/report/stock/all),
        grouped by product folder (МойСклад's category/group) so raw
        materials and finished goods can be told apart — assuming the
        account keeps them in separate folders. If a row has no folder,
        it's labelled "Без категории".
        """
        data = await self._request("GET", "/report/stock/all", params={"limit": limit})
        rows = data.get("rows") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise MoySkladError("Неожиданный формат ответа /report/stock/all")
        result = []
        for row in rows:
            folder = row.get("folder") or {}
            result.append(
                {
                    "name": row.get("name", "?"),
                    "stock": row.get("stock", 0),
                    "reserve": row.get("reserve", 0),
                    "folder": folder.get("name") or "Без категории",
                }
            )
        return result

    async def get_counterparty_debts(self, limit: int = 30) -> list[dict]:
        """Outstanding balance per counterparty (/report/counterparty).

        Positive balance = the counterparty owes us; negative = we owe them.
        This endpoint is less commonly used than /report/money and /report/stock
        — treat the first live call as a test and adjust if the account
        returns an unexpected shape.
        """
        data = await self._request("GET", "/report/counterparty", params={"limit": limit})
        rows = data.get("rows") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise MoySkladError("Неожиданный формат ответа /report/counterparty")

        debts = []
        for row in rows:
            balance = row.get("balance", 0) / 100
            if abs(balance) < 0.01:
                continue
            debts.append({"name": row.get("name", "?"), "balance": balance})
        return debts

    async def get_cash_rows(
        self,
        entity: str,
        start: datetime,
        end: datetime,
        *,
        expand_agent: bool = False,
        agent_href: str | None = None,
    ) -> list[dict]:
        """Raw cashin/cashout documents (moment, sum, description, and —
        with expand_agent — the full counterparty object) between start and
        end (inclusive), paginated. Pass agent_href to filter server-side to
        one specific counterparty.
        """
        rows_all: list[dict] = []
        offset = 0
        limit = 1000
        filter_parts = [
            f"moment>={start.strftime('%Y-%m-%d')} 00:00:00",
            f"moment<={end.strftime('%Y-%m-%d')} 23:59:59",
        ]
        if agent_href:
            filter_parts.append(f"agent={agent_href}")
        while True:
            params: dict[str, Any] = {
                "filter": ";".join(filter_parts),
                "limit": limit,
                "offset": offset,
            }
            if expand_agent:
                params["expand"] = "agent"
            data = await self._request("GET", f"/entity/{entity}", params=params)
            rows = data.get("rows", [])
            rows_all.extend(rows)
            if len(rows) < limit:
                break
            offset += limit
        return rows_all

    async def get_daily_cash_summary(
        self, start: datetime, end: datetime
    ) -> dict[str, dict[str, float]]:
        """Per-day income/expense totals for cashin/cashout between start and
        end (inclusive), keyed by 'YYYY-MM-DD'.
        """
        daily: dict[str, dict[str, float]] = {}
        for entity, key in (("cashin", "income"), ("cashout", "expense")):
            for row in await self.get_cash_rows(entity, start, end):
                day = (row.get("moment") or "")[:10]
                if not day:
                    continue
                daily.setdefault(day, {"income": 0.0, "expense": 0.0})
                daily[day][key] += row.get("sum", 0) / 100
        return daily

    async def resolve_tracked_agents(self, names: dict[str, str]) -> list[dict]:
        """Resolve a fixed list of counterparties, keyed by the search term
        used to find them in MoySklad with the display label to show
        instead (e.g. {"Дивиденды": "💼 Инвестор (вы)"}).
        """
        resolved: list[dict] = []
        seen_hrefs: set[str] = set()
        for search_name, display_label in names.items():
            candidates = await self.search_counterparty(search_name, limit=5)
            for candidate in candidates:
                href = candidate["meta"]["href"]
                if href in seen_hrefs:
                    continue
                seen_hrefs.add(href)
                # If the search term is broad enough to match more than one
                # real counterparty, keep the actual МойСклад name visible
                # too so they don't get silently conflated under one label.
                label = display_label
                if len(candidates) > 1:
                    label = f"{display_label} ({candidate.get('name', search_name)})"
                resolved.append({"name": label, "href": href})
        return resolved

    async def get_named_counterparty_expenses(
        self, names: dict[str, str], start: datetime, end: datetime
    ) -> list[dict]:
        """Expense totals for a fixed, known list of counterparties.
        Resolved once via search then queried directly with a server-side
        agent filter — far cheaper than scanning every cashout row in the
        period when you only care about a handful of people.
        """
        results: list[dict] = []
        for entry in await self.resolve_tracked_agents(names):
            breakdown = await self.get_counterparty_expense_breakdown(entry["href"], start, end)
            results.append({**entry, "total": breakdown["total"]})
        return sorted(results, key=lambda e: -e["total"])

    async def get_counterparty_expense_breakdown(
        self, agent_href: str, start: datetime, end: datetime
    ) -> dict:
        """Total + per-day expense for one specific counterparty (by href)."""
        daily: dict[str, float] = {}
        total = 0.0
        for row in await self.get_cash_rows("cashout", start, end, agent_href=agent_href):
            amount = row.get("sum", 0) / 100
            total += amount
            day = (row.get("moment") or "")[:10]
            if day:
                daily[day] = daily.get(day, 0.0) + amount
        return {"total": total, "daily": daily}
