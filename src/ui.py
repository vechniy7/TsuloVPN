"""Единый визуальный язык экранов Telegram-бота."""

from __future__ import annotations

import html
from datetime import datetime, timezone

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import config
from database import User
from payments import PLANS, TariffPlan, get_plan, is_subscription_active

DIV = "────────"


def _esc(value: str | None) -> str:
    return html.escape(value or "")


def status_info(user: User) -> tuple[str, str, bool]:
    """
    Returns (badge, detail_line, is_active).
    badge: АКТИВЕН / НУЖЕН ТАРИФ / ИСТЁК
    """
    if not config.payments_active:
        return "АКТИВЕН", "полный доступ", True

    if not user.expires_at:
        return "НУЖЕН ТАРИФ", "оформите подписку, чтобы открыть доступ", False

    try:
        expires = datetime.fromisoformat(user.expires_at)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= datetime.now(timezone.utc):
            return "ИСТЁК", "продлите подписку, чтобы продолжить", False
        return "АКТИВЕН", f"доступ до {expires.strftime('%d.%m.%Y')}", True
    except ValueError:
        return "АКТИВЕН", "полный доступ", True


def format_access_until(user: User) -> str:
    badge, detail, _ = status_info(user)
    if badge == "АКТИВЕН" and detail.startswith("доступ до"):
        return detail.replace("доступ ", "")
    if badge == "АКТИВЕН":
        return "активен"
    if badge == "ИСТЁК":
        return "истёк — выберите тариф"
    return "не оплачен — выберите тариф"


def plan_per_month(plan: TariffPlan) -> int:
    return max(1, round(plan.price_rub / max(plan.months, 1)))


def plan_is_best(plan: TariffPlan) -> bool:
    return plan.id == "12m"


def plan_button_label(plan: TariffPlan) -> str:
    short = {1: "1 мес", 3: "3 мес", 12: "12 мес"}.get(plan.months, plan.title)
    label = f"{short} · {plan.price_rub} ₽"
    if plan_is_best(plan):
        label += " · выгода"
    return label


def kb_home(*, is_admin: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Получить доступ", callback_data="get_key")
    b.button(text="Тарифы", callback_data="tariffs")
    b.button(text="Как подключить", callback_data="help")
    if is_admin:
        b.button(text="Админ", callback_data="admin_menu")
    b.adjust(2, 1, 1)
    return b.as_markup()


def kb_home_nav() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="На главную", callback_data="back_to_menu")
    return b.as_markup()


def kb_tariffs() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for plan in PLANS.values():
        b.button(text=plan_button_label(plan), callback_data=f"order:{plan.id}")
    b.button(text="На главную", callback_data="back_to_menu")
    b.adjust(1)
    return b.as_markup()


def kb_order(plan_id: str) -> InlineKeyboardMarkup:
    plan = get_plan(plan_id)
    price = plan.price_rub if plan else 0
    b = InlineKeyboardBuilder()
    b.button(text=f"Оплатить {price} ₽", callback_data=f"pay:{plan_id}")
    b.button(text="К тарифам", callback_data="tariffs")
    b.adjust(1)
    return b.as_markup()


def kb_pay(bill_url: str, bill_id: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="Перейти к оплате", url=bill_url))
    b.button(text="Проверить оплату", callback_data=f"check:{bill_id}")
    b.button(text="К тарифам", callback_data="tariffs")
    b.adjust(1)
    return b.as_markup()


def kb_access(*, inactive: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if inactive:
        b.button(text="Выбрать тариф", callback_data="tariffs")
        b.button(text="На главную", callback_data="back_to_menu")
        b.adjust(1)
        return b.as_markup()
    b.button(text="Обновить ссылку", callback_data="get_key")
    b.button(text="Тарифы", callback_data="tariffs")
    b.button(text="На главную", callback_data="back_to_menu")
    b.adjust(2, 1)
    return b.as_markup()


def kb_help() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Получить доступ", callback_data="get_key")
    b.button(text="Тарифы", callback_data="tariffs")
    b.button(text="На главную", callback_data="back_to_menu")
    b.adjust(2, 1)
    return b.as_markup()


def kb_admin() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Обновить данные", callback_data="admin_refresh")
    b.button(text="Пользователи", callback_data="admin_users")
    b.button(text="На главную", callback_data="back_to_menu")
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
    b.button(text="Получить доступ", callback_data="get_key")
    b.button(text="На главную", callback_data="back_to_menu")
    b.adjust(1)
    return b.as_markup()


def screen_home(user: User, *, is_admin: bool = False) -> str:
    badge, detail, active = status_info(user)
    name = _esc(config.BOT_NAME)
    if active:
        tip = "Откройте доступ одной кнопкой или продлите подписку."
    else:
        tip = "Выберите тариф — доступ откроется сразу после оплаты."

    return (
        f"<b>{name}</b>\n"
        f"<i>цифровая подписка</i>\n\n"
        f"{DIV}\n"
        f"<b>Статус · {badge}</b>\n"
        f"{_esc(detail)}\n"
        f"{DIV}\n\n"
        f"{tip}"
    )


def screen_access_inactive() -> str:
    return (
        f"<b>Доступ закрыт</b>\n\n"
        f"{DIV}\n"
        f"Подписка не активна.\n"
        f"Оформите тариф — и ссылка появится здесь.\n"
        f"{DIV}"
    )


def screen_access_loading() -> str:
    return (
        f"<b>Почти готово</b>\n\n"
        f"Данные ещё подгружаются.\n"
        f"Подождите минуту и нажмите «Обновить ссылку»."
    )


def screen_access(user: User, import_url: str) -> str:
    badge, detail, _ = status_info(user)
    return (
        f"<b>Ваш доступ</b>\n\n"
        f"{DIV}\n"
        f"<b>Статус · {badge}</b>\n"
        f"{_esc(detail)}\n"
        f"{DIV}\n\n"
        f"<b>Ссылка</b>\n"
        f"<code>{_esc(import_url)}</code>\n\n"
        f"<b>Как подключить</b>\n"
        f"1. Скопируйте ссылку (тап по тексту)\n"
        f"2. Вставьте в приложение-клиент\n"
        f"3. Включите автообновление\n\n"
        f"В списке серверов выберите <b>АВТО-ВЫБОР</b> — "
        f"клиент сам возьмёт узел с лучшим пингом."
    )


def screen_tariffs() -> str:
    lines = [
        f"<b>Тарифы</b>",
        f"<i>цифровая подписка · мгновенная выдача</i>",
        "",
        DIV,
    ]
    for plan in PLANS.values():
        per = plan_per_month(plan)
        mark = " · <b>выгоднее</b>" if plan_is_best(plan) else ""
        lines.append(f"<b>{_esc(plan.title)}</b>{mark}")
        lines.append(f"{plan.price_rub} ₽ · ≈ {per} ₽/мес")
        lines.append("")
    lines.append(DIV)
    lines.append("Выберите срок — откроется оформление.")
    return "\n".join(lines)


def screen_order(plan: TariffPlan) -> str:
    per = plan_per_month(plan)
    best = "\nЛучшее соотношение цены и срока." if plan_is_best(plan) else ""
    return (
        f"<b>Оформление</b>\n\n"
        f"{DIV}\n"
        f"<b>{_esc(plan.title)}</b>\n"
        f"Цифровая подписка\n"
        f"{DIV}\n\n"
        f"К оплате: <b>{plan.price_rub} ₽</b>\n"
        f"≈ {per} ₽ в месяц{best}"
    )


def screen_pay(plan: TariffPlan) -> str:
    return (
        f"<b>Оплата</b>\n\n"
        f"{DIV}\n"
        f"{_esc(plan.title)}\n"
        f"<b>{plan.price_rub} ₽</b>\n"
        f"{DIV}\n\n"
        f"1. Нажмите «Перейти к оплате»\n"
        f"2. Вернитесь и нажмите «Проверить оплату»\n\n"
        f"Доступ активируется автоматически."
    )


def screen_pay_error() -> str:
    return (
        f"<b>Не удалось создать счёт</b>\n\n"
        f"Попробуйте ещё раз чуть позже\n"
        f"или напишите в поддержку."
    )


def screen_help() -> str:
    name = _esc(config.BOT_NAME)
    return (
        f"<b>{name}</b>\n"
        f"<i>как подключить</i>\n\n"
        f"{DIV}\n"
        f"<b>1.</b> Получите ссылку в «Доступ»\n"
        f"<b>2.</b> Добавьте её в приложение-клиент\n"
        f"<b>3.</b> Включите автообновление\n"
        f"{DIV}\n\n"
        f"<b>АВТО-ВЫБОР</b>\n"
        f"Умный сервер: сам выбирает узел\n"
        f"с наименьшим пингом и переключается,\n"
        f"если связь слабеет.\n\n"
        f"Нужна помощь — напишите администратору."
    )


def screen_admin(*, users: int, sub_count: int, limit: int, primary: int, fill: int) -> str:
    return (
        f"<b>Админ</b>\n\n"
        f"{DIV}\n"
        f"Пользователей · <b>{users}</b>\n"
        f"В ключе · <b>{sub_count}</b> / {limit}\n"
        f"Основной · {primary} · доп. · {fill}\n"
        f"{DIV}"
    )


def screen_admin_refresh(*, sub_count: int, limit: int, primary: int, fill: int) -> str:
    return (
        f"<b>Данные обновлены</b>\n\n"
        f"{DIV}\n"
        f"В ключе · <b>{sub_count}</b> / {limit}\n"
        f"Основной · {primary} · доп. · {fill}\n"
        f"{DIV}"
    )


def screen_payment_success(plan_title: str, user: User) -> str:
    badge, detail, _ = status_info(user)
    return (
        f"<b>Оплата получена</b>\n\n"
        f"{DIV}\n"
        f"Тариф · {_esc(plan_title)}\n"
        f"Статус · <b>{badge}</b>\n"
        f"{_esc(detail)}\n"
        f"{DIV}\n\n"
        f"Можно открывать доступ."
    )


# Compatibility aliases used by payments/other modules
def format_tariffs_text() -> str:
    return screen_tariffs()


def format_order_text(plan: TariffPlan) -> str:
    return screen_order(plan)
