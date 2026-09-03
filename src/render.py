"""Отправка экранов бота: текст (баннеры временно отключены)."""

from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InputMediaPhoto, Message

logger = logging.getLogger(__name__)

PHOTO_DIR = Path(__file__).parent / "photo"
# Баннеры включены — фото из src/photo (как у типичных VPN-ботов).
USE_SCREEN_PHOTOS = True
SCREEN_PHOTOS = {
    "home": PHOTO_DIR / "1vpn.PNG",
    "access": PHOTO_DIR / "2vpn.PNG",
    "help": PHOTO_DIR / "2vpn.PNG",
    "tariffs": PHOTO_DIR / "3vpn.PNG",
    "docs": PHOTO_DIR / "3vpn.PNG",
    "channel": PHOTO_DIR / "1vpn.PNG",
    "donate": PHOTO_DIR / "3vpn.PNG",
    "admin": PHOTO_DIR / "1vpn.PNG",
}
CAPTION_LIMIT = 4096
PHOTO_CAPTION_LIMIT = 1024

_file_ids: dict[str, str] = {}


def photo_path(screen: str) -> Path | None:
    if not USE_SCREEN_PHOTOS:
        return None
    path = SCREEN_PHOTOS.get(screen)
    if path and path.is_file():
        return path
    return None


def _media(screen: str):
    if not USE_SCREEN_PHOTOS:
        return None
    file_id = _file_ids.get(screen)
    if file_id:
        return file_id
    path = photo_path(screen)
    if not path:
        return None
    return FSInputFile(path)


def _remember_file_id(screen: str, message: Message) -> None:
    if message.photo:
        _file_ids[screen] = message.photo[-1].file_id


async def render_screen(
    message: Message,
    *,
    caption: str,
    markup,
    screen: str | None,
    edit: bool,
) -> Message | None:
    """
    screen — ключ баннера или None.
    При USE_SCREEN_PHOTOS=False всегда текстовые сообщения (без пустых фото).
    """
    caption = caption.strip()
    media = _media(screen) if screen else None
    limit = PHOTO_CAPTION_LIMIT if media is not None else CAPTION_LIMIT
    if len(caption) > limit:
        caption = caption[: limit - 1].rstrip() + "…"

    has_photo = bool(message.photo) if edit else False

    try:
        # Старое сообщение с фото → переходим на текст: удаляем и шлём новое.
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
