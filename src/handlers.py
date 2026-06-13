import html
import io
import logging
from datetime import datetime, timezone

import qrcode
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config
from config_pool import get_pool_state, refresh_pool
from database import User, create_user, get_all_users, get_user, get_user_count

logger = logging.getLogger(__name__)
router = Router()


def _menu_keyboard(user: User, chat_id: int) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔑 Получить ключ", callback_data="get_key")
    builder.button(text="📱 О сервисе", web_app=WebAppInfo(url=config.miniapp_url))
    builder.button(text="ℹ️ Как подключить", callback_data="help")
    if user.is_admin or chat_id in config.ADMINS:
        builder.button(text="⚙️ Админ", callback_data="admin_menu")
    builder.adjust(1)
    return builder


async def show_menu(bot: Bot, chat_id: int, message_id: int | None = None) -> None:
    user = await get_user(chat_id)
    if not user:
        return

    pool = get_pool_state()
    if pool.last_refresh_at:
        updated = datetime.fromtimestamp(pool.last_refresh_at, tz=timezone.utc).strftime("%d.%m %H:%M")
    else:
        updated = "—"

    text = (
        f"**{config.BOT_NAME}**\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📱 Обход: `{pool.subscription_count}` в ключе · `{pool.source_total}` в источнике\n"
        f"🔄 Обновлено: `{updated}` UTC\n\n"
        f"Подписка для **Happ / Hiddify**.\n"
        f"Конфиги синхронизируются с igareck автоматически."
    )

    markup = _menu_keyboard(user, chat_id).as_markup()
    if message_id:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text=text, reply_markup=markup, parse_mode="Markdown",
        )
    else:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, parse_mode="Markdown")


async def send_subscription_key(target: Message, user: User) -> None:
    pool = get_pool_state()
    if not pool.configs:
        await target.answer("⏳ Загружаю конфиги, подождите минуту и нажмите снова.")
        return

    sub_url = config.subscription_url_for_token(user.subscription_token)

    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(sub_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    photo = BufferedInputFile(buffer.getvalue(), filename="tsulovpn-qr.png")

    caption = (
        f"**{config.BOT_NAME}** — ваша подписка\n\n"
        f"`{sub_url}`\n\n"
        f"📱 Серверов в ключе: **{pool.subscription_count}**\n"
        f"📦 В источнике: **{pool.source_total}** конфигов\n\n"
        f"**Happ / Hiddify** → добавить по ссылке → автообновление **вкл**\n\n"
        f"Серверы **Обход #N** — для мобильного интернета (белые списки)."
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Меню", callback_data="back_to_menu")
    await target.answer_photo(photo=photo, caption=caption, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.message(Command("start"))
async def start_cmd(message: Message, bot: Bot) -> None:
    if not await get_user(message.from_user.id):
        is_admin = message.from_user.id in config.ADMINS
        await create_user(
            telegram_id=message.from_user.id,
            full_name=message.from_user.full_name or "User",
            username=message.from_user.username,
            is_admin=is_admin,
        )
        await message.answer(f"Добро пожаловать в **{config.BOT_NAME}**!", parse_mode="Markdown")
    await show_menu(bot, message.from_user.id)


@router.message(Command("menu"))
async def menu_cmd(message: Message, bot: Bot) -> None:
    if not await get_user(message.from_user.id):
        await start_cmd(message, bot)
        return
    await show_menu(bot, message.from_user.id)


@router.message(Command("key", "connect"))
async def key_cmd(message: Message) -> None:
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Нажмите /start")
        return
    await send_subscription_key(message, user)


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await _send_help(message)


async def _send_help(target: Message) -> None:
    text = (
        f"**{config.BOT_NAME} — инструкция**\n\n"
        "**1.** Получите ключ в боте\n"
        "**2.** Happ → **+** → подписка по URL\n"
        "**3.** Включите **автообновление**\n\n"
        "**Мобильный интернет (белые списки)** → серверы **Обход #N**\n\n"
        "Подписка обновляется автоматически — при обновлении "
        "источника igareck конфиги заменятся в Happ."
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🔑 Получить ключ", callback_data="get_key")
    builder.button(text="⬅️ Меню", callback_data="back_to_menu")
    builder.adjust(1)
    await target.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(F.data == "get_key")
async def get_key_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_user(callback.from_user.id)
    if not user:
        return
    if callback.message.photo:
        await callback.message.delete()
    await send_subscription_key(callback.message, user)


@router.callback_query(F.data == "help")
async def help_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message.photo:
        await callback.message.delete()
    await _send_help(callback.message)


@router.callback_query(F.data == "admin_menu")
async def admin_menu_callback(callback: CallbackQuery) -> None:
    if callback.from_user.id not in config.ADMINS:
        user = await get_user(callback.from_user.id)
        if not user or not user.is_admin:
            await callback.answer("Доступ запрещён", show_alert=True)
            return

    await callback.answer()
    pool = get_pool_state()
    text = (
        f"**Админ · {config.BOT_NAME}**\n\n"
        f"👥 Пользователей: `{await get_user_count()}`\n"
        f"📱 В ключе: `{pool.subscription_count}` · в источнике: `{pool.source_total}`"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Обновить конфиги", callback_data="admin_refresh")
    builder.button(text="👥 Пользователи", callback_data="admin_users")
    builder.button(text="⬅️ Назад", callback_data="back_to_menu")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(F.data == "admin_refresh")
async def admin_refresh_callback(callback: CallbackQuery) -> None:
    if callback.from_user.id not in config.ADMINS:
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    await callback.answer("Обновляю...")
    await callback.message.edit_text("⏳ Загружаю конфиги из источников...")
    await refresh_pool(force=True)
    pool = get_pool_state()
    text = (
        f"✅ Готово\n\n"
        f"📱 В ключе: `{pool.subscription_count}` · в источнике: `{pool.source_total}`"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Админ", callback_data="admin_menu")
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(F.data == "admin_users")
async def admin_users_callback(callback: CallbackQuery) -> None:
    if callback.from_user.id not in config.ADMINS:
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    await callback.answer()
    users = await get_all_users()
    lines = [f"<b>Пользователи ({len(users)}):</b>\n"]
    for user in users[:30]:
        username = f"@{user.username}" if user.username else "—"
        lines.append(
            f"• <code>{user.telegram_id}</code> "
            f"{html.escape(user.full_name or '—')} ({html.escape(username)})"
        )
    if len(users) > 30:
        lines.append(f"\n... ещё {len(users) - 30}")

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Админ", callback_data="admin_menu")
    await callback.message.edit_text(
        "\n".join(lines), reply_markup=builder.as_markup(), parse_mode="HTML",
    )


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer()
    if callback.message.photo:
        await callback.message.delete()
        await show_menu(bot, callback.from_user.id)
    else:
        await show_menu(bot, callback.from_user.id, callback.message.message_id)


def setup_handlers(dp: Dispatcher) -> None:
    dp.include_router(router)
