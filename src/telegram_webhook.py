"""Telegram webhook — Amvera часто не может ходить в api.telegram.org.

Входящие апдейты приходят от Telegram на наш HTTPS.
Ответы (sendMessage и т.п.) отдаём в HTTP-ответе webhook —
Telegram выполняет их сам, без исходящего запроса с Amvera.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher
from aiogram.client.default import Default
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import Chat, ChatMemberMember, Message, Update, User as TgUser
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from config import config

logger = logging.getLogger(__name__)

router = APIRouter()

_dp: Dispatcher | None = None
_bot: Bot | None = None

_capture: ContextVar[list[TelegramMethod] | None] = ContextVar("tg_capture", default=None)
_UNSET = object()

# Во время обработки webhook НИКОГДА не ходим в api.telegram.org
# (иначе Telegram ждёт ответ >10s → Connection timed out → /start «молчит»).
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
    "answerCallbackQuery",
    "sendPhoto",
    "editMessageMedia",
    "editMessageCaption",
    "sendMessage",
    "editMessageText",
    "editMessageReplyMarkup",
    "sendDocument",
    "deleteMessage",
)


def pick_reply_methods(calls: list[TelegramMethod]) -> list[TelegramMethod]:
    """Все исходящие методы для CF multi-exec (порядок важен)."""
    if not calls:
        return []
    priority = {name: i for i, name in enumerate(_METHOD_PRIORITY)}
    ordered = sorted(
        calls,
        key=lambda m: priority.get(m.__api_method__, 100),
    )
    # Один method на тип — последний побеждает (актуальный экран).
    by_name: dict[str, TelegramMethod] = {}
    for method in ordered:
        by_name[method.__api_method__] = method
    result = sorted(
        by_name.values(),
        key=lambda m: priority.get(m.__api_method__, 100),
    )
    return result


def pick_reply_method(calls: list[TelegramMethod]) -> TelegramMethod | None:
    methods = pick_reply_methods(calls)
    return methods[0] if methods else None


_WEBHOOK_HANDLE_TIMEOUT_SEC = 8.0


def bind_telegram(dp: Dispatcher, bot: Bot) -> None:
    global _dp, _bot
    _dp = dp
    _bot = bot


def bot_id_from_token(token: str) -> int:
    try:
        return int((token or "").split(":", 1)[0])
    except (TypeError, ValueError):
        return 0


def _dummy_result(method: TelegramMethod[TelegramType], *, bot: Bot | None = None) -> TelegramType:
    name = method.__api_method__
    if name == "getMe":
        tid = bot_id_from_token(config.BOT_TOKEN)
        return TgUser(  # type: ignore[return-value]
            id=tid,
            is_bot=True,
            first_name=(config.BOT_NAME or "TsuloVPN")[:64],
            username="TsuloVPN_bot",
        )
    if name == "getChatMember":
        uid = int(getattr(method, "user_id", 0) or 0)
        return ChatMemberMember(  # type: ignore[return-value]
            user=TgUser(id=uid, is_bot=False, first_name="user"),
        )
    if name in _SEND_METHODS and name not in ("answerCallbackQuery", "deleteMessage"):
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


def _scrub(value):
    """Убрать aiogram Default и сделать значение JSON-safe."""
    if isinstance(value, Default):
        return _UNSET
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            scrubbed = _scrub(item)
            if scrubbed is _UNSET:
                continue
            out[key] = scrubbed
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            scrubbed = _scrub(item)
            if scrubbed is _UNSET:
                continue
            out.append(scrubbed)
        return out
    if isinstance(value, datetime):
        return int(value.timestamp())
    return value


def method_to_webhook_json(method: TelegramMethod) -> dict:
    raw = method.model_dump(mode="python", exclude_none=True, exclude_unset=True, by_alias=True)
    data = _scrub(raw)
    if not isinstance(data, dict):
        data = {}
    data["method"] = method.__api_method__
    # FSInputFile / локальные файлы в webhook JSON нельзя — только URL/file_id.
    return json.loads(json.dumps(data, ensure_ascii=False, default=_json_default))


def _json_default(obj):
    name = type(obj).__name__
    if name in ("FSInputFile", "BufferedInputFile", "URLInputFile"):
        path = getattr(obj, "path", None) or getattr(obj, "url", None)
        raise TypeError(
            f"{name} cannot be sent via webhook reply "
            f"(use HTTPS photo URL). path={path!r}"
        )
    raise TypeError(f"Object of type {name} is not JSON serializable")


class HybridSession(AiohttpSession):
    """Во время webhook: все Bot API-вызовы локальные (без сети к Telegram)."""

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,
    ) -> TelegramType:
        capture = _capture.get()
        name = method.__api_method__

        if capture is not None:
            if name in _SEND_METHODS:
                capture.append(method)
            return _dummy_result(method, bot=bot)

        # Вне webhook — короткий таймаут, чтобы не вешать event loop на Amvera.
        try:
            return await asyncio.wait_for(
                super().make_request(bot, method, timeout=timeout),
                timeout=5.0,
            )
        except Exception:
            if name in ("getMe", "getChatMember"):
                return _dummy_result(method, bot=bot)
            raise


def create_bot() -> Bot:
    bot = Bot(token=config.BOT_TOKEN, session=HybridSession())
    # Кладём getMe в кэш без сети — иначе aiogram дергает api.telegram.org на каждый апдейт.
    tid = bot_id_from_token(config.BOT_TOKEN)
    if tid:
        object.__setattr__(
            bot,
            "_me",
            TgUser(
                id=tid,
                is_bot=True,
                first_name=(config.BOT_NAME or "TsuloVPN")[:64],
                username="TsuloVPN_bot",
            ),
        )
    return bot


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
            await asyncio.wait_for(
                _dp.feed_update(_bot, update),
                timeout=_WEBHOOK_HANDLE_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            logger.error("Webhook handler timed out after %ss", _WEBHOOK_HANDLE_TIMEOUT_SEC)
            return JSONResponse({"ok": False, "error": "handler timeout", "captured": len(calls)})
        except Exception as exc:
            logger.exception("Webhook update handling failed: %s", exc)
            return JSONResponse(
                {"ok": False, "error": f"handler: {exc}", "captured": len(calls)}
            )

        replies = pick_reply_methods(calls)
        if not replies:
            return JSONResponse({"ok": True, "note": "no reply method", "captured": len(calls)})
        try:
            methods_json = [method_to_webhook_json(m) for m in replies]
        except Exception as exc:
            logger.exception("Webhook serialize failed: %s", exc)
            return JSONResponse({"ok": False, "error": f"serialize: {exc}"})
        names = [m.__api_method__ for m in replies]
        logger.info("Webhook reply methods=%s", ",".join(names))
        # CF Pages исполняет весь список через Bot API (токен на edge).
        # Один method оставляем на верхнем уровне — fallback, если edge старый.
        body = {"ok": True, "methods": methods_json, **methods_json[0]}
        return JSONResponse(content=body)
    except Exception as exc:
        logger.exception("Webhook fatal: %s", exc)
        return JSONResponse(content={"ok": False, "error": str(exc)[:500]})
    finally:
        _capture.reset(token)


async def maintain_webhook(bot: Bot) -> None:
    """С Amvera setWebhook почти всегда невозможен — не пытаемся (висит и мешает)."""
    logger.info(
        "Skip setWebhook from Amvera (no outbound to api.telegram.org). "
        "Webhook must be registered externally: scripts/set_webhook.py / GitHub Action. "
        "Expected URL: %s",
        config.telegram_webhook_url(),
    )
