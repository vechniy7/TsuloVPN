"""Отправка экранов бота. Баннеры — по HTTPS URL (webhook не умеет FSInputFile)."""

from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InputMediaPhoto, Message

from config import config

logger = logging.getLogger(__name__)

PHOTO_DIR = Path(__file__).parent / "photo"
USE_SCREEN_PHOTOS = True

# Имена файлов в cloudflare/pages/public и src/photo
SCREEN_PHOTO_FILES = {
    "home": "1vpn.PNG",
    "access": "2vpn.PNG",
    "help": "2vpn.PNG",
    "tariffs": "3vpn.PNG",
    "docs": "3vpn.PNG",
    "channel": "1vpn.PNG",
    "donate": "3vpn.PNG",
    "admin": "1vpn.PNG",
}

CAPTION_LIMIT = 4096
PHOTO_CAPTION_LIMIT = 1024

_file_ids: dict[str, str] = {}


def photo_url(screen: str) -> str | None:
    if not USE_SCREEN_PHOTOS:
        return None
    filename = SCREEN_PHOTO_FILES.get(screen or "")
    if not filename:
        return None
    # Локальный файл должен существовать на диске (sanity).
    if not (PHOTO_DIR / filename).is_file():
        return None
    base = (config.SUBSCRIPTION_PUBLIC_URL or "").rstrip("/")
    if not base.startswith("https://"):
        return None
    return f"{base}/{filename}"


def _media(screen: str) -> str | None:
    """file_id или публичный HTTPS URL — оба сериализуются в webhook JSON."""
    if not USE_SCREEN_PHOTOS:
        return None
    file_id = _file_ids.get(screen)
    if file_id:
        return file_id
    return photo_url(screen)


def _remember_file_id(screen: str, message: Message) -> None:
    if screen and message.photo:
        _file_ids[screen] = message.photo[-1].file_id


async def render_screen(
    message: Message,
    *,
    caption: str,
    markup,
    screen: str | None,
    edit: bool,
) -> Message | None:
    caption = caption.strip()
    media = _media(screen) if screen else None
    limit = PHOTO_CAPTION_LIMIT if media is not None else CAPTION_LIMIT
    if len(caption) > limit:
        caption = caption[: limit - 1].rstrip() + "…"

    has_photo = bool(message.photo) if edit else False

    try:
        if edit and media is None and has_photo:
            try:
                await message.delete()
            except TelegramBadRequest:
                pass
            return await message.answer(
                caption,
                reply_markup=markup,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

        if edit and media is not None and has_photo:
            sent = await message.edit_media(
                InputMediaPhoto(media=media, caption=caption, parse_mode="HTML"),
                reply_markup=markup,
            )
            result = sent if isinstance(sent, Message) else message
            _remember_file_id(screen or "", result)
            return result

        if edit and media is None and not has_photo:
            return await message.edit_text(
                caption,
                reply_markup=markup,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

        if edit:
            try:
                await message.delete()
            except TelegramBadRequest:
                pass

        if media is not None:
            sent = await message.answer_photo(
                media,
                caption=caption,
                reply_markup=markup,
                parse_mode="HTML",
            )
            _remember_file_id(screen or "", sent)
            return sent

        return await message.answer(
            caption,
            reply_markup=markup,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except TelegramBadRequest as exc:
        text = str(exc).lower()
        if "message is not modified" in text:
            return message
        logger.warning("render_screen failed (%s/%s): %s", screen, edit, exc)
        return await message.answer(
            caption,
            reply_markup=markup,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


async def send_screen(
    bot: Bot,
    chat_id: int,
    *,
    caption: str,
    markup,
    screen: str,
) -> Message:
    caption = caption.strip()
    media = _media(screen)
    limit = PHOTO_CAPTION_LIMIT if media is not None else CAPTION_LIMIT
    if len(caption) > limit:
        caption = caption[: limit - 1].rstrip() + "…"
    if media is None:
        return await bot.send_message(
            chat_id,
            caption,
            reply_markup=markup,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    sent = await bot.send_photo(
        chat_id,
        media,
        caption=caption,
        reply_markup=markup,
        parse_mode="HTML",
    )
    _remember_file_id(screen, sent)
    return sent
