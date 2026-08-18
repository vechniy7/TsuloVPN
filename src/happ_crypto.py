import json
import logging

import aiohttp

from config import config

logger = logging.getLogger(__name__)

HAPP_CRYPTO_API = "https://crypto.happ.su/api-v2.php"


def _parse_crypto_response(raw: str) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("happ://"):
        return text
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("encrypted_link", "link", "url", "result"):
        value = payload.get(key)
        if isinstance(value, str) and value.startswith("happ://"):
            return value.strip()
    return None


async def encrypt_subscription_url(subscription_url: str) -> str:
    """Шифрует ссылку подписки в happ://crypt5/... — скрывает URL и конфиги в Happ."""
    if not config.HAPP_ENCRYPT_SUBSCRIPTION:
        return subscription_url
    return await _encrypt_or_plain(subscription_url)


async def bot_subscription_import_url(subscription_url: str) -> str:
    """Ссылка для «Мой доступ» в Telegram: по умолчанию plain https."""
    if not config.BOT_ENCRYPT_SUBSCRIPTION:
        return subscription_url
    return await _encrypt_or_plain(subscription_url)


async def _encrypt_or_plain(subscription_url: str) -> str:
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                HAPP_CRYPTO_API,
                json={"url": subscription_url},
                headers={"Content-Type": "application/json"},
            ) as resp:
                resp.raise_for_status()
                text = (await resp.text()).strip()
    except Exception as exc:
        logger.warning("Happ crypto API failed, using plain URL: %s", exc)
        return subscription_url

    encrypted = _parse_crypto_response(text)
    if encrypted:
        return encrypted

    logger.warning("Happ crypto API returned unexpected response, using plain URL")
    return subscription_url
