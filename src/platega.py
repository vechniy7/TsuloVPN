"""Клиент Platega: создание платежа и проверка статуса."""

from __future__ import annotations

import logging
import uuid

import aiohttp

from config import config

logger = logging.getLogger(__name__)

PLATEGA_API_BASE = "https://app.platega.io"


class PlategaError(Exception):
    pass


def _headers() -> dict[str, str]:
    return {
        "X-MerchantId": config.PLATEGA_MERCHANT_ID,
        "X-Secret": config.PLATEGA_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def verify_callback_headers(merchant_id: str | None, secret: str | None) -> bool:
    if not config.use_platega:
        return False
    return (
        (merchant_id or "").strip() == config.PLATEGA_MERCHANT_ID
        and (secret or "").strip() == config.PLATEGA_API_KEY
    )


def new_order_id(telegram_id: int, plan_id: str) -> str:
    return f"{telegram_id}-{plan_id}-{uuid.uuid4().hex[:10]}"


async def create_transaction(
    *,
    amount: int,
    order_id: str,
    description: str,
    telegram_id: int,
    username: str | None = None,
) -> dict:
    if not config.use_platega:
        raise PlategaError("Platega is not configured")

    base = config.SUBSCRIPTION_PUBLIC_URL.rstrip("/")
    uname = (username or "").strip()
    if uname and not uname.startswith("@"):
        uname = f"@{uname}"
    if not uname:
        uname = f"tg:{telegram_id}"

    payload = {
        "paymentDetails": {
            "amount": float(amount),
            "currency": "RUB",
        },
        "description": description,
        "return": f"{base}/platega/success",
        "failedUrl": f"{base}/platega/fail",
        "payload": order_id,
        "orderId": order_id,
        "metadata": {
            "userId": str(telegram_id),
            "userName": uname,
        },
    }

    # Опционально зафиксировать метод (2=СБП QR, 11=карты). Пусто = выбор на пейформе (v2).
    method = (getattr(config, "PLATEGA_PAYMENT_METHOD", "") or "").strip()
    if method.isdigit():
        payload["paymentMethod"] = int(method)
        endpoint = f"{PLATEGA_API_BASE}/transaction/process"
    else:
        endpoint = f"{PLATEGA_API_BASE}/v2/transaction/process"

    timeout = aiohttp.ClientTimeout(total=config.FETCH_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            endpoint,
            json=payload,
            headers=_headers(),
        ) as response:
            body = await response.json(content_type=None)
            if response.status != 200:
                logger.error("Platega create HTTP %s: %s", response.status, body)
                raise PlategaError(f"Platega HTTP {response.status}")

    transaction_id = body.get("transactionId") or body.get("id")
    pay_url = body.get("url") or body.get("redirect")
    if not transaction_id or not pay_url:
        logger.error("Platega create missing fields: %s", body)
        raise PlategaError("Platega response missing payment link")

    return {
        "transaction_id": str(transaction_id),
        "pay_url": str(pay_url),
        "status": str(body.get("status") or "PENDING"),
        "expires_in": body.get("expiresIn"),
    }


async def get_transaction_status(transaction_id: str) -> str | None:
    if not config.use_platega or not transaction_id:
        return None

    timeout = aiohttp.ClientTimeout(total=config.FETCH_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(
            f"{PLATEGA_API_BASE}/transaction/{transaction_id}",
            headers=_headers(),
        ) as response:
            if response.status != 200:
                logger.warning(
                    "Platega status HTTP %s for %s", response.status, transaction_id
                )
                return None
            body = await response.json(content_type=None)

    status = body.get("status")
    return str(status).upper() if status else None
