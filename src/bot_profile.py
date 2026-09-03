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
                f"💜 {name} — быстрый VPN. Ключ в боте · Happ · 69₽/мес"
            )[:120]
        )
        await bot.set_my_description(
            description=(
                f"💜 {name}\n"
                f"Быстрый VPN через Happ\n\n"
                f"🔑 /start → Мой ключ\n"
                f"💳 Тариф 69 ₽ / месяц\n"
                f"📱 1 устройство на ключ\n\n"
                f"Инструкция и поддержка — в меню бота."
            )
        )
        logger.info("Bot profile restored: %s", name)
    except Exception as exc:
        logger.warning("Failed to restore bot profile: %s", exc)
