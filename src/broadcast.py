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
    """URL Cloudflare Pages /telegram/broadcast (не Amvera — там 404).

    Берём хост из TELEGRAM webhook (pages.dev), иначе PUBLIC_URL с pages.dev.
    FALLBACK (Amvera) для рассылки не подходит: Amvera не ходит в Telegram API.
    """
    webhook = (config.telegram_webhook_url() or "").rstrip("/")
    if webhook.endswith("/telegram/webhook"):
        return f"{webhook[: -len('/telegram/webhook')]}/telegram/broadcast"

    public = (config.SUBSCRIPTION_PUBLIC_URL or "").rstrip("/")
    fallback = config.subscription_fallback_base()
    for base in (public, fallback):
        if not base:
            continue
        host = base.lower()
        if "pages.dev" in host or "workers.dev" in host:
            return f"{base}/telegram/broadcast"
    if public:
        return f"{public}/telegram/broadcast"
    if fallback:
        return f"{fallback}/telegram/broadcast"
    raise RuntimeError("Не задан URL Cloudflare для /telegram/broadcast")


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


def build_direct_message_job(admin_id: int, telegram_id: int, text: str) -> dict:
    """Одно сообщение конкретному пользователю через Cloudflare edge."""
    body = (text or "").strip()
    if not body:
        raise ValueError("Пустой текст сообщения")
    chat_id = int(telegram_id)
    return {
        "admin_id": int(admin_id),
        "recipients": [chat_id],
        "text": body,
        "caption": None,
        "photo_file_id": None,
        "parse_mode": "HTML",
        "total": 1,
        "notify_admin": False,
    }


def _edge_auth_token() -> str:
    """Токен для Cloudflare /telegram/broadcast.

    Сначала ADMIN_PANEL_TOKEN, иначе BOT_TOKEN (Pages уже хранит BOT_TOKEN для webhook).
    """
    panel = (config.ADMIN_PANEL_TOKEN or "").strip()
    if panel:
        return panel
    bot = (config.BOT_TOKEN or "").strip()
    if bot:
        return bot
    raise RuntimeError("Нужен ADMIN_PANEL_TOKEN или BOT_TOKEN для рассылки")


async def dispatch_broadcast_to_edge(job: dict) -> dict:
    """POST job на Cloudflare Pages /telegram/broadcast."""
    url = edge_broadcast_url()
    panel = (config.ADMIN_PANEL_TOKEN or "").strip()
    bot = (config.BOT_TOKEN or "").strip()
    # Сначала panel-токен; при 401 — BOT_TOKEN (часто уже есть в Pages Secrets).
    tokens: list[tuple[str, str]] = []
    if panel:
        tokens.append(("panel", panel))
    if bot and bot != panel:
        tokens.append(("bot", bot))
    if not tokens:
        raise RuntimeError("Нужен ADMIN_PANEL_TOKEN или BOT_TOKEN для рассылки")

    timeout = aiohttp.ClientTimeout(total=45)
    last_error = "unknown"
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for label, token in tokens:
            logger.info(
                "edge broadcast POST %s recipients=%s auth=%s",
                url,
                len(job.get("recipients") or []),
                label,
            )
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            }
            async with session.post(url, json=job, headers=headers) as resp:
                raw = await resp.text()
                try:
                    data = json.loads(raw) if raw else {}
                except Exception:
                    data = {"raw": raw[:500]}
                if resp.status < 400:
                    return data if isinstance(data, dict) else {"ok": True, "raw": data}
                last_error = (
                    f"HTTP {resp.status}: "
                    f"{(data.get('error') if isinstance(data, dict) else None) or raw[:200]}"
                )
                logger.error(
                    "edge broadcast failed url=%s auth=%s status=%s body=%s",
                    url,
                    label,
                    resp.status,
                    raw[:500],
                )
                # 401 — пробуем следующий токен; остальное — сразу ошибка.
                if resp.status != 401:
                    break

    raise RuntimeError(
        f"Cloudflare broadcast failed ({url}): {last_error}. "
        "На Pages Secrets нужны BOT_TOKEN и/или ADMIN_PANEL_TOKEN (= Amvera)."
    )


def draft_to_dict(draft: BroadcastDraft) -> dict:
    return asdict(draft)
