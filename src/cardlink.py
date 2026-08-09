import hashlib
import json
import logging
import uuid

import aiohttp

from config import config

logger = logging.getLogger(__name__)

CARDLINK_API_BASE = "https://cardlink.link/api/v1"


class CardlinkError(Exception):
    pass


def verify_signature(out_sum: str, inv_id: str, signature: str) -> bool:
    if not config.CARDLINK_API_TOKEN:
        return False
    raw = f"{out_sum}:{inv_id}:{config.CARDLINK_API_TOKEN}"
    expected = hashlib.md5(raw.encode()).hexdigest().upper()
    return expected == signature.upper()


async def create_bill(
    *,
    amount: int,
    order_id: str,
    description: str,
    telegram_id: int,
    plan_id: str,
    username: str | None = None,
) -> dict:
    if not config.use_cardlink:
        raise CardlinkError("Cardlink is not configured")

    base = config.SUBSCRIPTION_PUBLIC_URL.rstrip("/")
    form = aiohttp.FormData()
    form.add_field("amount", str(amount))
    form.add_field("shop_id", config.CARDLINK_SHOP_ID)
    form.add_field("order_id", order_id)
    form.add_field("description", description)
    form.add_field("type", "normal")
    form.add_field("currency_in", "RUB")
    form.add_field("name", f"{config.BOT_NAME} · подписка")
    form.add_field("payer_pays_commission", "1")
    form.add_field("locale", "ru")
    form.add_field("ttl", "3600")
    form.add_field(
        "custom",
        json.dumps({"telegram_id": telegram_id, "plan_id": plan_id}, ensure_ascii=False),
    )
    form.add_field("success_url", f"{base}/cardlink/success")
    form.add_field("fail_url", f"{base}/cardlink/fail")
    form.add_field("items[0][name]", description)
    form.add_field("items[0][price]", str(amount))
    form.add_field("items[0][quantity]", "1")
    form.add_field("items[0][category]", "digital/subscription/netflix")
    form.add_field("items[0][extra][telegram_id]", str(telegram_id))
    if username:
        form.add_field("items[0][extra][telegram_username]", username.lstrip("@"))

    if config.CARDLINK_PAYMENT_METHOD:
        form.add_field("payment_method", config.CARDLINK_PAYMENT_METHOD)

    headers = {"Authorization": f"Bearer {config.CARDLINK_API_TOKEN}"}

    timeout = aiohttp.ClientTimeout(total=config.FETCH_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            f"{CARDLINK_API_BASE}/bill/create",
            data=form,
            headers=headers,
        ) as response:
            body = await response.json(content_type=None)
            if response.status != 200:
                logger.error("Cardlink bill/create HTTP %s: %s", response.status, body)
                raise CardlinkError(f"Cardlink HTTP {response.status}")

    success = body.get("success")
    if success in (False, "false", "0", 0):
        logger.error("Cardlink bill/create failed: %s", body)
        raise CardlinkError("Cardlink rejected bill creation")

    link_page_url = body.get("link_page_url")
    bill_id = body.get("bill_id")
    if not link_page_url or not bill_id:
        raise CardlinkError("Cardlink response missing payment link")

    return {
        "bill_id": bill_id,
        "link_page_url": link_page_url,
        "link_url": body.get("link_url", link_page_url),
    }


async def get_bill_status(bill_id: str) -> str | None:
    if not config.use_cardlink:
        return None

    headers = {"Authorization": f"Bearer {config.CARDLINK_API_TOKEN}"}
    timeout = aiohttp.ClientTimeout(total=config.FETCH_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(
            f"{CARDLINK_API_BASE}/bill/status",
            params={"id": bill_id},
            headers=headers,
        ) as response:
            body = await response.json(content_type=None)
            if response.status != 200:
                return None
            if body.get("success") in (False, "false"):
                return None
            return body.get("status")


def new_order_id(telegram_id: int, plan_id: str) -> str:
    return f"{telegram_id}-{plan_id}-{uuid.uuid4().hex[:10]}"
