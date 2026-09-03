"""Webhook и return-страницы Platega."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse

from bot_notify import notify_payment_success
from config import config
from database import get_payment_order, get_payment_order_by_bill
from payments import process_payment
from platega import verify_callback_headers

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/platega", tags=["platega"])

_SUCCESS_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Оплата прошла</title>
  <style>
    body {{ font-family: system-ui, sans-serif; background:#0f1117; color:#e8eaed;
           display:flex; min-height:100vh; align-items:center; justify-content:center; margin:0; }}
    .box {{ background:#1a1d26; border-radius:16px; padding:32px; max-width:420px; text-align:center; }}
    h1 {{ font-size:22px; margin:0 0 12px; }}
    p {{ color:#9aa0a6; line-height:1.5; }}
  </style>
</head>
<body>
  <div class="box">
    <h1>Оплата успешна</h1>
    <p>Вернитесь в Telegram-бот {bot_name} и нажмите «Мой доступ» или «Я оплатил · проверить».</p>
  </div>
</body>
</html>
"""

_FAIL_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Оплата не прошла</title>
  <style>
    body {{ font-family: system-ui, sans-serif; background:#0f1117; color:#e8eaed;
           display:flex; min-height:100vh; align-items:center; justify-content:center; margin:0; }}
    .box {{ background:#1a1d26; border-radius:16px; padding:32px; max-width:420px; text-align:center; }}
    h1 {{ font-size:22px; margin:0 0 12px; }}
    p {{ color:#9aa0a6; line-height:1.5; }}
  </style>
</head>
<body>
  <div class="box">
    <h1>Оплата не выполнена</h1>
    <p>Вернитесь в бот {bot_name} и попробуйте снова в разделе «Тарифы».</p>
  </div>
</body>
</html>
"""


@router.get("/success", response_class=HTMLResponse)
@router.post("/success", response_class=HTMLResponse)
async def payment_success_page() -> HTMLResponse:
    return HTMLResponse(_SUCCESS_HTML.format(bot_name=config.BOT_NAME))


@router.get("/fail", response_class=HTMLResponse)
@router.post("/fail", response_class=HTMLResponse)
async def payment_fail_page() -> HTMLResponse:
    return HTMLResponse(_FAIL_HTML.format(bot_name=config.BOT_NAME))


@router.post("/webhook")
async def payment_webhook(request: Request) -> Response:
    if not config.use_platega:
        return Response(content="disabled", status_code=503)

    merchant = request.headers.get("X-MerchantId") or request.headers.get("x-merchantid")
    secret = request.headers.get("X-Secret") or request.headers.get("x-secret")
    if not verify_callback_headers(merchant, secret):
        logger.warning("Platega webhook: bad auth headers")
        return Response(content="unauthorized", status_code=401)

    try:
        body = await request.json()
    except Exception:
        logger.warning("Platega webhook: invalid JSON")
        return Response(content="bad request", status_code=400)

    status = str(body.get("status") or "").upper()
    tx_id = str(body.get("id") or body.get("transactionId") or "").strip()
    payload = str(body.get("payload") or "").strip()

    logger.info("Platega webhook status=%s id=%s payload=%s", status, tx_id, payload)

    if status != "CONFIRMED":
        return Response(content="ok", status_code=200)

    order = None
    if payload:
        order = await get_payment_order(payload)
    if not order and tx_id:
        order = await get_payment_order_by_bill(tx_id)
    if not order:
        logger.error("Platega webhook: order not found tx=%s payload=%s", tx_id, payload)
        return Response(content="ok", status_code=200)

    user, plan, activated = await process_payment(
        order_id=order.order_id,
        telegram_id=order.telegram_id,
        plan_id=order.plan_id,
    )
    if activated and user and plan:
        try:
            await notify_payment_success(user.telegram_id, plan.title, user)
        except Exception as exc:
            logger.warning("Platega notify failed (ok if Amvera has no TG egress): %s", exc)

    return Response(content="ok", status_code=200)
