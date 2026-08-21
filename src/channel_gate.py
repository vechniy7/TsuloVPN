"""Проверка подписки на обязательный Telegram-канал перед доступом к боту."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.enums import ChatMemberStatus
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from config import config
from database import create_user, get_user
from render import render_screen
import ui

logger = logging.getLogger(__name__)

CHECK_CALLBACK = "check_channel_sub"


async def is_channel_member(bot: Bot, user_id: int) -> bool:
    channel = config.required_channel_id
    if not channel:
        return True
    try:
        member = await bot.get_chat_member(channel, user_id)
    except Exception as exc:
        logger.warning("Channel membership check failed for %s: %s", user_id, exc)
        return False

    if member.status == ChatMemberStatus.RESTRICTED:
        return bool(getattr(member, "is_member", False))
    return member.status in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.CREATOR,
    )


async def ensure_user_registered(
    *,
    user_id: int,
    full_name: str | None,
    username: str | None,
) -> None:
    if await get_user(user_id):
        return
    await create_user(
        telegram_id=user_id,
        full_name=full_name or "User",
        username=username,
        is_admin=user_id in config.ADMINS,
    )


async def prompt_channel_subscription(
    message: Message,
    *,
    edit: bool = False,
) -> None:
    await render_screen(
        message,
        caption=ui.screen_channel_required(),
        markup=ui.kb_channel_required(),
        screen="home",
        edit=edit,
    )


class ChannelGateMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not config.channel_gate_enabled:
            return await handler(event, data)

        update = event if isinstance(event, Update) else data.get("event_update")
        if not isinstance(update, Update):
            return await handler(event, data)

        tg_user = None
        target_message: Message | None = None
        callback: CallbackQuery | None = None

        if update.message and update.message.from_user:
            tg_user = update.message.from_user
            target_message = update.message
        elif update.callback_query and update.callback_query.from_user:
            callback = update.callback_query
            tg_user = callback.from_user
            target_message = callback.message

        if not tg_user or not target_message:
            return await handler(event, data)

        user_id = tg_user.id
        if user_id in config.ADMINS:
            return await handler(event, data)

        if callback and callback.data == CHECK_CALLBACK:
            return await handler(event, data)

        bot: Bot = data["bot"]
        if await is_channel_member(bot, user_id):
            return await handler(event, data)

        await ensure_user_registered(
            user_id=user_id,
            full_name=tg_user.full_name,
            username=tg_user.username,
        )

        if callback:
            await callback.answer()
            await prompt_channel_subscription(target_message, edit=True)
            return None

        await prompt_channel_subscription(target_message, edit=False)
        return None
