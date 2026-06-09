import html
import io
import logging
from datetime import datetime, timezone

import qrcode
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config
from config_pool import get_pool_state, refresh_pool
from database import Session, User, create_user, get_all_users, get_user, get_user_count

logger = logging.getLogger(__name__)
router = Router()


def _format_pool_stats() -> str:
    pool = get_pool_state()
    regular = sum(1 for item in pool.configs if item.category == "regular")
    whitelist = sum(1 for item in pool.configs if item.category == "whitelist")

    if pool.last_refresh_at:
        updated = datetime.fromtimestamp(pool.last_refresh_at, tz=timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    else:
        updated = "ещё не обновлялся"

    verified = pool.last_verify_alive or len(pool.configs)
    total_hint = f"`{len(pool.configs)}`" if config.WHITELIST_INCLUDE_ALL else f"`{verified}` / `{config.target_total_count}`"
    return (
        f"**Конфигов в подписке:** {total_hint}\n"
        f"**Обычный VPN (чёрные списки):** `{regular}`\n"
        f"**Обход белых списков:** `{whitelist}`"
        + (" (все из источника)\n" if config.WHITELIST_INCLUDE_ALL else "\n")
        + f"**Проверка при обновлении:** `{'вкл' if config.VERIFY_ON_SUBSCRIBE and not config.SKIP_HEALTH_CHECK else 'выкл'}`\n"
        f"**Обновлено:** `{updated}`"
    )


async def show_menu(bot: Bot, chat_id: int, message_id: int | None = None) -> None:
    user = await get_user(chat_id)
    if not user:
        return

    sub_url = config.subscription_url_for_token(user.subscription_token)
    text = (
        f"**{config.BOT_NAME}** — бесплатные VPN-ключи\n\n"
        f"**Ваш ID:** `{user.telegram_id}`\n\n"
        f"{_format_pool_stats()}\n\n"
        "Нажмите **«Получить ключ»**, чтобы получить ссылку подписки для Hiddify / Happ / v2rayNG."
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🔑 Получить ключ", callback_data="get_key")
    builder.button(text="🔄 Проверить серверы", callback_data="user_refresh")
    builder.button(text="📊 Статус серверов", callback_data="pool_status")
    builder.button(text="ℹ️ Как подключить", callback_data="help")
    if user.is_admin or chat_id in config.ADMINS:
        builder.button(text="⚙️ Админ", callback_data="admin_menu")
    builder.adjust(1)

    markup = builder.as_markup()
    if message_id:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=markup,
            parse_mode="Markdown",
        )
    else:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, parse_mode="Markdown")


async def send_subscription_key(target: Message, user: User) -> None:
    sub_url = config.subscription_url_for_token(user.subscription_token)
    pool = get_pool_state()

    if not pool.configs:
        await target.answer(
            "⏳ Список серверов ещё проверяется. Подождите 1–2 минуты и нажмите снова.",
        )
        return

    qr = qrcode.QRCode(version=1, box_size=8, border=4)
    qr.add_data(sub_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    photo = BufferedInputFile(buffer.getvalue(), filename="tsulovpn-qr.png")

    regular = sum(1 for item in pool.configs if item.category == "regular")
    whitelist = sum(1 for item in pool.configs if item.category == "whitelist")

    caption = (
        f"**{config.BOT_NAME}** — ваша подписка\n\n"
        f"🔗 **Ссылка для Hiddify / Happ:**\n`{sub_url}`\n\n"
        f"В подписке сейчас **{len(pool.configs)}** рабочих серверов:\n"
        f"• Обычные VPN: **{regular}**\n"
        f"• Обход белых списков: **{whitelist}**\n\n"
        "**Как использовать:**\n"
        "1. Скопируйте ссылку или отсканируйте QR\n"
        "2. В Hiddify / Happ: **Новый профиль → Добавить по ссылке**\n"
        "3. Включите автообновление подписки в приложении\n\n"
        "При каждом обновлении подписки в Happ мёртвые серверы отсекаются — "
        "остаются только те, что отвечают на проверку."
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Скопировать ссылку", callback_data="copy_hint")
    builder.button(text="⬅️ В меню", callback_data="back_to_menu")
    builder.adjust(1)

    await target.answer_photo(
        photo=photo,
        caption=caption,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )


@router.message(Command("start"))
async def start_cmd(message: Message, bot: Bot) -> None:
    user = await get_user(message.from_user.id)
    if not user:
        is_admin = message.from_user.id in config.ADMINS
        user = await create_user(
            telegram_id=message.from_user.id,
            full_name=message.from_user.full_name or "User",
            username=message.from_user.username,
            is_admin=is_admin,
        )
        await message.answer(
            f"Добро пожаловать в **{config.BOT_NAME}**!\n\n"
            "Бесплатные VPN-ключи из проверенных источников. "
            "Список обновляется автоматически — в приложении всегда только рабочие серверы.",
            parse_mode="Markdown",
        )

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
        await message.answer("Сначала нажмите /start")
        return
    await send_subscription_key(message, user)


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await _send_help(message)


async def _send_help(target: Message) -> None:
    text = (
        f"**Как подключить {config.BOT_NAME}**\n\n"
        "**Android / iOS / Windows / macOS:**\n"
        "• **Hiddify** — рекомендуется\n"
        "• **Happ** (Happ Proxy)\n"
        "• v2rayNG, V2Box, Throne\n\n"
        "**Шаги:**\n"
        "1. Получите ссылку подписки в боте (кнопка «Получить ключ»)\n"
        "2. В приложении: **Добавить подписку по URL**\n"
        "3. Включите **автообновление** подписки\n"
        "4. Выберите сервер с минимальным пингом\n\n"
        "**Зачем обход белых списков?**\n"
        "Когда мобильный интернет (Мегафон, МТС и др.) заблокирован и работают "
        "только сайты из «белого списка» (Яндекс, VK, X5) — обычный VPN не подключится. "
        "Конфиги «БС» маскируют трафик под разрешённые сайты.\n\n"
        "**TsuloVPN · Сервер #N** — обычный интернет (WiFi / без блокировок)\n"
        "**TsuloVPN · Обход #N** — обход белых списков на мобильном\n\n"
        "На мобильном интернете подключайтесь **только к серверам «БС»**.\n"
        "После добавления подписки нажмите **обновить** в Happ — "
        "в списке останутся только серверы, прошедшие проверку.\n"
        f"Полное обновление пула — каждые ~{config.POOL_REFRESH_INTERVAL // 60} мин."
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ В меню", callback_data="back_to_menu")
    await target.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(F.data == "get_key")
async def get_key_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_user(callback.from_user.id)
    if not user:
        return
    await send_subscription_key(callback.message, user)


@router.callback_query(F.data == "user_refresh")
async def user_refresh_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    text = (
        "**Обновить список серверов?**\n\n"
        "Будет загружен свежий список VPN и обходов белых списков.\n\n"
        "⏳ **Ожидание: 1–2 минуты.** Не закрывайте бота до завершения.\n\n"
        "После обновления нажмите «Обновить» в Happ или добавьте подписку заново.\n\n"
        "Продолжить?"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да", callback_data="user_refresh_confirm")
    builder.button(text="❌ Нет", callback_data="user_refresh_cancel")
    builder.adjust(2)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(F.data == "user_refresh_cancel")
async def user_refresh_cancel_callback(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer("Отменено")
    await show_menu(bot, callback.from_user.id, callback.message.message_id)


@router.callback_query(F.data == "user_refresh_confirm")
async def user_refresh_confirm_callback(callback: CallbackQuery) -> None:
    await callback.answer("Обновляю список...")
    await callback.message.edit_text(
        "⏳ Скачиваю свежие обходы и обновляю список серверов.\n"
        "Это займёт **1–2 минуты** — пожалуйста, подождите...",
        parse_mode="Markdown",
    )
    await refresh_pool(force=True)
    text = (
        "✅ **Список обновлён**\n\n"
        f"{_format_pool_stats()}\n\n"
        "Теперь **обновите подписку в Happ** — появятся новые серверы."
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🔑 Получить ключ", callback_data="get_key")
    builder.button(text="⬅️ В меню", callback_data="back_to_menu")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(F.data == "pool_status")
async def pool_status_callback(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer()
    text = f"**Статус пула серверов**\n\n{_format_pool_stats()}"
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Обновить сейчас", callback_data="force_refresh")
    builder.button(text="⬅️ Назад", callback_data="back_to_menu")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(F.data == "force_refresh")
async def force_refresh_callback(callback: CallbackQuery) -> None:
    if callback.from_user.id not in config.ADMINS:
        user = await get_user(callback.from_user.id)
        if not user or not user.is_admin:
            await callback.answer("Только для администратора", show_alert=True)
            return

    await callback.answer("Обновляю список...")
    await callback.message.edit_text("⏳ Проверяю серверы, это может занять 1–3 минуты...")
    await refresh_pool(force=True)
    text = f"✅ **Список обновлён**\n\n{_format_pool_stats()}"
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ В меню", callback_data="back_to_menu")
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(F.data == "help")
async def help_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.delete()
    await _send_help(callback.message)


@router.callback_query(F.data == "copy_hint")
async def copy_hint_callback(callback: CallbackQuery) -> None:
    user = await get_user(callback.from_user.id)
    if user:
        sub_url = config.subscription_url_for_token(user.subscription_token)
        await callback.answer("Ссылка в сообщении выше — нажмите и удерживайте для копирования", show_alert=True)
    else:
        await callback.answer()


@router.callback_query(F.data == "admin_menu")
async def admin_menu_callback(callback: CallbackQuery) -> None:
    if callback.from_user.id not in config.ADMINS:
        user = await get_user(callback.from_user.id)
        if not user or not user.is_admin:
            await callback.answer("Доступ запрещён", show_alert=True)
            return

    await callback.answer()
    users_count = await get_user_count()
    text = (
        f"**Админ-панель {config.BOT_NAME}**\n\n"
        f"**Пользователей:** `{users_count}`\n\n"
        f"{_format_pool_stats()}"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Обновить пул", callback_data="force_refresh")
    builder.button(text="👥 Пользователи", callback_data="admin_users")
    builder.button(text="⬅️ Назад", callback_data="back_to_menu")
    builder.adjust(1)
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
        safe_name = html.escape(user.full_name or "—")
        safe_username = html.escape(username)
        lines.append(f"• <code>{user.telegram_id}</code> {safe_name} ({safe_username})")
    if len(users) > 30:
        lines.append(f"\n... и ещё {len(users) - 30}")

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Назад", callback_data="admin_menu")
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
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
