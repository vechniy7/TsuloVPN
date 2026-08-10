import logging

from aiogram import Bot

import ui

logger = logging.getLogger(__name__)

_bot: Bot | None = None


def set_bot(bot: Bot) -> None:
    global _bot
    _bot = bot


async def notify_payment_success(telegram_id: int, plan_title: str, user) -> None:
    if not _bot:
        return

    try:
        await _bot.send_message(
            telegram_id,
            ui.screen_payment_success(plan_title, user),
            reply_markup=ui.kb_payment_success(),
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.warning("Failed to notify user %s about payment: %s", telegram_id, exc)
