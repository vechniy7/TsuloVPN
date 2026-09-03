"""Telegram webhook — Amvera часто не может ходить в api.telegram.org.

Входящие апдейты приходят от Telegram на наш HTTPS.
Ответы (sendMessage и т.п.) отдаём в HTTP-ответе webhook —
Telegram выполняет их сам, без исходящего запроса с Amvera.
"""

from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import Chat, ChatMemberMember, Message, Update, User as TgUser
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from config import config

logger = logging.getLogger(__name__)

router = APIRouter()

_dp: Dispatcher | None = None
_bot: Bot | None = None

_capture: ContextVar[list[TelegramMethod] | None] = ContextVar("tg_capture", default=None)

_SEND_METHODS = frozenset(
    {
        "sendMessage",
        "sendPhoto",
        "sendDocument",
        "editMessageText",
        "editMessageCaption",
        "editMessageMedia",
        "editMessageReplyMarkup",
        "answerCallbackQuery",
        "deleteMessage",
    }
)

_METHOD_PRIORITY = (
    "sendMessage",
    "sendPhoto",
    "editMessageText",
    "editMessageCaption",
    "editMessageMedia",
    "editMessageReplyMarkup",
    "sendDocument",
    "deleteMessage",
    "answerCallbackQuery",
)


def bind_telegram(dp: Dispatcher, bot: Bot) -> None:
    global _dp, _bot
    _dp = dp
    _bot = bot


def _dummy_result(method: TelegramMethod[TelegramType]) -> TelegramType:
    name = method.__api_method__
    if name == "getChatMember":
        uid = int(getattr(method, "user_id", 0) or 0)
        return ChatMemberMember(  # type: ignore[return-value]
            user=TgUser(id=uid, is_bot=False, first_name="user"),
        )
    if name in _SEND_METHODS and name != "answerCallbackQuery" and name != "deleteMessage":
        chat_id = getattr(method, "chat_id", 0) or 0
        try:
            chat_id = int(chat_id)
        except (TypeError, ValueError):
            chat_id = 0
        mid = getattr(method, "message_id", None) or 1
        try:
            mid = int(mid)
        except (TypeError, ValueError):
            mid = 1
        return Message(  # type: ignore[return-value]
            message_id=mid,
            date=datetime.now(timezone.utc),
            chat=Chat(id=chat_id, type="private"),
        )
    return True  # type: ignore[return-value]


def method_to_webhook_json(method: TelegramMethod) -> dict:
    data = method.model_dump(mode="json", exclude_none=True, exclude_unset=True, by_alias=True)
    data["method"] = method.__api_method__
    return data


def pick_reply_method(calls: list[TelegramMethod]) -> TelegramMethod | None:
    if not calls:
        return None
    by_name = {m.__api_method__: m for m in calls}
    for name in _METHOD_PRIORITY:
        if name in by_name:
            return by_name[name]
    return calls[0]


class HybridSession(AiohttpSession):
    """Во время webhook: send* не уходят в сеть, а копятся для HTTP-ответа."""

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,
    ) -> TelegramType:
        capture = _capture.get()
        name = method.__api_method__

        # На Amvera getChatMember почти всегда падает — не ждём таймаут.
        if capture is not None and name == "getChatMember":
            return _dummy_result(method)

        if capture is not None and name in _SEND_METHODS:
            capture.append(method)
            return _dummy_result(method)

        try:
            return await super().make_request(bot, method, timeout=timeout)
        except Exception:
            if name == "getChatMember":
                return _dummy_result(method)
            if capture is not None and name in _SEND_METHODS:
                capture.append(method)
                return _dummy_result(method)
            raise


def create_bot() -> Bot:
    return Bot(token=config.BOT_TOKEN, session=HybridSession())


@router.get(config.TELEGRAM_WEBHOOK_PATH)
async def telegram_webhook_probe() -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "webhook": config.telegram_webhook_url(),
            "bot_ready": bool(_dp and _bot),
        }
    )


@router.post("/telegram/ping")
async def telegram_ping(request: Request) -> JSONResponse:
    raw = await request.body()
    return JSONResponse({"ok": True, "bytes": len(raw)})


@router.post(config.TELEGRAM_WEBHOOK_PATH)
async def telegram_webhook(request: Request) -> Response:
    if not _dp or not _bot:
        return JSONResponse({"ok": False, "error": "bot not ready"}, status_code=503)

    secret = config.telegram_webhook_secret()
    if secret:
        header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if header != secret:
            logger.warning("Webhook rejected: invalid secret token")
            return JSONResponse({"ok": False, "error": "invalid webhook secret"}, status_code=403)

    try:
        payload = await request.json()
        update = Update.model_validate(payload)
    except Exception as exc:
        logger.warning("Webhook bad payload: %s", exc)
        return JSONResponse({"ok": False, "error": f"bad update: {exc}"}, status_code=400)

    kind = "unknown"
    if update.message:
        kind = f"message:{(update.message.text or '')[:40]}"
    elif update.callback_query:
        kind = f"callback:{(update.callback_query.data or '')[:40]}"
    logger.info("Telegram webhook update_id=%s %s", update.update_id, kind)

    calls: list[TelegramMethod] = []
    token = _capture.set(calls)
    try:
        try:
            await _dp.feed_update(_bot, update)
        except Exception as exc:
            logger.exception("Webhook update handling failed: %s", exc)
            return JSONResponse(
                {"ok": False, "error": f"handler: {exc}", "captured": len(calls)}
            )
        reply = pick_reply_method(calls)
        if reply is not None:
            try:
                body = method_to_webhook_json(reply)
            except Exception as exc:
                logger.exception("Webhook serialize failed: %s", exc)
                return JSONResponse({"ok": False, "error": f"serialize: {exc}"})
            logger.info("Webhook reply method=%s", reply.__api_method__)
            return JSONResponse(content=body)
        return JSONResponse({"ok": True, "note": "no reply method", "captured": len(calls)})
    except Exception as exc:
        logger.exception("Webhook fatal: %s", exc)
        return JSONResponse(content={"ok": False, "error": str(exc)[:500]})
    finally:
        _capture.reset(token)


async def register_webhook(bot: Bot) -> None:
    url = config.telegram_webhook_url()
    secret = config.telegram_webhook_secret()
    kwargs: dict = {
        "drop_pending_updates": True,
        "allowed_updates": ["message", "callback_query"],
    }
    if secret:
        kwargs["secret_token"] = secret
    await bot.set_webhook(url, **kwargs)
    logger.info("Telegram webhook registered: %s", url)


async def maintain_webhook(bot: Bot) -> None:
    """Пытаемся setWebhook с Amvera; если сеть закрыта — нужна внешняя регистрация."""
    for attempt in range(1, 8):
        try:
            await register_webhook(bot)
            return
        except Exception as exc:
            delay = min(45, 5 * attempt)
            logger.warning(
                "Telegram webhook setup attempt %s failed: %s (retry in %ss)",
                attempt,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
    logger.error(
        "Telegram webhook NOT registered from Amvera (api.telegram.org unreachable). "
        "Register externally: scripts/set_webhook.py or GitHub Action."
    )
