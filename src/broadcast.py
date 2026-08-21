"""Рассылка сообщений всем пользователям бота (только для админов)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from database import get_all_users

logger = logging.getLogger(__name__)

SEND_DELAY_SEC = 0.05


@dataclass(frozen=True)
class BroadcastDraft:
    chat_id: int
    message_id: int


@dataclass(frozen=True)
class BroadcastResult:
    total: int
    sent: int
    blocked: int
    failed: int


_waiting: set[int] = set()
_drafts: dict[int, BroadcastDraft] = {}
_running: set[int] = set()


def start_draft(admin_id: int) -> None:
    _waiting.add(admin_id)
    _drafts.pop(admin_id, None)


def cancel_draft(admin_id: int) -> None:
    _waiting.discard(admin_id)
    _drafts.pop(admin_id, None)


def is_waiting_draft(admin_id: int) -> bool:
    return admin_id in _waiting


def has_draft(admin_id: int) -> bool:
    return admin_id in _drafts


def save_draft(admin_id: int, chat_id: int, message_id: int) -> None:
    _waiting.discard(admin_id)
    _drafts[admin_id] = BroadcastDraft(chat_id=chat_id, message_id=message_id)


def pop_draft(admin_id: int) -> BroadcastDraft | None:
    return _drafts.pop(admin_id, None)


def is_running(admin_id: int) -> bool:
    return admin_id in _running


async def run_broadcast(bot: Bot, admin_id: int, draft: BroadcastDraft) -> BroadcastResult:
    _running.add(admin_id)
    sent = blocked = failed = 0
    users = await get_all_users()
    total = len(users)

    try:
        for user in users:
            if user.telegram_id == admin_id:
                continue
            while True:
                try:
                    await bot.copy_message(
                        chat_id=user.telegram_id,
                        from_chat_id=draft.chat_id,
                        message_id=draft.message_id,
                    )
                    sent += 1
                    break
                except TelegramRetryAfter as exc:
                    await asyncio.sleep(float(exc.retry_after) + 0.5)
                except TelegramForbiddenError:
                    blocked += 1
                    break
                except TelegramBadRequest:
                    failed += 1
                    break
                except Exception as exc:
                    logger.warning("Broadcast to %s failed: %s", user.telegram_id, exc)
                    failed += 1
                    break
            await asyncio.sleep(SEND_DELAY_SEC)
    finally:
        _running.discard(admin_id)

    return BroadcastResult(total=total, sent=sent, blocked=blocked, failed=failed)
