import html
import io
import json
import logging
from datetime import datetime, timezone

import qrcode
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bypass_source import assign_bootstrap_bypass, is_probed_bypass
from config import config
from config_pool import get_pool_state, refresh_pool
from database import (
    User,
    create_user,
    get_all_users,
    get_personal_bypass_uris,
    get_user,
    get_user_count,
)

logger = logging.getLogger(__name__)
router = Router()


def _miniapp_keyboard(button_text: str = "📱 Уточнить на мобильном"):
    builder = InlineKeyboardBuilder()
    builder.button(
        text=button_text,
        web_app=WebAppInfo(url=config.miniapp_url),
    )
    return builder.as_markup()


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
        f"**Конфигов в пуле:** {total_hint}\n"
        f"**Обычный VPN:** `{regular}`\n"
        f"**Обходы в пуле:** `{whitelist}`"
        + (" (все из источника)\n" if config.WHITELIST_INCLUDE_ALL else "\n")
        + f"**Обновлено:** `{updated}`"
    )


async def show_menu(bot: Bot, chat_id: int, message_id: int | None = None) -> None:
    user = await get_user(chat_id)
    if not user:
        return

    personal_count = len(get_personal_bypass_uris(user))
    if personal_count:
        kind = "с мобильного" if is_probed_bypass(user) else "стартовый"
        personal_hint = f"\n**Ваш ключ:** `{personal_count}` обходов ({kind})\n"
    else:
        personal_hint = "\n**Ключ:** ещё не получен\n"

    text = (
        f"**{config.BOT_NAME}** — обход белых списков\n\n"
        f"**Ваш ID:** `{user.telegram_id}`\n"
        f"{personal_hint}\n"
        f"{_format_pool_stats()}\n\n"
        "**«Получить ключ»** — сразу **7 стартовых обходов** для Happ "
        "(получите на Wi‑Fi с VPN, затем пробуйте на мобильном).\n\n"
        "**«Уточнить на мобильном»** — когда уже есть интернет через Happ, "
        "подберём до **7** обходов с проверкой с вашего телефона."
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🔑 Получить ключ", callback_data="get_key")
    if personal_count:
        builder.button(text="📋 Мой ключ Happ", callback_data="show_personal_key")
    builder.button(text="📱 Уточнить на мобильном", callback_data="refine_bypass")
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


async def deliver_bootstrap_key(target: Message, user: User) -> None:
    """Выдаёт или обновляет стартовый набор из 7 обходов."""
    await assign_bootstrap_bypass(user.telegram_id)
    user = await get_user(user.telegram_id)
    if not user:
        return
    await send_personal_key_message(target, user, is_bootstrap=True)


async def send_personal_key_message(
    target: Message,
    user: User,
    *,
    is_update: bool = False,
    is_bootstrap: bool = False,
) -> None:
    uris = get_personal_bypass_uris(user)
    if not uris:
        await target.answer(
            "Не удалось загрузить обходы. Попробуйте через минуту.",
            parse_mode="Markdown",
        )
        return

    sub_url = config.personal_subscription_url_for_token(user.subscription_token)
    probed = is_probed_bypass(user) and not is_bootstrap

    qr = qrcode.QRCode(version=1, box_size=8, border=4)
    qr.add_data(sub_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    photo = BufferedInputFile(buffer.getvalue(), filename="tsulovpn-personal-qr.png")

    if probed:
        title = "обновлён" if is_update else "готов"
        desc = (
            f"В подписке **{len(uris)}** обходов — проверены **с вашего телефона** "
            f"на мобильном интернете."
        )
    else:
        title = "стартовый"
        desc = (
            f"В подписке **{len(uris)}** стартовых обходов (лучшие из базы).\n\n"
            "**Сейчас вы на Wi‑Fi?** Добавьте ссылку в Happ **с включённым VPN** "
            "(иначе Telegram и подписка могут не открыться).\n\n"
            "Затем на **мобильном** (без Wi‑Fi) перебирайте серверы «Обход» "
            "или нажмите **«Уточнить на мобильном»** в боте."
        )

    caption = (
        f"**{config.BOT_NAME}** — ключ {title}\n\n"
        f"🔗 **Ссылка для Happ / Hiddify:**\n`{sub_url}`\n\n"
        f"{desc}\n\n"
        "**Как использовать:**\n"
        "1. Скопируйте ссылку или отсканируйте QR\n"
        "2. В Happ: **Новый профиль → Добавить по ссылке**\n"
        "3. На мобильном интернете — серверы **TsuloVPN · Обход #N**"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="📱 Уточнить на мобильном", callback_data="refine_bypass")
    builder.button(text="🔑 Обновить стартовый ключ", callback_data="refresh_bootstrap")
    builder.button(text="⬅️ В меню", callback_data="back_to_menu")
    builder.adjust(1)

    await target.answer_photo(
        photo=photo,
        caption=caption,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown",
    )


async def prompt_miniapp(target: Message) -> None:
    text = (
        "**Уточнить обход на мобильном**\n\n"
        "⚠️ **Сначала** получите стартовый ключ и подключите **любой** обход в Happ — "
        "иначе интернета не будет и проверка не запустится.\n\n"
        "**Порядок:**\n"
        "1. Wi‑Fi + VPN → **«Получить ключ»** → добавить в Happ\n"
        "2. Мобильный интернет (Wi‑Fi выкл.) → подключить обход в Happ\n"
        "3. Когда интернет есть → откройте Mini App ниже\n"
        "4. Дождитесь проверки (1–2 мин, до **7** обходов)\n\n"
        "⏳ Не закрывайте Mini App до завершения."
    )
    await target.answer(
        text,
        reply_markup=_miniapp_keyboard("📱 Открыть проверку"),
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
            "Стартовый ключ для Happ — сразу. Уточнение под ваш оператор — с телефона.",
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
    await deliver_bootstrap_key(message, user)


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await _send_help(message)


@router.message(F.web_app_data)
async def web_app_data_handler(message: Message) -> None:
    user = await get_user(message.from_user.id)
    if not user:
        return
    try:
        data = json.loads(message.web_app_data.data)
    except json.JSONDecodeError:
        data = {}

    if data.get("ok"):
        count = data.get("count", len(get_personal_bypass_uris(user)))
        await message.answer(
            f"✅ Уточнение завершено! Найдено **{count}** обходов с вашего телефона.",
            parse_mode="Markdown",
        )
        await send_personal_key_message(message, user, is_update=True)
    else:
        await message.answer("Подбор не завершён. Попробуйте снова.")


async def _send_help(target: Message) -> None:
    text = (
        f"**Как подключить {config.BOT_NAME}**\n\n"
        "**Шаг 1 — Стартовый ключ (Wi‑Fi + VPN):**\n"
        "1. Включите VPN (для Telegram в РФ)\n"
        "2. **«Получить ключ»** → 7 стартовых обходов\n"
        "3. Добавьте ссылку в Happ / Hiddify\n\n"
        "**Шаг 2 — Мобильный интернет:**\n"
        "1. Отключите Wi‑Fi, включите мобильные данные\n"
        "2. В Happ перебирайте **TsuloVPN · Обход #1…#7**\n\n"
        "**Шаг 3 — Уточнение (опционально):**\n"
        "Когда любой обход уже даёт интернет → "
        "**«Уточнить на мобильном»** → Mini App подберёт до 7 лучших "
        "именно для вашего оператора.\n\n"
        "Если обходы перестали работать — **«Обновить стартовый ключ»** "
        "или **«Уточнить на мобильном»**."
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ В меню", callback_data="back_to_menu")
    await target.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(F.data == "get_key")
async def get_key_callback(callback: CallbackQuery) -> None:
    await callback.answer("Готовлю ключ...")
    user = await get_user(callback.from_user.id)
    if not user:
        return
    if callback.message.photo:
        await callback.message.delete()
    await deliver_bootstrap_key(callback.message, user)


@router.callback_query(F.data == "refresh_bootstrap")
async def refresh_bootstrap_callback(callback: CallbackQuery) -> None:
    await callback.answer("Обновляю стартовый ключ...")
    user = await get_user(callback.from_user.id)
    if not user:
        return
    if callback.message.photo:
        await callback.message.delete()
    await deliver_bootstrap_key(callback.message, user)


@router.callback_query(F.data == "refine_bypass")
async def refine_bypass_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message.photo:
        await callback.message.delete()
    await prompt_miniapp(callback.message)


@router.callback_query(F.data == "show_personal_key")
async def show_personal_key_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_user(callback.from_user.id)
    if not user:
        return
    if callback.message.photo:
        await callback.message.delete()
    await send_personal_key_message(callback.message, user)


@router.callback_query(F.data == "user_refresh")
async def user_refresh_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    text = (
        "**Обновить пул серверов?**\n\n"
        "Будет загружен свежий список из источника.\n\n"
        "⏳ **Ожидание: 1–2 минуты.**\n\n"
        "Ваш персональный ключ обходов **не изменится** — "
        "для нового подбора используйте **«Подобрать новый обход»**.\n\n"
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
    await callback.answer("Обновляю...")
    await callback.message.edit_text(
        "⏳ Обновляю пул серверов. Подождите 1–2 минуты...",
        parse_mode="Markdown",
    )
    await refresh_pool(force=True)
    text = f"✅ **Пул обновлён**\n\n{_format_pool_stats()}"
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ В меню", callback_data="back_to_menu")
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

    await callback.answer("Обновляю...")
    await callback.message.edit_text("⏳ Проверяю серверы...")
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
        await callback.answer(
            "Ссылка в сообщении выше — нажмите и удерживайте для копирования",
            show_alert=True,
        )
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
        bypass_n = len(get_personal_bypass_uris(user))
        lines.append(
            f"• <code>{user.telegram_id}</code> {safe_name} ({safe_username}) — обходов: {bypass_n}"
        )
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
