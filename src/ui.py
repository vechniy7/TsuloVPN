"""Единый визуальный язык экранов Telegram-бота."""

from __future__ import annotations

import html

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config
from database import User
from payments import TariffPlan, is_subscription_active

DIV = "────────"


def _esc(value: str | None) -> str:
    return html.escape(value or "")


def _webapp_https() -> bool:
    return config.miniapp_url.lower().startswith("https://")


def status_info(user: User) -> tuple[str, str, bool]:
    """badge, detail, is_active — доступ всегда открыт, пока не включена оплата."""
    if not config.payments_active:
        return "открыт", "полный доступ · без ограничений", True
    if is_subscription_active(user):
        return "открыт", "полный доступ", True
    return "ожидает", "откройте доступ через поддержку", False


def format_access_until(user: User) -> str:
    badge, detail, active = status_info(user)
    if active:
        return "открыт"
    return detail


def kb_channel_required() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📢  Подписаться на канал", url=config.required_channel_url)
    b.button(text="✓  Проверить подписку", callback_data="check_channel_sub")
    b.adjust(1)
    return b.as_markup()


def screen_channel_required() -> str:
    channel = _esc(config.required_channel_id.lstrip("@") or "TsuloVPN")
    name = _esc(config.BOT_NAME)
    return (
        f"<b>Доступ к {name}</b>\n\n"
        f"Чтобы пользоваться ботом, подпишитесь на канал "
        f"<b>@{channel}</b> — там новости, обновления и полезные материалы.\n\n"
        f"<blockquote>1. Нажмите «Подписаться на канал»\n"
        f"2. Вернитесь сюда и нажмите «Проверить подписку»</blockquote>\n\n"
        f"Без подписки бот недоступен."
    )


def kb_home(*, is_admin: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✦  Мой доступ", callback_data="get_key")
    b.button(text="♡  Поддержать", callback_data="donate")
    b.button(text="▸  Подключение", callback_data="help")
    if _webapp_https():
        b.button(text="✧  Кабинет", web_app=WebAppInfo(url=config.miniapp_url))
    b.button(text="✉  Поддержка", url=config.SUPPORT_URL)
    b.button(text="Instagram", url=config.INSTAGRAM_URL)
    if is_admin:
        b.button(text="⚙  Админ", callback_data="admin_menu")
    if _webapp_https() and is_admin:
        b.adjust(2, 2, 2, 1)
    elif _webapp_https():
        b.adjust(2, 2, 2)
    elif is_admin:
        b.adjust(2, 1, 2, 1)
    else:
        b.adjust(2, 1, 2)
    return b.as_markup()


def kb_home_nav() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="◂  На главную", callback_data="back_to_menu")
    return b.as_markup()


def kb_access(*, inactive: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if inactive:
        b.button(text="♡  Поддержать", callback_data="donate")
        b.button(text="✉  Поддержка", url=config.SUPPORT_URL)
        b.button(text="◂  На главную", callback_data="back_to_menu")
        b.adjust(1)
        return b.as_markup()
    if _webapp_https():
        b.button(text="✧  Открыть кабинет", web_app=WebAppInfo(url=config.miniapp_url))
    b.button(text="▸  Подключение", callback_data="help")
    b.button(text="♡  Поддержать", callback_data="donate")
    b.button(text="◂  На главную", callback_data="back_to_menu")
    if _webapp_https():
        b.adjust(1, 2, 1)
    else:
        b.adjust(2, 1)
    return b.as_markup()


def kb_help() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✦  Мой доступ", callback_data="get_key")
    if _webapp_https():
        b.button(text="✧  Кабинет", web_app=WebAppInfo(url=config.miniapp_url))
    b.button(text="✉  Поддержка", url=config.SUPPORT_URL)
    b.button(text="◂  На главную", callback_data="back_to_menu")
    if _webapp_https():
        b.adjust(2, 2)
    else:
        b.adjust(2, 1)
    return b.as_markup()


def kb_donate() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✉  Написать автору", url=config.SUPPORT_URL)
    b.button(text="Instagram", url=config.INSTAGRAM_URL)
    b.button(text="✦  Мой доступ", callback_data="get_key")
    b.button(text="◂  На главную", callback_data="back_to_menu")
    b.adjust(2, 2)
    return b.as_markup()


def kb_tariffs() -> InlineKeyboardMarkup:
    return kb_donate()


def kb_order(_plan_id: str) -> InlineKeyboardMarkup:
    return kb_donate()


def kb_pay(_bill_url: str, _bill_id: str) -> InlineKeyboardMarkup:
    return kb_donate()


def kb_admin() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Обновить данные", callback_data="admin_refresh")
    b.button(text="Пользователи", callback_data="admin_users")
    b.button(text="📣  Рассылка", callback_data="admin_broadcast")
    b.button(text="◂  На главную", callback_data="back_to_menu")
    b.adjust(1)
    return b.as_markup()


def kb_admin_broadcast_cancel() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Отмена", callback_data="admin_broadcast_cancel")
    b.button(text="К админке", callback_data="admin_menu")
    b.adjust(1)
    return b.as_markup()


def kb_admin_broadcast_confirm() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✓  Отправить всем", callback_data="admin_broadcast_send")
    b.button(text="Отмена", callback_data="admin_broadcast_cancel")
    b.adjust(1)
    return b.as_markup()


def kb_admin_back() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="К админке", callback_data="admin_menu")
    return b.as_markup()


def kb_admin_users(*, page: int, pages: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    nav = 0
    if page > 0:
        b.button(text="Назад", callback_data=f"admin_users:{page - 1}")
        nav += 1
    if page < pages - 1:
        b.button(text="Ещё", callback_data=f"admin_users:{page + 1}")
        nav += 1
    b.button(text="К админке", callback_data="admin_menu")
    if nav == 2:
        b.adjust(2, 1)
    elif nav == 1:
        b.adjust(1, 1)
    else:
        b.adjust(1)
    return b.as_markup()


def kb_payment_success() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✦  Мой доступ", callback_data="get_key")
    b.button(text="◂  На главную", callback_data="back_to_menu")
    b.adjust(1)
    return b.as_markup()


def screen_home(user: User, *, is_admin: bool = False) -> str:
    badge, detail, _ = status_info(user)
    name = _esc(config.BOT_NAME)
    return (
        f"🔮  <b>{name}</b>\n"
        f"<i>цифровой доступ · всегда на связи</i>\n\n"
        f"<blockquote><b>◆  статус · {badge}</b>\n{_esc(detail)}</blockquote>\n\n"
        f"Обход ограничений · скорость · стабильность.\n"
        f"Один жест — и профиль у вас."
    )


def screen_access_inactive() -> str:
    return (
        f"<b>Доступ пока закрыт</b>\n\n"
        f"<blockquote>Напишите в поддержку — откроем профиль вручную.</blockquote>\n\n"
        f"Или поддержите проект, если хотите помочь развитию."
    )


def screen_access_loading() -> str:
    return (
        f"<b>Ещё секунда</b>\n\n"
        f"Профиль собирается. Подождите минуту\n"
        f"и нажмите «Мой доступ» снова."
    )


def screen_access(user: User, import_url: str) -> str:
    badge, detail, _ = status_info(user)
    return (
        f"<b>Ваш доступ</b>\n"
        f"<i>свобода без границ</i>\n\n"
        f"<blockquote><b>◆  статус · {badge}</b>\n{_esc(detail)}</blockquote>\n\n"
        f"<b>Ссылка профиля</b>\n"
        f"<code>{_esc(import_url)}</code>\n\n"
        f"1. Нажмите на ссылку — скопируется\n"
        f"2. Happ → добавить подписку\n"
        f"3. Автообновление — включить"
    )


def screen_access_short(user: User) -> str:
    badge, detail, _ = status_info(user)
    return (
        f"<b>Ваш доступ</b>\n"
        f"<i>свобода без границ</i>\n\n"
        f"<blockquote><b>◆  статус · {badge}</b>\n{_esc(detail)}</blockquote>\n\n"
        f"Ссылка профиля — сообщением ниже.\n"
        f"Нажмите на неё, чтобы скопировать."
    )


def screen_access_link(import_url: str) -> str:
    return f"<code>{_esc(import_url)}</code>"


def screen_donate() -> str:
    card = _esc(config.donation_card_spaced())
    name = _esc(config.DONATE_CARD_NAME)
    bank = _esc(config.DONATE_BANK)
    return (
        f"<b>Поддержать проект</b>\n"
        f"<i>автор и развитие Tsulo</i>\n\n"
        f"Сервис живёт на добровольных переводах.\n"
        f"Любая сумма — уже огромная помощь.\n\n"
        f"<blockquote><b>{bank}</b>\n"
        f"<code>{card}</code>\n"
        f"{name}</blockquote>\n\n"
        f"Нажмите на номер — чтобы скопировать.\n"
        f"Спасибо, что вы с нами."
    )


def screen_tariffs() -> str:
    return screen_donate()


def screen_order(plan: TariffPlan) -> str:
    return screen_donate()


def screen_pay(plan: TariffPlan) -> str:
    return screen_donate()


def screen_pay_error() -> str:
    return (
        f"<b>Оплата через кассу отключена</b>\n\n"
        f"Поддержать проект можно переводом на карту\n"
        f"в разделе «Поддержать»."
    )


def screen_help() -> str:
    name = _esc(config.BOT_NAME)
    return (
        f"<b>{name}</b>\n"
        f"<i>как подключить за минуту</i>\n\n"
        f"<blockquote><b>1.</b>  Откройте «Мой доступ»\n"
        f"<b>2.</b>  Нажмите на ссылку — скопируется\n"
        f"<b>3.</b>  Happ → добавить подписку → автообновление</blockquote>\n\n"
        f"На мобильном берите профиль с ping, не N/A.\n"
        f"Связь просела — переключите профиль\n"
        f"и подождите 10–15 секунд.\n\n"
        f"Нужна помощь — кнопка «Поддержка»."
    )


def screen_admin(
    *,
    users: int,
    sub_count: int,
    limit: int,
    primary: int,
    fill: int,
    source_total: int = 0,
    sources_line: str = "",
    wifi_count: int = 0,
    lte_count: int = 0,
    source_status: str = "unknown",
    source_key: str = "",
    last_error: str | None = None,
    source_real: int = 0,
) -> str:
    sources = f"\nисточники · {_esc(sources_line)}" if sources_line else ""
    status_map = {
        "ok": "✓ источник OK",
        "degraded": "⚠ кэш (источник недоступен)",
        "failed": "✗ источник не работает",
        "unknown": "… загрузка",
    }
    status_line = status_map.get(source_status, source_status)
    key_line = f"\nключ · <code>{_esc(source_key)}</code>" if source_key else ""
    real_line = f"\nреальных · {source_real}" if source_real else ""
    err_line = f"\n<i>{_esc(last_error)}</i>" if last_error else ""
    return (
        f"<b>Админ</b>\n\n"
        f"<blockquote>пользователей · <b>{users}</b>\n"
        f"в профиле · <b>{sub_count}</b> / {limit}\n"
        f"в источнике · {source_total}{sources}{key_line}{real_line}\n"
        f"статус · {status_line}{err_line}\n"
        f"формат · Happ JSON</blockquote>"
    )


def screen_admin_broadcast_prompt() -> str:
    return (
        "<b>Рассылка</b>\n\n"
        "Отправьте сообщение, которое получат все пользователи бота.\n"
        "Поддерживаются текст, фото, видео и другие типы.\n\n"
        "<blockquote>После отправки покажем превью и попросим подтверждение.</blockquote>\n\n"
        "Отмена — /cancel"
    )


def screen_admin_broadcast_confirm(*, users: int) -> str:
    spaced = f"{users:,}".replace(",", " ")
    return (
        "<b>Подтвердите рассылку</b>\n\n"
        f"Сообщение выше будет отправлено <b>{spaced}</b> пользователям.\n\n"
        "Это действие нельзя отменить."
    )


def screen_admin_broadcast_progress(*, sent: int, total: int) -> str:
    return (
        "<b>Рассылка…</b>\n\n"
        f"Отправлено: <b>{sent}</b> / {total}"
    )


def screen_admin_broadcast_done(*, sent: int, blocked: int, failed: int, total: int) -> str:
    return (
        "<b>Рассылка завершена</b>\n\n"
        f"<blockquote>всего · {total}\n"
        f"доставлено · <b>{sent}</b>\n"
        f"заблокировали бота · {blocked}\n"
        f"ошибки · {failed}</blockquote>"
    )


def screen_admin_refresh(
    *,
    sub_count: int,
    limit: int,
    primary: int,
    fill: int,
    source_total: int = 0,
    sources_line: str = "",
    wifi_count: int = 0,
    lte_count: int = 0,
    source_status: str = "unknown",
    source_key: str = "",
    last_error: str | None = None,
    source_real: int = 0,
) -> str:
    sources = f"\nисточники · {_esc(sources_line)}" if sources_line else ""
    status_map = {
        "ok": "✓ OK",
        "degraded": "⚠ кэш",
        "failed": "✗ ошибка",
        "unknown": "…",
    }
    status_line = status_map.get(source_status, source_status)
    err_line = f"\n<i>{_esc(last_error)}</i>" if last_error else ""
    return (
        f"<b>Данные обновлены</b>\n\n"
        f"<blockquote>в профиле · <b>{sub_count}</b> / {limit}\n"
        f"в источнике · {source_total}{sources}\n"
        f"статус · {status_line}{err_line}</blockquote>"
    )


def screen_payment_success(plan_title: str, user: User) -> str:
    badge, detail, _ = status_info(user)
    return (
        f"<b>Спасибо</b>\n\n"
        f"<blockquote>статус · <b>{badge}</b>\n{_esc(detail)}</blockquote>\n\n"
        f"Можно открывать доступ."
    )


def format_tariffs_text() -> str:
    return screen_donate()


def format_order_text(plan: TariffPlan) -> str:
    return screen_donate()
