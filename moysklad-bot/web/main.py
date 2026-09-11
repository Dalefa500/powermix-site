"""JSON API + static hosting for the iPhone web app (PWA).

Same MoySklad data as the Telegram bot, shaped as JSON for a real UI
instead of chat messages. Runs as a second service off the same image.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel

from bot.moysklad import MoySkladClient, MoySkladError
from bot.people import TRACKED_COUNTERPARTIES

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
# Сколько килограммов считать «на исходе». Порог применяется к позициям,
# которые measured в кг; меняется в .env без правки кода.
LOW_STOCK_KG = float(os.environ.get("LOW_STOCK_KG", "1000"))
COOKIE_NAME = "pmx_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # stay logged in for a month
DAY_LEVEL_MAX_DAYS = 92  # longer than this and the UI switches to months

# A short PIN on a public URL is only safe with a hard cap on guessing.
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60

_failed_logins: dict[str, list[float]] = defaultdict(list)


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} не задан в .env — веб-приложение не запустится без него")
    return value


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.moysklad = MoySkladClient(_env("MOYSKLAD_TOKEN"))
    app.state.pin = _env("WEB_PIN")
    app.state.serializer = URLSafeTimedSerializer(_env("WEB_SECRET"), salt="pmx-session")
    app.state.tracked_hrefs: dict[str, str] = {}
    logger.info("Web app started")
    try:
        yield
    finally:
        await app.state.moysklad.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


# --- auth -----------------------------------------------------------------


class LoginRequest(BaseModel):
    pin: str


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _locked_out(ip: str) -> bool:
    cutoff = time.time() - LOGIN_LOCKOUT_SECONDS
    attempts = [t for t in _failed_logins[ip] if t > cutoff]
    _failed_logins[ip] = attempts
    return len(attempts) >= MAX_LOGIN_ATTEMPTS


def _has_valid_session(request: Request) -> bool:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return False
    try:
        request.app.state.serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return False
    return True


def require_session(request: Request) -> None:
    if not _has_valid_session(request):
        raise HTTPException(status_code=401, detail="Нужно войти")


authed = [Depends(require_session)]


@app.post("/api/login")
async def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    ip = _client_ip(request)
    if _locked_out(ip):
        raise HTTPException(
            status_code=429, detail="Слишком много попыток. Попробуйте через 15 минут."
        )

    if payload.pin != request.app.state.pin:
        _failed_logins[ip].append(time.time())
        raise HTTPException(status_code=401, detail="Неверный код")

    _failed_logins.pop(ip, None)
    response.set_cookie(
        COOKIE_NAME,
        request.app.state.serializer.dumps("ok"),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return {"ok": True}


@app.post("/api/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@app.get("/api/session")
async def session_state(request: Request) -> dict:
    return {"authenticated": _has_valid_session(request)}


# --- data -----------------------------------------------------------------

MONTHS_RU = [
    "янв", "фев", "мар", "апр", "май", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
]


def _period(days: int) -> tuple[datetime, datetime, str]:
    now = datetime.now()
    return now - timedelta(days=days), now, "day" if days <= DAY_LEVEL_MAX_DAYS else "month"


def _day_label(key: str) -> str:
    return f"{key[8:10]}.{key[5:7]}"


def _month_label(month_key: str) -> str:
    return f"{MONTHS_RU[int(month_key[5:7]) - 1]} {month_key[:4]}"


@app.get("/api/summary", dependencies=authed)
async def summary(request: Request) -> dict:
    moysklad: MoySkladClient = request.app.state.moysklad
    try:
        income, expense = await asyncio.gather(
            moysklad.sum_cash_today("cashin"), moysklad.sum_cash_today("cashout")
        )
    except MoySkladError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    accounts: list[dict] = []
    try:
        accounts = await moysklad.get_account_balances()
    except MoySkladError:
        logger.info("byaccount report unavailable, summing orders instead")

    if accounts:
        total = sum(a["balance"] for a in accounts)
        estimated = False
    else:
        estimated = True
        try:
            total = await moysklad.get_total_cash_balance_fallback()
        except MoySkladError as exc:
            raise HTTPException(status_code=502, detail=str(exc))

    return {
        "today": {"income": income, "expense": expense, "profit": income - expense},
        "accounts": accounts,
        "total_balance": total,
        "balance_is_estimate": estimated,
    }


@app.get("/api/report", dependencies=authed)
async def report(request: Request, days: int = Query(30, ge=1, le=400)) -> dict:
    moysklad: MoySkladClient = request.app.state.moysklad
    start, end, granularity = _period(days)

    try:
        daily = await moysklad.get_daily_cash_summary(start, end)
    except MoySkladError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if granularity == "day":
        rows = [
            {
                "label": _day_label(key),
                "income": daily[key]["income"],
                "expense": daily[key]["expense"],
            }
            for key in sorted(daily)
        ]
    else:
        monthly: dict[str, dict[str, float]] = defaultdict(
            lambda: {"income": 0.0, "expense": 0.0}
        )
        for key, value in daily.items():
            monthly[key[:7]]["income"] += value["income"]
            monthly[key[:7]]["expense"] += value["expense"]
        rows = [
            {
                "label": _month_label(f"{key}-01"),
                "income": monthly[key]["income"],
                "expense": monthly[key]["expense"],
            }
            for key in sorted(monthly)
        ]

    total_income = sum(r["income"] for r in rows)
    total_expense = sum(r["expense"] for r in rows)
    return {
        "granularity": granularity,
        "rows": rows,
        "totals": {
            "income": total_income,
            "expense": total_expense,
            "profit": total_income - total_expense,
        },
    }


@app.get("/api/stock", dependencies=authed)
async def stock(request: Request) -> dict:
    moysklad: MoySkladClient = request.app.state.moysklad
    try:
        rows = await moysklad.get_stock_report()
    except MoySkladError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    by_folder: dict[str, list[dict]] = defaultdict(list)
    low: list[dict] = []
    for item in rows:
        # МойСклад пишет единицу по-разному: «кг», «Килограмм» — сверяем начало.
        in_kg = item["uom"].strip().lower().startswith(("кг", "килогра"))
        entry = {
            "name": item["name"],
            "stock": item["stock"],
            "uom": item["uom"],
            "low": in_kg and item["stock"] < LOW_STOCK_KG,
        }
        by_folder[item["folder"]].append(entry)
        if entry["low"]:
            low.append(entry)

    return {
        "folders": [
            {
                "name": folder,
                "items": sorted(by_folder[folder], key=lambda i: i["name"]),
                "low": sum(1 for i in by_folder[folder] if i["low"]),
            }
            for folder in sorted(by_folder)
        ],
        # Самые критичные — впереди
        "low": sorted(low, key=lambda i: i["stock"]),
        "low_threshold": LOW_STOCK_KG,
    }


async def _tracked(request: Request) -> list[dict]:
    """Resolved tracked counterparties, cached so the drill-down endpoint
    can whitelist the hrefs it accepts from the client."""
    moysklad: MoySkladClient = request.app.state.moysklad
    resolved = await moysklad.resolve_tracked_agents(TRACKED_COUNTERPARTIES)
    request.app.state.tracked_hrefs = {entry["href"]: entry["name"] for entry in resolved}
    return resolved


@app.get("/api/team", dependencies=authed)
async def team(request: Request, days: int = Query(30, ge=1, le=400)) -> dict:
    moysklad: MoySkladClient = request.app.state.moysklad
    start, end, _granularity = _period(days)

    try:
        resolved = await _tracked(request)
        breakdowns = await asyncio.gather(
            *(
                moysklad.get_counterparty_expense_breakdown(entry["href"], start, end)
                for entry in resolved
            )
        )
    except MoySkladError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    people = sorted(
        (
            {"name": entry["name"], "href": entry["href"], "total": breakdown["total"]}
            for entry, breakdown in zip(resolved, breakdowns)
        ),
        key=lambda p: -p["total"],
    )
    return {"people": people, "total": sum(p["total"] for p in people)}


@app.get("/api/team/detail", dependencies=authed)
async def team_detail(request: Request, href: str, days: int = Query(30, ge=1, le=400)) -> dict:
    moysklad: MoySkladClient = request.app.state.moysklad

    known: dict[str, str] = request.app.state.tracked_hrefs
    if href not in known:
        known = {entry["href"]: entry["name"] for entry in await _tracked(request)}
    if href not in known:
        raise HTTPException(status_code=404, detail="Этот человек не отслеживается")

    start, end, granularity = _period(days)
    today_start = end.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        period_data, today_data = await asyncio.gather(
            moysklad.get_counterparty_expense_breakdown(href, start, end),
            moysklad.get_counterparty_expense_breakdown(href, today_start, end),
        )
    except MoySkladError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    daily = period_data["daily"]
    if granularity == "day":
        rows = [{"label": _day_label(key), "amount": daily[key]} for key in sorted(daily)]
    else:
        monthly: dict[str, float] = defaultdict(float)
        for key, amount in daily.items():
            monthly[key[:7]] += amount
        rows = [
            {"label": _month_label(f"{key}-01"), "amount": monthly[key]}
            for key in sorted(monthly)
        ]

    return {
        "name": known[href],
        "today": today_data["total"],
        "total": period_data["total"],
        "granularity": granularity,
        "rows": rows,
    }


# --- static ---------------------------------------------------------------
# Mounted last so every /api route above wins; serving from the root keeps
# the service worker's scope over the whole app.


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")
