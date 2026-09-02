"""Telegram webhook — вместо long polling (Amvera нестабильно тянет getUpdates)."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import APIRouter, HTTPException, Request, Response

from config import config

logger = logging.getLogger(__name__)

router = APIRouter()

_dp: Dispatcher | None = None
_bot: Bot | None = None


def bind_telegram(dp: Dispatcher, bot: Bot) -> None:
    global _dp, _bot
    _dp = dp
    _bot = bot


@router.post(config.TELEGRAM_WEBHOOK_PATH)
async def telegram_webhook(request: Request) -> Response:
    if not _dp or not _bot:
        raise HTTPException(status_code=503, detail="bot not ready")

    secret = config.telegram_webhook_secret()
    if secret:
        header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if header != secret:
            raise HTTPException(status_code=403, detail="invalid webhook secret")

    try:
        payload = await request.json()
        update = Update.model_validate(payload)
        await _dp.feed_update(_bot, update)
    except Exception as exc:
        logger.warning("Webhook update handling failed: %s", exc)
        raise HTTPException(status_code=500, detail="update failed") from exc

    return Response(status_code=200)


async def register_webhook(bot: Bot) -> None:
    url = config.telegram_webhook_url()
    secret = config.telegram_webhook_secret()
    kwargs: dict = {"drop_pending_updates": True, "allowed_updates": []}
    if secret:
        kwargs["secret_token"] = secret
    await bot.set_webhook(url, **kwargs)
    logger.info("Telegram webhook registered: %s", url)


async def maintain_webhook(bot: Bot) -> None:
    """Фоновая регистрация webhook — не блокирует HTTP-сервер при сбое Telegram API."""
    for attempt in range(1, 25):
        try:
            await register_webhook(bot)
            return
        except Exception as exc:
            delay = min(60, 5 * attempt)
            logger.warning(
                "Telegram webhook setup attempt %s failed: %s (retry in %ss)",
                attempt,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
    logger.error(
        "Telegram webhook not registered after retries — "
        "check BOT_TOKEN and outbound access to api.telegram.org"
    )
