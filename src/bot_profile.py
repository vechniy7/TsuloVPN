"""Счётчик пользователей в профиле бота (под названием в Telegram)."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from config import config
from database import get_user_count

logger = logging.getLogger(__name__)

UPDATE_INTERVAL_SEC = 1800


def format_users_count(count: int) -> str:
    spaced = f"{count:,}".replace(",", " ")
    return f"👥 {spaced} пользователей"


async def update_bot_user_count(bot: Bot) -> int:
    count = await get_user_count()
    short = format_users_count(count)
    name = config.BOT_NAME.strip() or "TsuloVPN"
    description = (
        f"{name} — обход блокировок и глушилок.\n"
        f"Быстрый, стабильный и защищённый интернет.\n\n"
        f"{short}"
    )
    try:
        await bot.set_my_short_description(short_description=short)
        await bot.set_my_description(description=description)
        logger.info("Bot profile updated: %s", short)
    except Exception as exc:
        logger.warning("Failed to update bot profile: %s", exc)
    return count


async def profile_update_loop(bot: Bot) -> None:
    while True:
        try:
            await update_bot_user_count(bot)
        except Exception as exc:
            logger.warning("Profile update loop error: %s", exc)
        await asyncio.sleep(UPDATE_INTERVAL_SEC)
