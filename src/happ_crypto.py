import logging

import aiohttp

from config import config

logger = logging.getLogger(__name__)

HAPP_CRYPTO_API = "https://crypto.happ.su/api-v2.php"


async def encrypt_subscription_url(subscription_url: str) -> str:
    """Шифрует ссылку подписки в happ://crypt5/... — скрывает URL и конфиги в Happ."""
    if not config.HAPP_ENCRYPT_SUBSCRIPTION:
        return subscription_url

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

    if text.startswith("happ://"):
        return text

    logger.warning("Happ crypto API returned unexpected response, using plain URL")
    return subscription_url
