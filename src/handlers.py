import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot_notify import notify_payment_success
from cardlink import CardlinkError, create_bill, new_order_id
from config import config
from config_pool import get_pool_state, refresh_pool
from database import User, create_user, get_all_users, get_user, get_user_count
from happ_crypto import encrypt_subscription_url
from payments import (
    create_pending_order,
    get_plan,
    is_subscription_active,
    try_activate_from_bill,
)
import ui

logger = logging.getLogger(__name__)
router = Router()

USERS_PAGE_SIZE = 20


def _is_admin(user: User | None, chat_id: int) -> bool:
    return chat_id in config.ADMINS or bool(user and user.is_admin)


async def _edit_or_answer(
    target: Message,
    text: str,
    markup,
    *,
    edit: bool,
) -> None:
    if edit:
        await target.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=markup, parse_mode="HTML")


async def show_menu(bot: Bot, chat_id: int, message_id: int | None = None) -> None:
    user = await get_user(chat_id)
    if not user:
        return

    text = ui.screen_home(user, is_admin=_is_admin(user, chat_id))
    markup = ui.kb_home(is_admin=_is_admin(user, chat_id))
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


async def send_subscription_key(target: Message, user: User, *, edit: bool = False) -> None:
    if config.payments_active and not _is_admin(user, user.telegram_id):
        if not is_subscription_active(user):
            await _edit_or_answer(
                target,
                ui.screen_access_inactive(),
                ui.kb_access(inactive=True),
                edit=edit,
            )
            return

    pool = get_pool_state()
    if not pool.configs:
        await _edit_or_answer(
            target,
            ui.screen_access_loading(),
            ui.kb_access(),
            edit=edit,
        )
        return

    sub_url = config.subscription_url_for_token(user.subscription_token)
    import_url = await encrypt_subscription_url(sub_url)
    await _edit_or_answer(
        target,
        ui.screen_access(user, import_url),
        ui.kb_access(),
        edit=edit,
    )


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
    await send_subscription_key(message, user, edit=False)


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await message.answer(ui.screen_help(), reply_markup=ui.kb_help(), parse_mode="HTML")


@router.callback_query(F.data == "get_key")
async def get_key_callback(callback: CallbackQuery) -> None:
    await callback.answer("Готовим доступ…")
    user = await get_user(callback.from_user.id)
    if not user:
        return
    await send_subscription_key(callback.message, user, edit=True)


@router.callback_query(F.data == "help")
async def help_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        ui.screen_help(),
        reply_markup=ui.kb_help(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "tariffs")
async def tariffs_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        ui.screen_tariffs(),
        reply_markup=ui.kb_tariffs(),
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
        ui.screen_order(plan),
        reply_markup=ui.kb_order(plan_id),
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
            ui.screen_pay_error(),
            reply_markup=ui.kb_order(plan_id),
            parse_mode="HTML",
        )
        return

    await create_pending_order(
        order_id=order_id,
        telegram_id=user.telegram_id,
        plan_id=plan_id,
        amount=plan.price_rub,
        bill_id=bill["bill_id"],
    )

    await callback.message.edit_text(
        ui.screen_pay(plan),
        reply_markup=ui.kb_pay(bill["link_page_url"], bill["bill_id"]),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("check:"))
async def check_payment_callback(callback: CallbackQuery) -> None:
    bill_id = callback.data.split(":", 1)[1]
    user, plan, activated = await try_activate_from_bill(bill_id)

    if activated and user and plan:
        await callback.answer("Оплата подтверждена", show_alert=True)
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
    await callback.message.edit_text(
        ui.screen_admin(
            users=total_users,
            sub_count=pool.subscription_count,
            limit=config.SUBSCRIPTION_CONFIG_LIMIT,
            primary=pool.primary_count,
            fill=pool.fill_count,
        ),
        reply_markup=ui.kb_admin(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_refresh")
async def admin_refresh_callback(callback: CallbackQuery) -> None:
    if callback.from_user.id not in config.ADMINS:
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    await callback.answer("Обновляю…")
    await callback.message.edit_text("Обновление данных…")
    await refresh_pool(force=True)
    pool = get_pool_state()
    await callback.message.edit_text(
        ui.screen_admin_refresh(
            sub_count=pool.subscription_count,
            limit=config.SUBSCRIPTION_CONFIG_LIMIT,
            primary=pool.primary_count,
            fill=pool.fill_count,
        ),
        reply_markup=ui.kb_admin_back(),
        parse_mode="HTML",
    )


async def _show_admin_users(callback: CallbackQuery, page: int = 0) -> None:
    users = await get_all_users()
    total = len(users)
    if total == 0:
        await callback.message.edit_text(
            "<b>Пользователи</b>\n\nСписок пуст.",
            reply_markup=ui.kb_admin_back(),
            parse_mode="HTML",
        )
        return

    pages = max(1, (total + USERS_PAGE_SIZE - 1) // USERS_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    start = page * USERS_PAGE_SIZE
    chunk = users[start : start + USERS_PAGE_SIZE]

    lines = [
        f"<b>Пользователи · {total}</b>",
        f"стр. {page + 1}/{pages}",
        "",
        ui.DIV,
    ]
    for idx, user in enumerate(chunk, start=start + 1):
        username = f"@{user.username}" if user.username else "—"
        access = ui.format_access_until(user)
        lines.append(
            f"<b>{idx}.</b> <code>{user.telegram_id}</code>\n"
            f"{ui._esc(user.full_name or '—')} · {ui._esc(username)}\n"
            f"<i>{ui._esc(access)}</i>"
        )
        lines.append("")
    lines.append(ui.DIV)

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=ui.kb_admin_users(page=page, pages=pages),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_users")
@router.callback_query(F.data.startswith("admin_users:"))
async def admin_users_callback(callback: CallbackQuery) -> None:
    if callback.from_user.id not in config.ADMINS:
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    page = 0
    if callback.data and callback.data.startswith("admin_users:"):
        try:
            page = int(callback.data.split(":", 1)[1])
        except ValueError:
            page = 0

    await callback.answer()
    await _show_admin_users(callback, page)


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer()
    await show_menu(bot, callback.from_user.id, callback.message.message_id)


def setup_handlers(dp: Dispatcher) -> None:
    dp.include_router(router)
