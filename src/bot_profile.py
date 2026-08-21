"""Счётчик пользователей в шапке бота (название) и внутри главного экрана."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from config import config
from database import get_user_count

logger = logging.getLogger(__name__)

UPDATE_INTERVAL_SEC = 1800


def format_users_count_spaced(count: int) -> str:
    return f"{count:,}".replace(",", " ")


def format_users_count_label(count: int) -> str:
    return f"👥 {format_users_count_spaced(count)} пользователей"


def format_bot_display_name(count: int) -> str:
    """Имя бота в шапке чата — единственный способ показать число до порога Telegram (~10k MAU)."""
    base = (config.BOT_NAME or "TsuloVPN").strip()
    if not config.BOT_USER_COUNT_IN_NAME:
        return base[:64]
    spaced = format_users_count_spaced(count)
    name = f"{base} · {spaced}"
    return name[:64]


async def update_bot_user_count(bot: Bot) -> int:
    count = await get_user_count()
    name = config.BOT_NAME.strip() or "TsuloVPN"
    try:
        if config.BOT_USER_COUNT_IN_NAME:
            display_name = format_bot_display_name(count)
            await bot.set_my_name(name=display_name)
            logger.info("Bot display name updated: %s", display_name)

        await bot.set_my_short_description(
            short_description=(
                f"{name} — обход блокировок и глушилок. "
                f"Быстрый и стабильный интернет."
            )[:120]
        )
        await bot.set_my_description(
            description=(
                f"{name} — обход блокировок и глушилок.\n"
                f"Быстрый, стабильный и защищённый интернет без границ.\n\n"
                f"Нажмите /start или «Мой доступ»."
            )
        )
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
