"""Профиль бота в Telegram (без числа пользователей — только в сообщениях бота)."""

from __future__ import annotations

import logging

from aiogram import Bot

from config import config

logger = logging.getLogger(__name__)


async def restore_bot_profile(bot: Bot) -> None:
    """Вернуть чистое имя бота и описание без счётчика пользователей."""
    name = (config.BOT_NAME or "TsuloVPN").strip()
    try:
        await bot.set_my_name(name=name[:64])
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
        logger.info("Bot profile restored: %s", name)
    except Exception as exc:
        logger.warning("Failed to restore bot profile: %s", exc)
