"""Рассылка сообщений всем пользователям бота (только для админов)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from database import get_all_user_ids

logger = logging.getLogger(__name__)

SEND_DELAY_SEC = 0.035
PROGRESS_EVERY = 25


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
    skipped: int = 0


ProgressCallback = Callable[[int, int, int, int], Awaitable[None]]

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


async def run_broadcast(
    bot: Bot,
    admin_id: int,
    draft: BroadcastDraft,
    *,
    on_progress: ProgressCallback | None = None,
) -> BroadcastResult:
    _running.add(admin_id)
    sent = blocked = failed = skipped = 0
    total = 0

    try:
        user_ids = await get_all_user_ids()
        recipients = [uid for uid in user_ids if uid != admin_id]
        total = len(recipients)
        logger.info("Broadcast started by %s: %s recipients", admin_id, total)

        if on_progress:
            await on_progress(sent, blocked, failed, total)

        for idx, chat_id in enumerate(recipients, start=1):
            while True:
                try:
                    await bot.copy_message(
                        chat_id=chat_id,
                        from_chat_id=draft.chat_id,
                        message_id=draft.message_id,
                    )
                    sent += 1
                    break
                except TelegramRetryAfter as exc:
                    wait = float(exc.retry_after) + 0.5
                    logger.info("Broadcast rate limit, sleep %.1fs", wait)
                    await asyncio.sleep(wait)
                except TelegramForbiddenError:
                    blocked += 1
                    break
                except TelegramBadRequest as exc:
                    logger.warning("Broadcast bad request to %s: %s", chat_id, exc)
                    failed += 1
                    break
                except Exception as exc:
                    logger.warning("Broadcast to %s failed: %s", chat_id, exc)
                    failed += 1
                    break

            processed = sent + blocked + failed
            if on_progress and (processed % PROGRESS_EVERY == 0 or idx == total):
                await on_progress(sent, blocked, failed, total)

            await asyncio.sleep(SEND_DELAY_SEC)
    finally:
        _running.discard(admin_id)

    result = BroadcastResult(
        total=total,
        sent=sent,
        blocked=blocked,
        failed=failed,
        skipped=skipped,
    )
    logger.info(
        "Broadcast finished by %s: sent=%s blocked=%s failed=%s total=%s",
        admin_id,
        sent,
        blocked,
        failed,
        total,
    )
    return result
