import html
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config
from config_pool import get_pool_state, refresh_pool
from database import User, create_user, get_all_users, get_user, get_user_count
from happ_crypto import encrypt_subscription_url

logger = logging.getLogger(__name__)
router = Router()


def _is_admin(user: User | None, chat_id: int) -> bool:
    return chat_id in config.ADMINS or bool(user and user.is_admin)


def _main_keyboard(user: User, chat_id: int) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="Мой ключ", callback_data="get_key")
    builder.button(text="Инструкция", callback_data="help")
    if _is_admin(user, chat_id):
        builder.button(text="Админ", callback_data="admin_menu")
    builder.adjust(1)
    return builder


async def show_menu(bot: Bot, chat_id: int, message_id: int | None = None) -> None:
    user = await get_user(chat_id)
    if not user:
        return

    text = (
        f"<b>{html.escape(config.BOT_NAME)}</b>\n"
        f"Обход белых списков · Happ"
    )

    markup = _main_keyboard(user, chat_id).as_markup()
    if message_id:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=markup,
            parse_mode="HTML",
        )
    else:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=markup,
            parse_mode="HTML",
        )


async def send_subscription_key(target: Message, user: User) -> None:
    pool = get_pool_state()
    if not pool.configs:
        await target.answer("Конфиги загружаются. Попробуйте через минуту.")
        return

    sub_url = config.subscription_url_for_token(user.subscription_token)
    import_url = await encrypt_subscription_url(sub_url)

    text = (
        f"<b>Ваша подписка</b>\n\n"
        f"<code>{html.escape(import_url)}</code>\n\n"
        f"Happ → + → вставить из буфера → автообновление вкл"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="← Меню", callback_data="back_to_menu")
    await target.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.message(Command("start"))
async def start_cmd(message: Message, bot: Bot) -> None:
    if not await get_user(message.from_user.id):
        await create_user(
            telegram_id=message.from_user.id,
            full_name=message.from_user.full_name or "User",
            username=message.from_user.username,
            is_admin=message.from_user.id in config.ADMINS,
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
        await message.answer("Нажмите /start")
        return
    await send_subscription_key(message, user)


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await _send_help(message)


async def _send_help(target: Message) -> None:
    text = (
        f"<b>{html.escape(config.BOT_NAME)}</b>\n\n"
        "1. Получите ключ в боте\n"
        "2. Happ → + → подписка по ссылке\n"
        "3. Включите автообновление\n\n"
        "Используйте на мобильном интернете с белыми списками."
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="Мой ключ", callback_data="get_key")
    builder.button(text="← Меню", callback_data="back_to_menu")
    builder.adjust(1)
    await target.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "get_key")
async def get_key_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_user(callback.from_user.id)
    if not user:
        return
    await send_subscription_key(callback.message, user)


@router.callback_query(F.data == "help")
async def help_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await _send_help(callback.message)


@router.callback_query(F.data == "admin_menu")
async def admin_menu_callback(callback: CallbackQuery) -> None:
    user = await get_user(callback.from_user.id)
    if not _is_admin(user, callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    await callback.answer()
    pool = get_pool_state()
    total_users = await get_user_count()
    text = (
        f"<b>Админ</b>\n\n"
        f"Пользователей: <b>{total_users}</b>\n"
        f"Конфигов в ключе: {pool.subscription_count}"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="Обновить конфиги", callback_data="admin_refresh")
    builder.button(text="Список пользователей", callback_data="admin_users")
    builder.button(text="← Меню", callback_data="back_to_menu")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "admin_refresh")
async def admin_refresh_callback(callback: CallbackQuery) -> None:
    if callback.from_user.id not in config.ADMINS:
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    await callback.answer("Обновляю…")
    await callback.message.edit_text("Загрузка конфигов…")
    await refresh_pool(force=True)
    pool = get_pool_state()
    text = f"Готово\n\nКонфигов в ключе: {pool.subscription_count}"
    builder = InlineKeyboardBuilder()
    builder.button(text="← Админ", callback_data="admin_menu")
    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "admin_users")
async def admin_users_callback(callback: CallbackQuery) -> None:
    if callback.from_user.id not in config.ADMINS:
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    await callback.answer()
    users = await get_all_users()
    lines = [f"<b>Пользователи ({len(users)})</b>\n"]
    for user in users[:30]:
        username = f"@{user.username}" if user.username else "—"
        lines.append(
            f"• <code>{user.telegram_id}</code> "
            f"{html.escape(user.full_name or '—')} ({html.escape(username)})"
        )
    if len(users) > 30:
        lines.append(f"\n… ещё {len(users) - 30}")

    builder = InlineKeyboardBuilder()
    builder.button(text="← Админ", callback_data="admin_menu")
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer()
    await show_menu(bot, callback.from_user.id, callback.message.message_id)


def setup_handlers(dp: Dispatcher) -> None:
    dp.include_router(router)
