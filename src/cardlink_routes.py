import json
import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse

from bot_notify import notify_payment_success
from cardlink import verify_signature
from config import config
from database import get_payment_order, get_user, mark_payment_order_paid
from payments import extend_subscription, get_plan, process_cardlink_payment

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cardlink", tags=["cardlink"])

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
    <p>Вернитесь в Telegram-бот {bot_name} — доступ будет активирован автоматически.</p>
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
    <p>Попробуйте снова в боте {bot_name} или выберите другой способ оплаты.</p>
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
    if not config.use_cardlink:
        return Response(content="disabled", status_code=503)

    form = await request.form()
    inv_id = str(form.get("InvId", ""))
    out_sum = str(form.get("OutSum", ""))
    status = str(form.get("Status", ""))
    signature = str(form.get("SignatureValue", ""))
    custom = str(form.get("custom", ""))

    if not inv_id or not out_sum or not signature:
        logger.warning("Cardlink webhook: missing fields")
        return Response(content="bad request", status_code=400)

    if not verify_signature(out_sum, inv_id, signature):
        logger.warning("Cardlink webhook: invalid signature for order %s", inv_id)
        return Response(content="invalid signature", status_code=403)

    if status != "SUCCESS":
        logger.info("Cardlink webhook: order %s status %s", inv_id, status)
        return Response(content="OK")

    plan_id = None
    telegram_id = None
    if custom:
        try:
            payload = json.loads(custom)
            plan_id = payload.get("plan_id")
            telegram_id = payload.get("telegram_id")
        except json.JSONDecodeError:
            pass

    order = await get_payment_order(inv_id)
    if order:
        plan_id = plan_id or order.plan_id
        telegram_id = telegram_id or order.telegram_id

    if not plan_id or not telegram_id:
        logger.error("Cardlink webhook: cannot resolve order %s", inv_id)
        return Response(content="order not found", status_code=404)

    user, plan, activated = await process_cardlink_payment(
        order_id=inv_id,
        telegram_id=int(telegram_id),
        plan_id=plan_id,
    )
    if activated and user and plan:
        await notify_payment_success(int(telegram_id), plan.title, user)

    return Response(content="OK")


async def _parse_redirect_form(request: Request) -> dict:
    if request.method == "POST":
        form = await request.form()
        return {key: str(form.get(key, "")) for key in form.keys()}
    return dict(request.query_params)


@router.get("/return")
@router.post("/return")
async def payment_return(request: Request) -> HTMLResponse:
    """Optional return URL handler after Cardlink redirect."""
    data = await _parse_redirect_form(request)
    inv_id = data.get("InvId", "")
    signature = data.get("SignatureValue", "")
    out_sum = data.get("OutSum", "")

    if inv_id and signature and verify_signature(out_sum, inv_id, signature):
        order = await get_payment_order(inv_id)
        if order and order.status != "paid":
            user = await get_user(order.telegram_id)
            plan = get_plan(order.plan_id)
            if user and plan:
                user, plan, activated = await process_cardlink_payment(
                    order_id=inv_id,
                    telegram_id=order.telegram_id,
                    plan_id=order.plan_id,
                )
                if activated:
                    await notify_payment_success(order.telegram_id, plan.title, user)
                    await mark_payment_order_paid(inv_id)

    return HTMLResponse(_SUCCESS_HTML.format(bot_name=config.BOT_NAME))
