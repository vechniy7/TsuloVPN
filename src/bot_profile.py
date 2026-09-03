"""Профиль бота в Telegram (без числа пользователей — только в сообщениях бота)."""

from __future__ import annotations

import logging

from aiogram import Bot

from config import config

logger = logging.getLogger(__name__)


async def restore_bot_profile(bot: Bot) -> None:
    """Имя и описание бота для пользователей."""
    name = (config.BOT_NAME or "TsuloVPN").strip()
    try:
        await bot.set_my_name(name=name[:64])
        await bot.set_my_short_description(
            short_description=(
                f"{name} — VPN через Happ. Ключ в боте, тариф 69 ₽/мес."
            )[:120]
        )
        await bot.set_my_description(
            description=(
                f"{name} — быстрый VPN-доступ.\n\n"
                f"1. /start → «Мой доступ» — получить ключ\n"
                f"2. Скопировать ссылку и вставить в Happ\n"
                f"3. Подписка — 69 ₽ / месяц\n\n"
                f"Инструкция и поддержка — в меню бота."
            )
        )
        logger.info("Bot profile restored: %s", name)
    except Exception as exc:
        logger.warning("Failed to restore bot profile: %s", exc)
