"""Отправка экранов бота: фото + подпись, без поломок edit_text/edit_caption."""

from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InputMediaPhoto, Message

logger = logging.getLogger(__name__)

PHOTO_DIR = Path(__file__).parent / "photo"
SCREEN_PHOTOS = {
    "home": PHOTO_DIR / "1vpn.PNG",
    "access": PHOTO_DIR / "2vpn.PNG",
    "help": PHOTO_DIR / "2vpn.PNG",
    "donate": PHOTO_DIR / "3vpn.PNG",
    "admin": PHOTO_DIR / "1vpn.PNG",
}
CAPTION_LIMIT = 1024

_file_ids: dict[str, str] = {}


def photo_path(screen: str) -> Path | None:
    path = SCREEN_PHOTOS.get(screen)
    if path and path.is_file():
        return path
    return None


def _media(screen: str):
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
    screen — ключ баннера (home/access/help/donate/admin) или None для текста.
    edit=True обновляет текущее сообщение; иначе отправляет новое.
    """
    caption = caption.strip()
    if screen and len(caption) > CAPTION_LIMIT:
        caption = caption[: CAPTION_LIMIT - 1].rstrip() + "…"

    media = _media(screen) if screen else None
    has_photo = bool(message.photo) if edit else False

    try:
        if edit and media is not None and has_photo:
            sent = await message.edit_media(
                InputMediaPhoto(media=media, caption=caption, parse_mode="HTML"),
                reply_markup=markup,
            )
            result = sent if isinstance(sent, Message) else message
            _remember_file_id(screen, result)
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
            _remember_file_id(screen, sent)
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
        if media is not None:
            try:
                sent = await message.answer_photo(
                    media,
                    caption=caption,
                    reply_markup=markup,
                    parse_mode="HTML",
                )
                _remember_file_id(screen, sent)
                return sent
            except Exception as inner:
                logger.warning("photo fallback failed: %s", inner)
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
    if len(caption) > CAPTION_LIMIT:
        caption = caption[: CAPTION_LIMIT - 1].rstrip() + "…"
    media = _media(screen)
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
