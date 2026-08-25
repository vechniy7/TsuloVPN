"""Единый визуальный язык экранов Telegram-бота."""

from __future__ import annotations

import html

from aiogram.types import InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config
from database import User
from payments import TariffPlan, is_subscription_active


def _esc(value: str | None) -> str:
    return html.escape(value or "")


def _webapp_https() -> bool:
    return config.miniapp_url.lower().startswith("https://")


def _plans() -> list[TariffPlan]:
    from payments import PLANS

    return list(PLANS.values())


def _main_plan() -> TariffPlan | None:
    plans = _plans()
    return plans[0] if plans else None


def status_info(user: User) -> tuple[str, str, bool]:
    if not config.payments_active:
        return "активен", "полный доступ · сейчас бесплатно", True
    if is_subscription_active(user):
        return "активен", "подписка действует", True
    return "неактивен", "оформите подписку или напишите в поддержку", False


def format_access_until(user: User) -> str:
    badge, detail, active = status_info(user)
    if active:
        return "активен"
    return detail


def kb_channel_required() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Подписаться на канал", url=config.required_channel_url)
    b.button(text="Проверить подписку", callback_data="check_channel_sub")
    b.adjust(1)
    return b.as_markup()


def screen_channel_required() -> str:
    channel = _esc(config.required_channel_id.lstrip("@") or "TsuloVPN")
    name = _esc(config.BOT_NAME)
    return (
        f"<b>{name}</b>\n\n"
        f"Чтобы продолжить, подпишитесь на канал <b>@{channel}</b>.\n\n"
        f"1. Нажмите «Подписаться на канал»\n"
        f"2. Вернитесь и нажмите «Проверить подписку»"
    )


def kb_home(*, is_admin: bool) -> InlineKeyboardMarkup:
    """Короткое меню как у типичных VPN-ботов: одно действие на строку."""
    b = InlineKeyboardBuilder()
    b.button(text="Мой доступ", callback_data="get_key")
    plan = _main_plan()
    price = f" · {plan.price_rub} ₽" if plan else ""
    b.button(text=f"Тарифы{price}", callback_data="tariffs")
    b.button(text="Документы", callback_data="docs")
    b.button(text="Поддержка", url=config.SUPPORT_URL)
    b.button(text="Поддержать проект", callback_data="donate")
    if _webapp_https():
        b.button(text="Кабинет", web_app=WebAppInfo(url=config.miniapp_url))
    if is_admin:
        b.button(text="Админ", callback_data="admin_menu")
    b.adjust(1)
    return b.as_markup()


def kb_home_nav() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="← Назад", callback_data="back_to_menu")
    return b.as_markup()


def kb_access(*, inactive: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if inactive:
        b.button(text="Тарифы", callback_data="tariffs")
        b.button(text="Поддержка", url=config.SUPPORT_URL)
        b.button(text="← Назад", callback_data="back_to_menu")
        b.adjust(1)
        return b.as_markup()
    if _webapp_https():
        b.button(text="Открыть кабинет", web_app=WebAppInfo(url=config.miniapp_url))
    b.button(text="Тарифы", callback_data="tariffs")
    b.button(text="Поддержка", url=config.SUPPORT_URL)
    b.button(text="← Назад", callback_data="back_to_menu")
    b.adjust(1)
    return b.as_markup()


def kb_help() -> InlineKeyboardMarkup:
    return kb_access()


def kb_donate() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Написать в поддержку", url=config.SUPPORT_URL)
    b.button(text="← Назад", callback_data="back_to_menu")
    b.adjust(1)
    return b.as_markup()


def kb_docs() -> InlineKeyboardMarkup:
    """Документы отдельными кнопками — требование для согласования с банком."""
    b = InlineKeyboardBuilder()
    b.button(text="Тарифы и цены", url=config.tariffs_page_url)
    b.button(text="Политика конфиденциальности", url=config.privacy_page_url)
    b.button(text="Пользовательское соглашение", url=config.terms_page_url)
    b.button(text="Поддержка", url=config.SUPPORT_URL)
    b.button(text="← Назад", callback_data="back_to_menu")
    b.adjust(1)
    return b.as_markup()


def kb_tariffs() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Открыть тарифы", url=config.tariffs_page_url)
    b.button(text="Политика конфиденциальности", url=config.privacy_page_url)
    b.button(text="Пользовательское соглашение", url=config.terms_page_url)
    b.button(text="Поддержка", url=config.SUPPORT_URL)
    if config.payments_active:
        for plan in _plans():
            b.button(text=f"Оплатить · {plan.price_rub} ₽", callback_data=f"order:{plan.id}")
    else:
        b.button(text="Мой доступ", callback_data="get_key")
    b.button(text="← Назад", callback_data="back_to_menu")
    b.adjust(1)
    return b.as_markup()


def kb_order(_plan_id: str) -> InlineKeyboardMarkup:
    return kb_tariffs()


def kb_pay(_bill_url: str, _bill_id: str) -> InlineKeyboardMarkup:
    return kb_tariffs()


def kb_admin() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Обновить данные", callback_data="admin_refresh")
    b.button(text="Пользователи", callback_data="admin_users")
    b.button(text="Рассылка", callback_data="admin_broadcast")
    b.button(text="← Назад", callback_data="back_to_menu")
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
    b.button(text="Отправить всем", callback_data="admin_broadcast_send")
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
    b.button(text="Мой доступ", callback_data="get_key")
    b.button(text="← Назад", callback_data="back_to_menu")
    b.adjust(1)
    return b.as_markup()


def format_users_count_spaced(count: int) -> str:
    return f"{count:,}".replace(",", " ")


def screen_home(user: User, *, is_admin: bool = False, users_total: int | None = None) -> str:
    badge, detail, _ = status_info(user)
    name = _esc(config.BOT_NAME)
    plan = _main_plan()
    price_line = f"{plan.price_rub} ₽ / месяц" if plan else "тариф на сайте"
    users_line = ""
    if users_total is not None:
        users_line = f"\nПользователей: <b>{format_users_count_spaced(users_total)}</b>\n"
    return (
        f"<b>{name}</b>{users_line}\n"
        f"Цифровой сервис доступа\n\n"
        f"Статус: <b>{_esc(badge)}</b>\n"
        f"{_esc(detail)}\n\n"
        f"Тариф: <b>{price_line}</b>\n"
        f"Сейчас доступ бесплатный для всех.\n\n"
        f"Нажмите «Мой доступ», чтобы получить ссылку профиля."
    )


def screen_access_inactive() -> str:
    return (
        "<b>Доступ закрыт</b>\n\n"
        "Напишите в поддержку — поможем открыть профиль.\n"
        "Актуальные тарифы — в разделе «Тарифы»."
    )


def screen_access_loading() -> str:
    return (
        "<b>Профиль обновляется</b>\n\n"
        "Подождите около минуты и снова нажмите «Мой доступ»."
    )


def screen_access(user: User, import_url: str) -> str:
    badge, detail, _ = status_info(user)
    return (
        f"<b>Ваш доступ</b>\n\n"
        f"Статус: <b>{_esc(badge)}</b>\n"
        f"{_esc(detail)}\n\n"
        f"<b>Ссылка профиля</b>\n"
        f"<code>{_esc(import_url)}</code>\n\n"
        f"Как подключить:\n"
        f"1. Нажмите на ссылку — она скопируется\n"
        f"2. Откройте Happ → добавить подписку\n"
        f"3. Включите автообновление"
    )


def screen_access_short(user: User) -> str:
    badge, detail, _ = status_info(user)
    return (
        f"<b>Ваш доступ</b>\n\n"
        f"Статус: <b>{_esc(badge)}</b>\n"
        f"{_esc(detail)}\n\n"
        f"Ссылка профиля — в следующем сообщении."
    )


def screen_access_link(import_url: str) -> str:
    return f"<code>{_esc(import_url)}</code>"


def screen_donate() -> str:
    card = _esc(config.donation_card_spaced())
    bank = _esc(config.DONATE_BANK)
    return (
        f"<b>Поддержать проект</b>\n\n"
        f"Добровольный перевод помогает развивать {_esc(config.BOT_NAME)}.\n\n"
        f"<b>{bank}</b>\n"
        f"<code>{card}</code>\n\n"
        f"Нажмите на номер, чтобы скопировать."
    )


def screen_docs() -> str:
    name = _esc(config.BOT_NAME)
    return (
        f"<b>Документы · {name}</b>\n\n"
        f"Все материалы всегда доступны по кнопкам ниже:\n\n"
        f"• Тарифы и цены\n"
        f"• Политика конфиденциальности\n"
        f"• Пользовательское соглашение\n"
        f"• Поддержка: {_esc(config.SUPPORT_URL)}\n\n"
        f"<i>код согласования · плаtega</i>"
    )


def screen_tariffs() -> str:
    plan = _main_plan()
    name = _esc(config.BOT_NAME)
    if not plan:
        return f"<b>Тарифы · {name}</b>\n\nТариф временно недоступен."
    status = (
        "Сейчас доступ <b>бесплатный</b> для всех пользователей.\n"
        "Ниже — актуальная стоимость подписки сервиса."
        if not config.payments_active
        else "Оплата открывает подписку на указанный срок."
    )
    return (
        f"<b>Тарифы · {name}</b>\n\n"
        f"{status}\n\n"
        f"<b>{_esc(plan.title)}</b> — <b>{plan.price_rub} ₽</b>\n"
        f"цифровой доступ к профилю, обновления и поддержка\n\n"
        f"Полное описание — на странице тарифов.\n"
        f"<i>код согласования · плаtega</i>"
    )


def screen_order(plan: TariffPlan) -> str:
    return screen_tariffs()


def screen_pay(plan: TariffPlan) -> str:
    return screen_tariffs()


def screen_pay_error() -> str:
    return (
        "<b>Онлайн-оплата пока не подключена</b>\n\n"
        "Актуальный тариф — в разделе «Тарифы».\n"
        "Вопросы — в поддержку."
    )


def screen_help() -> str:
    name = _esc(config.BOT_NAME)
    return (
        f"<b>{name}</b>\n\n"
        f"1. Откройте «Мой доступ»\n"
        f"2. Скопируйте ссылку профиля\n"
        f"3. Happ → добавить подписку → автообновление\n\n"
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
        "ok": "OK",
        "degraded": "кэш",
        "failed": "ошибка",
        "unknown": "загрузка",
    }
    status_line = status_map.get(source_status, source_status)
    err_line = f"\n{_esc(last_error)}" if last_error else ""
    return (
        f"<b>Админ</b>\n\n"
        f"пользователей · <b>{users}</b>\n"
        f"в профиле · <b>{sub_count}</b> / {limit}\n"
        f"в источнике · {source_total}{sources}\n"
        f"статус · {status_line}{err_line}"
    )


def screen_admin_broadcast_prompt() -> str:
    return (
        "<b>Рассылка</b>\n\n"
        "Отправьте сообщение для всех пользователей.\n"
        "После этого покажем превью и попросим подтверждение.\n\n"
        "Отмена — /cancel"
    )


def screen_admin_broadcast_confirm(*, users: int) -> str:
    spaced = f"{users:,}".replace(",", " ")
    return (
        "<b>Подтвердите рассылку</b>\n\n"
        f"Сообщение будет отправлено <b>{spaced}</b> пользователям."
    )


def screen_admin_broadcast_progress(
    *,
    sent: int,
    blocked: int,
    failed: int,
    total: int,
) -> str:
    done = sent + blocked + failed
    pct = int(done * 100 / total) if total else 0
    return (
        "<b>Рассылка…</b>\n\n"
        f"{done} / {total} ({pct}%)\n"
        f"доставлено · {sent}\n"
        f"блок · {blocked}\n"
        f"ошибки · {failed}"
    )


def screen_admin_broadcast_done(*, sent: int, blocked: int, failed: int, total: int) -> str:
    return (
        "<b>Рассылка завершена</b>\n\n"
        f"всего · {total}\n"
        f"доставлено · <b>{sent}</b>\n"
        f"блок · {blocked}\n"
        f"ошибки · {failed}"
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
    status_map = {"ok": "OK", "degraded": "кэш", "failed": "ошибка", "unknown": "…"}
    status_line = status_map.get(source_status, source_status)
    err_line = f"\n{_esc(last_error)}" if last_error else ""
    return (
        f"<b>Данные обновлены</b>\n\n"
        f"в профиле · <b>{sub_count}</b> / {limit}\n"
        f"в источнике · {source_total}{sources}\n"
        f"статус · {status_line}{err_line}"
    )


def screen_payment_success(plan_title: str, user: User) -> str:
    badge, detail, _ = status_info(user)
    return (
        f"<b>Оплата принята</b>\n\n"
        f"Статус: <b>{_esc(badge)}</b>\n"
        f"{_esc(detail)}\n\n"
        f"Можно открывать «Мой доступ»."
    )


def format_tariffs_text() -> str:
    return screen_tariffs()


def format_order_text(plan: TariffPlan) -> str:
    return screen_tariffs()
