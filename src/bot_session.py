"""Telegram Bot session — с прокси, если Amvera не видит api.telegram.org."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from config import config

logger = logging.getLogger(__name__)


def create_bot() -> Bot:
    proxy = config.telegram_proxy_url()
    if proxy:
        logger.info("Telegram API via proxy %s", config.telegram_proxy_label())
        session = AiohttpSession(proxy=proxy)
        return Bot(token=config.BOT_TOKEN, session=session)
    logger.warning(
        "TELEGRAM_PROXY_URL / UPSTREAM_PROXY_URL not set — "
        "bot may fail on hosts that block api.telegram.org"
    )
    return Bot(token=config.BOT_TOKEN)
