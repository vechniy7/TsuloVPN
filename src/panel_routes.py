"""Админ-панель TsuloVPN (/panel) — кабинет в стиле Marzban."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from config import config
from database import (
    get_all_orders,
    get_all_users,
    get_user,
    get_user_count,
    regenerate_user_token,
    save_user,
)
from payments import PLANS, extend_subscription, get_plan, is_subscription_active
from pool_engine_v3 import get_pool_state, refresh_pool

logger = logging.getLogger(__name__)
router = APIRouter(tags=["panel"])

PANEL_DIR = Path(__file__).resolve().parent / "panel" / "static"
COOKIE = "tsulo_panel"


class LoginBody(BaseModel):
    token: str = ""


class ExtendBody(BaseModel):
    days: int = Field(default=30, ge=1, le=3650)
    plan_id: str | None = None


class ExpireBody(BaseModel):
    expires_at: str | None = None
    days_from_now: int | None = Field(default=None, ge=0, le=3650)


class DisableBody(BaseModel):
    disabled: bool = True


class NoteBody(BaseModel):
    note: str = ""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _fmt(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def _user_status(user) -> str:
    if user.disabled:
        return "disabled"
    if user.is_admin:
        return "admin"
    if not config.payments_active:
        return "active"
    if is_subscription_active(user):
        return "active"
    return "expired"


def _user_payload(user) -> dict[str, Any]:
    sub_url = config.subscription_url_for_token(user.subscription_token)
    expires = _parse_iso(user.expires_at)
    return {
        "telegram_id": user.telegram_id,
        "full_name": user.full_name,
        "username": user.username,
        "username_link": f"https://t.me/{user.username}" if user.username else None,
        "subscription_token": user.subscription_token,
        "subscription_url": sub_url,
        "registration_date": user.registration_date,
        "expires_at": user.expires_at,
        "plan": user.plan,
        "plan_title": (get_plan(user.plan).title if user.plan and get_plan(user.plan) else None),
        "is_admin": user.is_admin,
        "disabled": bool(user.disabled),
        "status": _user_status(user),
        "last_seen_at": user.last_seen_at,
        "sub_fetch_count": int(user.sub_fetch_count or 0),
        "note": user.note or "",
        "data_limit": "∞",
        "used_traffic": "—",
        "online": bool(
            user.last_seen_at
            and (_utcnow() - (_parse_iso(user.last_seen_at) or _utcnow())).total_seconds() < 86400
        ),
        "days_left": (
            max(0, (expires - _utcnow()).days)
            if expires and expires > _utcnow()
            else (None if not config.payments_active and not user.expires_at else 0)
        ),
    }


def _require_panel_configured() -> None:
    if not config.panel_enabled:
        raise HTTPException(
            status_code=503,
            detail="Задайте ADMIN_PANEL_TOKEN в переменных Amvera",
        )


def _extract_token(request: Request, authorization: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    cookie = request.cookies.get(COOKIE) or ""
    return cookie.strip()


def require_admin(
    request: Request,
    authorization: str | None = Header(default=None),
) -> str:
    _require_panel_configured()
    token = _extract_token(request, authorization)
    if not token or not secrets.compare_digest(token, config.ADMIN_PANEL_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return token


@router.get("/panel")
@router.get("/panel/")
async def panel_index():
    path = PANEL_DIR / "index.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="panel missing")
    return FileResponse(path, media_type="text/html; charset=utf-8")


@router.get("/panel/static/{filename}")
async def panel_static(filename: str):
    safe = Path(filename).name
    path = PANEL_DIR / safe
    if not path.is_file():
        raise HTTPException(status_code=404)
    media = "text/css" if safe.endswith(".css") else "application/javascript"
    if safe.endswith(".html"):
        media = "text/html; charset=utf-8"
    return FileResponse(path, media_type=media)


@router.get("/panel/api/status")
async def panel_status():
    return {
        "ok": True,
        "enabled": config.panel_enabled,
        "bot_name": config.BOT_NAME,
        "payments_active": config.payments_active,
        "public_url": config.SUBSCRIPTION_PUBLIC_URL,
    }


@router.post("/panel/api/login")
async def panel_login(body: LoginBody):
    _require_panel_configured()
    token = (body.token or "").strip()
    if not token or not secrets.compare_digest(token, config.ADMIN_PANEL_TOKEN):
        raise HTTPException(status_code=401, detail="Неверный токен")
    response = JSONResponse({"ok": True, "bot_name": config.BOT_NAME})
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
        path="/",
    )
    return response


@router.post("/panel/api/logout")
async def panel_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE, path="/")
    return response


@router.get("/panel/api/dashboard")
async def panel_dashboard(_: str = Depends(require_admin)):
    # Один проход по кэшу пользователей + pool в памяти (без N+1 в Upstash).
    users = await get_all_users(use_cache=True)
    pool = get_pool_state()
    try:
        orders = await get_all_orders(limit=200)
    except Exception as exc:
        logger.warning("panel orders load failed: %s", exc)
        orders = []

    active = 0
    expired = 0
    disabled = 0
    online_24h = 0
    for user in users:
        st = _user_status(user)
        if st == "disabled":
            disabled += 1
        elif st in ("active", "admin"):
            active += 1
        else:
            expired += 1
        if user.last_seen_at:
            seen = _parse_iso(user.last_seen_at)
            if seen and (_utcnow() - seen).total_seconds() < 86400:
                online_24h += 1

    paid = [o for o in orders if o.status == "paid"]
    revenue = sum(o.amount for o in paid)

    logger.info(
        "panel dashboard users=%s active=%s configs=%s",
        len(users),
        active,
        pool.subscription_count,
    )

    return {
        "bot_name": config.BOT_NAME,
        "public_url": config.SUBSCRIPTION_PUBLIC_URL,
        "payments_active": config.payments_active,
        "platega": config.use_platega,
        "users_total": len(users),
        "users_active": active,
        "users_expired": expired,
        "users_disabled": disabled,
        "online_24h": online_24h,
        "orders_total": len(orders),
        "orders_paid": len(paid),
        "revenue_rub": revenue,
        "plans": [
            {"id": p.id, "title": p.title, "months": p.months, "price_rub": p.price_rub}
            for p in PLANS.values()
        ],
        "pool": {
            "status": pool.source_status,
            "configs": pool.subscription_count,
            "source_real": pool.source_real_count,
            "wifi": pool.wifi_count,
            "lte": pool.lte_count,
            "last_refresh_at": pool.last_refresh_at,
            "last_error": pool.last_error,
            "is_refreshing": pool.is_refreshing,
            "sources": pool.source_counts,
        },
    }


@router.get("/panel/api/users")
async def panel_users(
    q: str = "",
    status: str = "",
    page: int = 1,
    limit: int = 50,
    _: str = Depends(require_admin),
):
    page = max(1, page)
    limit = min(200, max(10, limit))
    query = (q or "").strip().lower()
    status_f = (status or "").strip().lower()

    users = await get_all_users(use_cache=True)
    rows = [_user_payload(u) for u in users]
    if query:
        rows = [
            r
            for r in rows
            if query in str(r["telegram_id"])
            or query in (r.get("username") or "").lower()
            or query in (r.get("full_name") or "").lower()
            or query in (r.get("subscription_token") or "").lower()
            or query in (r.get("note") or "").lower()
        ]
    if status_f:
        rows = [r for r in rows if r["status"] == status_f]

    total = len(rows)
    start = (page - 1) * limit
    chunk = rows[start : start + limit]
    return {
        "total": total,
        "page": page,
        "pages": max(1, (total + limit - 1) // limit),
        "items": chunk,
    }


@router.get("/panel/api/users/{telegram_id}")
async def panel_user_detail(telegram_id: int, _: str = Depends(require_admin)):
    user = await get_user(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _user_payload(user)


@router.post("/panel/api/users/{telegram_id}/extend")
async def panel_user_extend(
    telegram_id: int,
    body: ExtendBody,
    _: str = Depends(require_admin),
):
    user = await get_user(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    plan_id = body.plan_id or user.plan or next(iter(PLANS), "1m")
    if body.days == 30 and get_plan(plan_id):
        user = await extend_subscription(user, plan_id)
    else:
        now = _utcnow()
        base = now
        current = _parse_iso(user.expires_at)
        if current and current > now:
            base = current
        user.expires_at = (base + timedelta(days=body.days)).isoformat()
        if plan_id:
            user.plan = plan_id
        user.disabled = False
        user = await save_user(user)
    return _user_payload(user)


@router.post("/panel/api/users/{telegram_id}/expire")
async def panel_user_expire(
    telegram_id: int,
    body: ExpireBody,
    _: str = Depends(require_admin),
):
    user = await get_user(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if body.days_from_now is not None:
        user.expires_at = (_utcnow() + timedelta(days=body.days_from_now)).isoformat()
    elif body.expires_at:
        parsed = _parse_iso(body.expires_at)
        if not parsed:
            raise HTTPException(status_code=400, detail="Bad expires_at")
        user.expires_at = parsed.isoformat()
    else:
        user.expires_at = (_utcnow() - timedelta(minutes=1)).isoformat()
    user = await save_user(user)
    return _user_payload(user)


@router.post("/panel/api/users/{telegram_id}/disable")
async def panel_user_disable(
    telegram_id: int,
    body: DisableBody,
    _: str = Depends(require_admin),
):
    user = await get_user(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.disabled = bool(body.disabled)
    user = await save_user(user)
    return _user_payload(user)


@router.post("/panel/api/users/{telegram_id}/regen")
async def panel_user_regen(telegram_id: int, _: str = Depends(require_admin)):
    user = await regenerate_user_token(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _user_payload(user)


@router.post("/panel/api/users/{telegram_id}/note")
async def panel_user_note(
    telegram_id: int,
    body: NoteBody,
    _: str = Depends(require_admin),
):
    user = await get_user(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.note = (body.note or "").strip()[:500] or None
    user = await save_user(user)
    return _user_payload(user)


@router.get("/panel/api/orders")
async def panel_orders(limit: int = 100, _: str = Depends(require_admin)):
    orders = await get_all_orders(limit=min(500, max(20, limit)))
    return {
        "items": [
            {
                "order_id": o.order_id,
                "telegram_id": o.telegram_id,
                "plan_id": o.plan_id,
                "amount": o.amount,
                "bill_id": o.bill_id,
                "status": o.status,
                "created_at": o.created_at,
            }
            for o in orders
        ]
    }


@router.get("/panel/api/pool")
async def panel_pool(_: str = Depends(require_admin)):
    pool = get_pool_state()
    return {
        "status": pool.source_status,
        "configs": pool.subscription_count,
        "source_real": pool.source_real_count,
        "wifi": pool.wifi_count,
        "lte": pool.lte_count,
        "wifi_sources": pool.wifi_source_counts,
        "lte_sources": pool.lte_source_counts,
        "sources": pool.source_counts,
        "last_refresh_at": pool.last_refresh_at,
        "last_refresh_duration": pool.last_refresh_duration,
        "last_error": pool.last_error,
        "is_refreshing": pool.is_refreshing,
        "last_fetch_status": pool.last_fetch_status,
        "consecutive_fetch_failures": pool.consecutive_fetch_failures,
        "limit": config.SUBSCRIPTION_CONFIG_LIMIT,
    }


@router.post("/panel/api/pool/refresh")
async def panel_pool_refresh(_: str = Depends(require_admin)):
    pool = await refresh_pool(force=True)
    return {
        "ok": True,
        "status": pool.source_status,
        "configs": pool.subscription_count,
        "last_error": pool.last_error,
    }


@router.get("/panel/api/stats/users-count")
async def panel_users_count(_: str = Depends(require_admin)):
    return {"count": await get_user_count()}
