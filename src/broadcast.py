"""Рассылка сообщений всем пользователям бота (только для админов).

Фактическая отправка идёт с Cloudflare (BOT_TOKEN), т.к. Amvera
не достучится до api.telegram.org. Amvera кладёт job в webhook-ответ
или POST на /telegram/broadcast (панель).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass

import aiohttp

from config import config
from database import get_all_user_ids

logger = logging.getLogger(__name__)


@dataclass
class BroadcastDraft:
    chat_id: int
    message_id: int
    text: str | None = None
    caption: str | None = None
    photo_file_id: str | None = None
    parse_mode: str | None = "HTML"


@dataclass(frozen=True)
class BroadcastResult:
    total: int
    sent: int
    blocked: int
    failed: int
    skipped: int = 0


_waiting: set[int] = set()
_drafts: dict[int, BroadcastDraft] = {}
_running: set[int] = set()
_panel_running = False


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


def save_draft(
    admin_id: int,
    chat_id: int,
    message_id: int,
    *,
    text: str | None = None,
    caption: str | None = None,
    photo_file_id: str | None = None,
    parse_mode: str | None = "HTML",
) -> None:
    _waiting.discard(admin_id)
    _drafts[admin_id] = BroadcastDraft(
        chat_id=chat_id,
        message_id=message_id,
        text=(text or None),
        caption=(caption or None),
        photo_file_id=(photo_file_id or None),
        parse_mode=parse_mode,
    )


def pop_draft(admin_id: int) -> BroadcastDraft | None:
    return _drafts.pop(admin_id, None)


def is_running(admin_id: int) -> bool:
    return admin_id in _running


def mark_running(admin_id: int, running: bool = True) -> None:
    if running:
        _running.add(admin_id)
    else:
        _running.discard(admin_id)


def is_panel_broadcast_running() -> bool:
    return _panel_running


def mark_panel_broadcast_running(running: bool = True) -> None:
    global _panel_running
    _panel_running = bool(running)


def schedule_clear_running(admin_id: int | None, recipient_count: int) -> None:
    """Снять флаг «идёт рассылка» после ориентировочного времени CF-отправки."""
    delay = min(3600.0, max(90.0, float(recipient_count) * 0.05 + 45.0))

    async def _clear() -> None:
        await asyncio.sleep(delay)
        if admin_id is not None:
            mark_running(int(admin_id), False)
        else:
            mark_panel_broadcast_running(False)

    try:
        asyncio.get_running_loop().create_task(_clear())
    except RuntimeError:
        if admin_id is not None:
            mark_running(int(admin_id), False)
        else:
            mark_panel_broadcast_running(False)


def edge_broadcast_url() -> str:
    base = (
        config.subscription_fallback_base()
        or (config.SUBSCRIPTION_PUBLIC_URL or "").rstrip("/")
    )
    return f"{base.rstrip('/')}/telegram/broadcast"


async def build_broadcast_job(
    admin_id: int,
    draft: BroadcastDraft,
    *,
    exclude_admin: bool = True,
) -> dict:
    """Payload для Cloudflare: текст/фото + список chat_id."""
    user_ids = await get_all_user_ids()
    recipients = []
    for uid in user_ids:
        try:
            chat_id = int(uid)
        except (TypeError, ValueError):
            continue
        if exclude_admin and chat_id == int(admin_id):
            continue
        recipients.append(chat_id)
    body_text = (draft.text or draft.caption or "").strip()
    if not body_text and not draft.photo_file_id:
        raise ValueError("Пустой черновик рассылки")
    return {
        "admin_id": admin_id,
        "recipients": recipients,
        "text": draft.text,
        "caption": draft.caption,
        "photo_file_id": draft.photo_file_id,
        "parse_mode": draft.parse_mode or "HTML",
        "total": len(recipients),
    }


async def build_text_broadcast_job(admin_id: int, text: str) -> dict:
    draft = BroadcastDraft(
        chat_id=admin_id,
        message_id=0,
        text=text.strip(),
        parse_mode="HTML",
    )
    return await build_broadcast_job(admin_id, draft)


async def dispatch_broadcast_to_edge(job: dict) -> dict:
    """POST job на Cloudflare Pages /telegram/broadcast."""
    if not config.ADMIN_PANEL_TOKEN:
        raise RuntimeError("ADMIN_PANEL_TOKEN не задан")
    url = edge_broadcast_url()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.ADMIN_PANEL_TOKEN}",
    }
    timeout = aiohttp.ClientTimeout(total=45)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=job, headers=headers) as resp:
            raw = await resp.text()
            try:
                data = json.loads(raw) if raw else {}
            except Exception:
                data = {"raw": raw[:500]}
            if resp.status >= 400:
                logger.error("edge broadcast failed status=%s body=%s", resp.status, raw[:500])
                raise RuntimeError(
                    f"Cloudflare broadcast HTTP {resp.status}: "
                    f"{(data.get('error') if isinstance(data, dict) else None) or raw[:200]}"
                )
            return data if isinstance(data, dict) else {"ok": True, "raw": data}


def draft_to_dict(draft: BroadcastDraft) -> dict:
    return asdict(draft)
