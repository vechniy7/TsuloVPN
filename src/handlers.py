import logging
import time

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot_notify import notify_payment_success
from channel_gate import (
    CHECK_CALLBACK,
    is_channel_member,
    prompt_channel_subscription,
)
from config import config
from pool_engine_v3 import get_pool_state, refresh_pool
from database import User, create_user, get_all_users, get_user, get_user_count
from happ_crypto import bot_subscription_import_url
from payments import is_subscription_active, try_activate_from_bill
from render import CAPTION_LIMIT, render_screen, send_screen
import ui

logger = logging.getLogger(__name__)
router = Router()

USERS_PAGE_SIZE = 20
_last_admin_upstream_refresh_at: float = 0.0


def _is_admin(user: User | None, chat_id: int) -> bool:
    return chat_id in config.ADMINS or bool(user and user.is_admin)


async def show_menu(
    bot: Bot,
    chat_id: int,
    message: Message | None = None,
    *,
    edit: bool = False,
) -> None:
    user = await get_user(chat_id)
    if not user:
        return
    text = ui.screen_home(user, is_admin=_is_admin(user, chat_id))
    markup = ui.kb_home(is_admin=_is_admin(user, chat_id))
    if edit and message:
        await render_screen(message, caption=text, markup=markup, screen="home", edit=True)
        return
    await send_screen(bot, chat_id, caption=text, markup=markup, screen="home")


async def send_subscription_key(target: Message, user: User, *, edit: bool = False) -> None:
    if config.payments_active and not _is_admin(user, user.telegram_id):
        if not is_subscription_active(user):
            await render_screen(
                target,
                caption=ui.screen_access_inactive(),
                markup=ui.kb_access(inactive=True),
                screen="access",
                edit=edit,
            )
            return

    pool = get_pool_state()
    if not pool.configs and not pool.subscription_count:
        await render_screen(
            target,
            caption=ui.screen_access_loading(),
            markup=ui.kb_access(),
            screen="access",
            edit=edit,
        )
        return

    sub_url = config.subscription_url_for_token(user.subscription_token)
    import_url = await bot_subscription_import_url(sub_url)
    full = ui.screen_access(user, import_url)
    if len(full) <= CAPTION_LIMIT:
        await render_screen(
            target,
            caption=full,
            markup=ui.kb_access(),
            screen="access",
            edit=edit,
        )
        return

    await render_screen(
        target,
        caption=ui.screen_access_short(user),
        markup=ui.kb_access(),
        screen="access",
        edit=edit,
    )
    await target.answer(
        ui.screen_access_link(import_url),
        parse_mode="HTML",
        disable_web_page_preview=True,
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


@router.message(Command("key", "connect", "access"))
async def key_cmd(message: Message) -> None:
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Нажмите /start")
        return
    await send_subscription_key(message, user, edit=False)


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await render_screen(
        message,
        caption=ui.screen_help(),
        markup=ui.kb_help(),
        screen="help",
        edit=False,
    )


@router.message(Command("donate", "support"))
async def donate_cmd(message: Message) -> None:
    await render_screen(
        message,
        caption=ui.screen_donate(),
        markup=ui.kb_donate(),
        screen="donate",
        edit=False,
    )


@router.callback_query(F.data == "get_key")
async def get_key_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_user(callback.from_user.id)
    if not user:
        return
    await send_subscription_key(callback.message, user, edit=True)


@router.callback_query(F.data == "help")
async def help_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await render_screen(
        callback.message,
        caption=ui.screen_help(),
        markup=ui.kb_help(),
        screen="help",
        edit=True,
    )


@router.callback_query(F.data.in_({"donate", "tariffs"}))
async def donate_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await render_screen(
        callback.message,
        caption=ui.screen_donate(),
        markup=ui.kb_donate(),
        screen="donate",
        edit=True,
    )


@router.callback_query(F.data.startswith("order:"))
@router.callback_query(F.data.startswith("pay:"))
async def legacy_pay_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    await render_screen(
        callback.message,
        caption=ui.screen_donate(),
        markup=ui.kb_donate(),
        screen="donate",
        edit=True,
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
        "Касса отключена. Поддержать можно переводом на карту в «Поддержать».",
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
    sources_line = ", ".join(
        f"{name.split('.')[0][:18]}={n}" for name, n in pool.source_counts.items()
    )
    await render_screen(
        callback.message,
        caption=ui.screen_admin(
            users=total_users,
            sub_count=pool.subscription_count,
            limit=config.SUBSCRIPTION_CONFIG_LIMIT,
            primary=pool.primary_count,
            fill=pool.fill_count,
            source_total=pool.source_total,
            sources_line=sources_line,
            wifi_count=pool.wifi_count,
            lte_count=pool.lte_count,
            source_status=pool.source_status,
            source_key=config.source_label(),
            last_error=pool.last_error,
            source_real=pool.source_real_count,
        ),
        markup=ui.kb_admin(),
        screen="admin",
        edit=True,
    )


@router.callback_query(F.data == "admin_refresh")
async def admin_refresh_callback(callback: CallbackQuery) -> None:
    global _last_admin_upstream_refresh_at
    if callback.from_user.id not in config.ADMINS:
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    now = time.time()
    cooldown = config.ADMIN_FORCE_REFRESH_COOLDOWN_SEC
    if _last_admin_upstream_refresh_at and now - _last_admin_upstream_refresh_at < cooldown:
        wait_min = max(1, int((cooldown - (now - _last_admin_upstream_refresh_at) + 59) // 60))
        await callback.answer(
            f"Подождите ~{wait_min} мин — частое обновление бьёт по панели и повышает риск бана",
            show_alert=True,
        )
        return
    _last_admin_upstream_refresh_at = now
    await callback.answer("Обновляю…")
    await refresh_pool(force=True)
    pool = get_pool_state()
    sources_line = ", ".join(
        f"{name.split('.')[0][:18]}={n}" for name, n in pool.source_counts.items()
    )
    await render_screen(
        callback.message,
        caption=ui.screen_admin_refresh(
            sub_count=pool.subscription_count,
            limit=config.SUBSCRIPTION_CONFIG_LIMIT,
            primary=pool.primary_count,
            fill=pool.fill_count,
            source_total=pool.source_total,
            sources_line=sources_line,
            wifi_count=pool.wifi_count,
            lte_count=pool.lte_count,
            source_status=pool.source_status,
            source_key=config.source_label(),
            last_error=pool.last_error,
            source_real=pool.source_real_count,
        ),
        markup=ui.kb_admin_back(),
        screen="admin",
        edit=True,
    )


async def _show_admin_users(callback: CallbackQuery, page: int = 0) -> None:
    users = await get_all_users()
    total = len(users)
    if total == 0:
        await render_screen(
            callback.message,
            caption="<b>Пользователи</b>\n\nСписок пуст.",
            markup=ui.kb_admin_back(),
            screen=None,
            edit=True,
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

    await render_screen(
        callback.message,
        caption="\n".join(lines).strip(),
        markup=ui.kb_admin_users(page=page, pages=pages),
        screen=None,
        edit=True,
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
    await show_menu(bot, callback.from_user.id, callback.message, edit=True)


@router.callback_query(F.data == CHECK_CALLBACK)
async def check_channel_sub_callback(callback: CallbackQuery, bot: Bot) -> None:
    if callback.from_user.id in config.ADMINS:
        await callback.answer("Подписка подтверждена", show_alert=True)
        await show_menu(bot, callback.from_user.id, callback.message, edit=True)
        return

    if await is_channel_member(bot, callback.from_user.id):
        await callback.answer("Подписка подтверждена! Добро пожаловать.", show_alert=True)
        await show_menu(bot, callback.from_user.id, callback.message, edit=True)
        return

    await callback.answer(
        "Подписка не найдена. Подпишитесь на канал и нажмите «Проверить» снова.",
        show_alert=True,
    )
    if callback.message:
        await prompt_channel_subscription(callback.message, edit=True)


def setup_handlers(dp: Dispatcher) -> None:
    from channel_gate import ChannelGateMiddleware

    dp.update.outer_middleware(ChannelGateMiddleware())
    dp.include_router(router)
