import html
import logging

from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config
from payments import format_access_until

logger = logging.getLogger(__name__)

_bot: Bot | None = None


def set_bot(bot: Bot) -> None:
    global _bot
    _bot = bot


async def notify_payment_success(telegram_id: int, plan_title: str, user) -> None:
    if not _bot:
        return

    text = (
        f"<b>Оплата получена</b>\n\n"
        f"Тариф: {html.escape(plan_title)}\n"
        f"Статус: {format_access_until(user)}\n\n"
        f"Нажмите «Мой доступ», чтобы получить ссылку."
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="Мой доступ", callback_data="get_key")
    builder.button(text="← Меню", callback_data="back_to_menu")
    builder.adjust(1)

    try:
        await _bot.send_message(
            telegram_id,
            text,
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.warning("Failed to notify user %s about payment: %s", telegram_id, exc)
