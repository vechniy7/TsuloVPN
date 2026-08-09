import html
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot_notify import notify_payment_success
from cardlink import CardlinkError, create_bill, new_order_id
from config import config
from config_pool import get_pool_state, refresh_pool
from database import User, create_user, get_all_users, get_user, get_user_count
from happ_crypto import encrypt_subscription_url
from payments import (
    PLANS,
    create_pending_order,
    format_access_until,
    format_order_text,
    format_tariffs_text,
    get_plan,
    is_subscription_active,
    try_activate_from_bill,
)

logger = logging.getLogger(__name__)
router = Router()


def _is_admin(user: User | None, chat_id: int) -> bool:
    return chat_id in config.ADMINS or bool(user and user.is_admin)


def _main_keyboard(user: User, chat_id: int) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="Мой доступ", callback_data="get_key")
    builder.button(text="Тарифы", callback_data="tariffs")
    builder.button(text="Справка", callback_data="help")
    if _is_admin(user, chat_id):
        builder.button(text="Админ", callback_data="admin_menu")
    builder.adjust(1)
    return builder


def _tariffs_keyboard() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for plan in PLANS.values():
        builder.button(
            text=f"{plan.title} — {plan.price_rub} ₽",
            callback_data=f"order:{plan.id}",
        )
    builder.button(text="← Меню", callback_data="back_to_menu")
    builder.adjust(1)
    return builder


def _order_keyboard(plan_id: str) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="Оплатить", callback_data=f"pay:{plan_id}")
    builder.button(text="← Тарифы", callback_data="tariffs")
    builder.adjust(1)
    return builder


async def show_menu(bot: Bot, chat_id: int, message_id: int | None = None) -> None:
    user = await get_user(chat_id)
    if not user:
        return

    text = (
        f"<b>{html.escape(config.BOT_NAME)}</b>\n"
        f"Цифровая подписка на IT-сервис\n\n"
        f"Статус: {format_access_until(user)}"
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
    if config.payments_active and not _is_admin(user, user.telegram_id):
        if not is_subscription_active(user):
            text = (
                "<b>Доступ не активен</b>\n\n"
                "Оформите подписку в разделе «Тарифы»."
            )
            builder = InlineKeyboardBuilder()
            builder.button(text="Тарифы", callback_data="tariffs")
            builder.button(text="← Меню", callback_data="back_to_menu")
            builder.adjust(1)
            await target.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
            return

    pool = get_pool_state()
    if not pool.configs:
        await target.answer("Данные загружаются. Попробуйте через минуту.")
        return

    sub_url = config.subscription_url_for_token(user.subscription_token)
    import_url = await encrypt_subscription_url(sub_url)

    text = (
        f"<b>Ваш доступ</b>\n\n"
        f"<code>{html.escape(import_url)}</code>\n\n"
        f"Скопируйте ссылку и добавьте её в приложение-клиент.\n"
        f"Включите автообновление подписки."
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
        "1. Получите ссылку доступа в боте\n"
        "2. Откройте приложение-клиент и добавьте подписку по ссылке\n"
        "3. Включите автообновление\n\n"
        "Поддержка: напишите администратору через бота."
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="Мой доступ", callback_data="get_key")
    builder.button(text="Тарифы", callback_data="tariffs")
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


@router.callback_query(F.data == "tariffs")
async def tariffs_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        format_tariffs_text(),
        reply_markup=_tariffs_keyboard().as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("order:"))
async def order_callback(callback: CallbackQuery) -> None:
    plan_id = callback.data.split(":", 1)[1]
    plan = get_plan(plan_id)
    if not plan:
        await callback.answer("Тариф не найден", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text(
        format_order_text(plan),
        reply_markup=_order_keyboard(plan_id).as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("pay:"))
async def pay_callback(callback: CallbackQuery) -> None:
    plan_id = callback.data.split(":", 1)[1]
    plan = get_plan(plan_id)
    if not plan:
        await callback.answer("Тариф не найден", show_alert=True)
        return

    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Нажмите /start", show_alert=True)
        return

    if not config.use_cardlink:
        await callback.answer(
            "Оплата не настроена. Добавьте CARDLINK_API_TOKEN и CARDLINK_SHOP_ID.",
            show_alert=True,
        )
        return

    await callback.answer("Создаю счёт…")

    order_id = new_order_id(user.telegram_id, plan_id)
    description = f"Цифровая подписка · {plan.title}"

    try:
        bill = await create_bill(
            amount=plan.price_rub,
            order_id=order_id,
            description=description,
            telegram_id=user.telegram_id,
            plan_id=plan_id,
            username=user.username,
        )
    except CardlinkError as exc:
        logger.error("Cardlink create bill failed: %s", exc)
        await callback.message.edit_text(
            "Не удалось создать счёт. Попробуйте позже или напишите администратору.",
            reply_markup=_order_keyboard(plan_id).as_markup(),
        )
        return

    await create_pending_order(
        order_id=order_id,
        telegram_id=user.telegram_id,
        plan_id=plan_id,
        amount=plan.price_rub,
        bill_id=bill["bill_id"],
    )

    text = (
        f"<b>Оплата заказа</b>\n\n"
        f"Тариф: {html.escape(plan.title)}\n"
        f"Сумма: <b>{plan.price_rub} ₽</b>\n\n"
        f"Нажмите «Перейти к оплате», завершите платёж и вернитесь в бот.\n"
        f"Доступ активируется автоматически."
    )
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Перейти к оплате", url=bill["link_page_url"]),
    )
    builder.button(text="Проверить оплату", callback_data=f"check:{bill['bill_id']}")
    builder.button(text="← Тарифы", callback_data="tariffs")
    builder.adjust(1)

    await callback.message.edit_text(
        text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("check:"))
async def check_payment_callback(callback: CallbackQuery) -> None:
    bill_id = callback.data.split(":", 1)[1]
    user, plan, activated = await try_activate_from_bill(bill_id)

    if activated and user and plan:
        await callback.answer("Оплата подтверждена!", show_alert=True)
        await notify_payment_success(callback.from_user.id, plan.title, user)
        return

    if user and plan and is_subscription_active(user):
        await callback.answer("Подписка уже активна", show_alert=True)
        return

    await callback.answer(
        "Оплата пока не поступила. Подождите минуту и нажмите снова.",
        show_alert=True,
    )


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
        f"В ключе: <b>{pool.subscription_count}</b> / {config.SUBSCRIPTION_CONFIG_LIMIT}\n"
        f"Основной: {pool.primary_count} · Дополнение: {pool.fill_count}"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="Обновить данные", callback_data="admin_refresh")
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
    await callback.message.edit_text("Загрузка…")
    await refresh_pool(force=True)
    pool = get_pool_state()
    text = (
        f"Готово\n\n"
        f"В ключе: {pool.subscription_count} / {config.SUBSCRIPTION_CONFIG_LIMIT}\n"
        f"Основной: {pool.primary_count} · Дополнение: {pool.fill_count}"
    )
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
