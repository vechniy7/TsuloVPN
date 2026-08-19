import logging
import time

from aiogram import Bot

import ui
from config import config

logger = logging.getLogger(__name__)

_bot: Bot | None = None
_last_admin_alert: dict[str, float] = {}


def set_bot(bot: Bot) -> None:
    global _bot
    _bot = bot


async def notify_admins_source_alert(alert_key: str, message: str) -> None:
    """Telegram-алерт админам при проблемах с VPN_SOURCE_URL (с cooldown)."""
    if not _bot or not config.ADMINS:
        return

    now = time.time()
    last = _last_admin_alert.get(alert_key, 0.0)
    if now - last < config.SOURCE_ALERT_COOLDOWN_SEC:
        return
    _last_admin_alert[alert_key] = now

    text = (
        "<b>⚠ TsuloVPN · источник конфигов</b>\n\n"
        f"{message}\n\n"
        f"<i>Ключ:</i> <code>{config.source_label()}</code>\n"
        f"<i>Действие:</i> смените <code>VPN_SOURCE_URL</code> в Amvera и пересоберите."
    )
    for admin_id in config.ADMINS:
        try:
            await _bot.send_message(admin_id, text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as exc:
            logger.warning("Failed to notify admin %s: %s", admin_id, exc)


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
