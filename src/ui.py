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
        return "активен", "полный доступ", True
    if is_subscription_active(user):
        until = ""
        if user.expires_at:
            try:
                from datetime import datetime, timezone

                expires = datetime.fromisoformat(user.expires_at)
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                until = expires.astimezone().strftime("%d.%m.%Y")
            except ValueError:
                until = ""
        detail = f"подписка до {until}" if until else "подписка активна"
        return "активен", detail, True
    return "неактивен", "оформите подписку в разделе «Тарифы»", False


def format_access_until(user: User) -> str:
    badge, detail, active = status_info(user)
    if active:
        return detail if "до" in detail else "активен"
    return detail


def kb_channel_required() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📢 Подписаться на канал", url=config.required_channel_url)
    b.button(text="✅ Проверить подписку", callback_data="check_channel_sub")
    b.adjust(1)
    return b.as_markup()


def screen_channel_required() -> str:
    channel = _esc(config.required_channel_id.lstrip("@") or "TsuloVPN")
    name = _esc(config.BOT_NAME)
    return (
        f"💜 <b>{name}</b>\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"Для доступа подпишитесь на канал\n"
        f"<b>@{channel}</b>\n\n"
        f"① «Подписаться на канал»\n"
        f"② Вернитесь → «Проверить подписку»"
    )


def kb_home(*, is_admin: bool, user: User | None = None) -> InlineKeyboardMarkup:
    """Меню как у популярных VPN-ботов: ключ сверху, оплата, гайд, поддержка."""
    from devices import monthly_price_for_user

    b = InlineKeyboardBuilder()
    plan = _main_plan()
    if user and config.payments_active:
        price = f"{monthly_price_for_user(user)}₽"
    else:
        price = f"{plan.price_rub}₽" if plan else ""
    b.button(text="🔑  Мой ключ", callback_data="get_key")
    b.button(text=f"💳  Тарифы · {price}/мес" if price else "💳  Тарифы", callback_data="tariffs")
    b.button(text="📖  Инструкция", callback_data="help")
    b.button(text="💬  Поддержка", url=config.SUPPORT_URL)
    if _webapp_https():
        b.button(text="🖥  Кабинет", web_app=WebAppInfo(url=config.miniapp_url))
    if is_admin:
        b.button(text="🛠  Админ", callback_data="admin_menu")
    b.adjust(1)
    return b.as_markup()


def kb_home_nav() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="◀️  В меню", callback_data="back_to_menu")
    return b.as_markup()


def kb_access(
    *,
    inactive: bool = False,
    user: User | None = None,
    sub_url: str | None = None,
) -> InlineKeyboardMarkup:
    from open_apps import open_app_https_url

    b = InlineKeyboardBuilder()
    if inactive:
        b.button(text="💳  Оформить подписку", callback_data="tariffs")
        b.button(text="📖  Инструкция", callback_data="help")
        b.button(text="💬  Поддержка", url=config.SUPPORT_URL)
        b.button(text="◀️  В меню", callback_data="back_to_menu")
        b.adjust(1)
        return b.as_markup()

    # Автоимпорт в клиенты (HTTPS-редирект → deep link)
    app_btns = 0
    if sub_url:
        happ = open_app_https_url("happ", sub_url)
        incy = open_app_https_url("incy", sub_url)
        happplus = open_app_https_url("happplus", sub_url)
        if happ:
            b.button(text="⚡  Открыть в Happ", url=happ)
            app_btns += 1
        if incy:
            b.button(text="🌀  Открыть в INCY", url=incy)
            app_btns += 1
        if happplus:
            b.button(text="✨  Открыть в Happ Plus", url=happplus)
            app_btns += 1

    b.button(text="🔄  Обновить экран", callback_data="get_key")
    b.button(text="📱  Устройства", callback_data="devices")
    b.button(text="📖  Как подключить", callback_data="help")
    if _webapp_https():
        b.button(text="🖥  Кабинет", web_app=WebAppInfo(url=config.miniapp_url))
    b.button(text="◀️  В меню", callback_data="back_to_menu")
    b.adjust(1)
    return b.as_markup()


def kb_devices(user: User) -> InlineKeyboardMarkup:
    from devices import addon_options, user_device_limit

    b = InlineKeyboardBuilder()
    for opt in addon_options(user):
        add = opt["add"]
        label = f"➕ +{add} устр. · {opt['price_rub']} ₽"
        b.button(text=label, callback_data=f"order:{opt['plan_id']}")
    if user_device_limit(user) > 1:
        b.button(text="⬇️  Вернуть 1 устройство · 69 ₽/мес", callback_data="devices_downgrade")
    b.button(text="🔓  Сбросить привязки (HWID)", callback_data="reset_hwid")
    b.button(text="🔑  К ключу", callback_data="get_key")
    b.button(text="◀️  В меню", callback_data="back_to_menu")
    b.adjust(1)
    return b.as_markup()


def kb_devices_downgrade_confirm() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅  Да, оставить 1 устройство", callback_data="devices_downgrade_yes")
    b.button(text="◀️  Отмена", callback_data="devices")
    b.adjust(1)
    return b.as_markup()


def kb_help() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔑  Получить ключ", callback_data="get_key")
    b.button(text="◀️  В меню", callback_data="back_to_menu")
    b.adjust(1)
    return b.as_markup()


def kb_docs() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📄 Тарифы", url=config.tariffs_page_url)
    b.button(text="🔒 Конфиденциальность", url=config.privacy_page_url)
    b.button(text="📋 Соглашение", url=config.terms_page_url)
    b.button(text="💬 Поддержка", url=config.SUPPORT_URL)
    b.button(text="◀️  В меню", callback_data="back_to_menu")
    b.adjust(1)
    return b.as_markup()


def kb_tariffs(user: User | None = None) -> InlineKeyboardMarkup:
    from devices import monthly_price_for_user

    b = InlineKeyboardBuilder()
    if config.payments_active:
        for plan in _plans():
            price = monthly_price_for_user(user) if user else plan.price_rub
            b.button(
                text=f"💜  Оплатить {price} ₽ / мес",
                callback_data=f"order:{plan.id}",
            )
        b.button(text="➕  Доп. устройства", callback_data="devices")
    else:
        b.button(text="🔑  Мой ключ", callback_data="get_key")
    b.button(text="📄  Подробнее", url=config.tariffs_page_url)
    b.button(text="◀️  В меню", callback_data="back_to_menu")
    b.adjust(1)
    return b.as_markup()


def kb_order(_plan_id: str) -> InlineKeyboardMarkup:
    return kb_tariffs()


def kb_pay(pay_url: str, bill_id: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💜  Перейти к оплате", url=pay_url)
    b.button(text="✅  Я оплатил", callback_data=f"check:{bill_id}")
    b.button(text="◀️  Назад", callback_data="tariffs")
    b.adjust(1)
    return b.as_markup()

def kb_admin() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if config.panel_enabled:
        b.button(text="🌐 Открыть панель", url=config.panel_url)
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
    from devices import monthly_price_for_user, user_device_limit

    badge, detail, active = status_info(user)
    name = _esc(config.BOT_NAME)
    month = monthly_price_for_user(user)
    limit = user_device_limit(user)
    status_emoji = "🟢" if active else "🔴"
    users_line = ""
    if users_total is not None:
        users_line = f"👥  {_esc(format_users_count_spaced(users_total))}\n"
    if active:
        cta = "«Мой ключ» → откройте Happ / INCY одной кнопкой."
    else:
        cta = "Оформите подписку в «Тарифы», затем получите ключ."
    return (
        f"💜 <b>{name}</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{users_line}"
        f"{status_emoji}  Статус: <b>{_esc(badge)}</b>\n"
        f"📅  {_esc(detail)}\n"
        f"💎  Продление: <b>{month} ₽/мес</b>\n"
        f"📱  Устройств: <b>до {limit}</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{cta}"
    )


def screen_access_inactive() -> str:
    plan = _main_plan()
    price = f"{plan.price_rub} ₽" if plan else "по тарифу"
    return (
        f"💜 <b>Подписка неактивна</b>\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"Доступ закрыт. Оформите тариф — <b>{price}/мес</b>.\n\n"
        f"После оплаты нажмите «Мой ключ»."
    )


def screen_access_loading() -> str:
    return (
        f"💜 <b>Обновляем серверы</b>\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"Подождите ~1 минуту и снова нажмите «Мой ключ»."
    )


def screen_access(user: User, import_url: str) -> str:
    from devices import MAX_DEVICE_SLOTS, bound_hwid_list, monthly_price_for_user, user_device_limit

    badge, detail, _ = status_info(user)
    limit = user_device_limit(user)
    used = len(bound_hwid_list(user))
    month = monthly_price_for_user(user)
    return (
        f"💜 <b>Ваш ключ</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🟢  {_esc(badge)} · {_esc(detail)}\n"
        f"📱  Устройства: <b>{used} из {limit}</b> (макс. {MAX_DEVICE_SLOTS})\n"
        f"💎  Продление: <b>{month} ₽/мес</b>\n\n"
        f"<b>Ссылка подписки</b> — нажмите → «Копировать»:\n"
        f"<code>{_esc(import_url)}</code>\n\n"
        f"Или кнопки ниже — откроют Happ / INCY / Happ Plus и добавят ключ сами.\n"
        f"«Устройства» — лимит, сброс привязок, отказ от доп. слотов."
    )


def screen_devices(user: User) -> str:
    from devices import (
        BASE_MONTHLY_PRICE,
        FIRST_EXTRA_SLOT_PRICE,
        MAX_DEVICE_SLOTS,
        addon_options,
        bound_hwid_list,
        monthly_price_for_user,
        slot_price,
        user_device_limit,
    )

    limit = user_device_limit(user)
    used = len(bound_hwid_list(user))
    month = monthly_price_for_user(user)
    extras = ""
    if limit > 1:
        parts = [f"слот {n}: {slot_price(n)} ₽" for n in range(2, limit + 1)]
        extras = "Доп. слоты в цене: " + ", ".join(parts) + ".\n"

    opts = addon_options(user)
    if opts:
        buy_lines = "\n".join(
            f"· купить +{o['add']} → лимит {o['new_limit']} · <b>{o['price_rub']} ₽</b> разово"
            for o in opts
        )
        buy_block = f"\n<b>Докупить</b> (разово, лимит сохранится):\n{buy_lines}\n"
    else:
        buy_block = f"\nДостигнут максимум — <b>{MAX_DEVICE_SLOTS}</b> устройств.\n"

    downgrade = ""
    if limit > 1:
        downgrade = (
            f"\nМожно <b>вернуть 1 устройство</b> бесплатно — "
            f"тогда продление снова <b>{BASE_MONTHLY_PRICE} ₽/мес</b>, "
            f"лишние привязки снимутся.\n"
        )

    return (
        f"💜 <b>Устройства</b>\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"Сейчас привязано: <b>{used} / {limit}</b>\n"
        f"База в тарифе — 1 устройство ({BASE_MONTHLY_PRICE} ₽/мес).\n"
        f"Первый доп. слот — {FIRST_EXTRA_SLOT_PRICE} ₽, каждый следующий +5 ₽.\n"
        f"{extras}"
        f"Ваше продление сейчас: <b>{month} ₽/мес</b>.\n"
        f"{buy_block}"
        f"{downgrade}\n"
        f"<b>Сброс привязок</b> — освобождает слоты (лимит и цена не меняются). "
        f"Нужно, если сменили телефон."
    )


def screen_devices_downgrade_confirm(user: User) -> str:
    from devices import BASE_MONTHLY_PRICE, monthly_price_for_user, user_device_limit

    return (
        f"💜 <b>Вернуть 1 устройство?</b>\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"Сейчас лимит <b>{user_device_limit(user)}</b>, "
        f"продление <b>{monthly_price_for_user(user)} ₽/мес</b>.\n\n"
        f"После подтверждения:\n"
        f"· лимит станет <b>1</b>\n"
        f"· продление — <b>{BASE_MONTHLY_PRICE} ₽/мес</b>\n"
        f"· лишние HWID снимутся\n"
        f"· деньги за прошлые доп. слоты не возвращаются\n\n"
        f"Подтвердите ниже."
    )


def screen_devices_downgrade_done(user: User) -> str:
    from devices import BASE_MONTHLY_PRICE, monthly_price_for_user, user_device_limit

    return (
        f"💜 <b>Лимит обновлён</b>\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"Устройства: лимит <b>{user_device_limit(user)}</b>\n"
        f"Продление: <b>{monthly_price_for_user(user)} ₽/мес</b> "
        f"(база {BASE_MONTHLY_PRICE} ₽).\n\n"
        f"Привяжите ключ заново на одном телефоне."
    )


def screen_hwid_reset_ok(user: User) -> str:
    from devices import monthly_price_for_user, user_device_limit

    return (
        f"💜 <b>Привязки сброшены</b>\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"HWID очищены. Лимит <b>{user_device_limit(user)}</b> и цена "
        f"<b>{monthly_price_for_user(user)} ₽/мес</b> не изменились.\n\n"
        f"Добавьте ключ заново в Happ / INCY / Happ Plus."
    )


def screen_access_short(user: User) -> str:
    badge, detail, _ = status_info(user)
    return (
        f"💜 <b>Ваш ключ</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🟢  {_esc(badge)} · {_esc(detail)}\n\n"
        f"Ключ — в следующем сообщении.\n"
        f"Нажмите на ссылку → «Копировать»."
    )


def screen_access_link(import_url: str) -> str:
    return (
        f"<b>🔑 Ключ · нажмите → Копировать:</b>\n"
        f"<code>{_esc(import_url)}</code>"
    )


def screen_docs() -> str:
    name = _esc(config.BOT_NAME)
    return (
        f"💜 <b>Документы · {name}</b>\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"Откройте нужный раздел кнопкой ниже."
    )


def screen_tariffs(user: User | None = None) -> str:
    from devices import FIRST_EXTRA_SLOT_PRICE, MAX_DEVICE_SLOTS, monthly_price_for_user, user_device_limit

    plan = _main_plan()
    name = _esc(config.BOT_NAME)
    if not plan:
        return f"💜 <b>Тарифы · {name}</b>\n\nВременно недоступно."
    month = monthly_price_for_user(user) if user else plan.price_rub
    limit = user_device_limit(user) if user else 1
    if config.payments_active:
        body = (
            f"<b>{_esc(plan.title)}</b> — <b>{month} ₽</b> с вашим лимитом устройств\n"
            f"База {plan.price_rub} ₽ (1 устр.) + доп. слоты (сейчас лимит <b>{limit}</b>)\n"
            f"Докупить слоты — «Доп. устройства»; вернуть 1 устр. — там же.\n"
            f"Доп. слот от <b>{FIRST_EXTRA_SLOT_PRICE} ₽</b>, макс. {MAX_DEVICE_SLOTS}.\n\n"
            f"«Оплатить» — безопасная оплата Platega."
        )
    else:
        body = (
            f"<b>{_esc(plan.title)}</b> — <b>{plan.price_rub} ₽</b>/мес\n"
            f"Сейчас доступ открыт без оплаты."
        )
    return (
        f"💜 <b>Тарифы · {name}</b>\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"{body}"
    )


def screen_order(plan: TariffPlan, *, amount: int | None = None, devices_note: str = "") -> str:
    price = amount if amount is not None else plan.price_rub
    extra = f"\n{devices_note}\n" if devices_note else "\n"
    return (
        f"💜 <b>Оплата</b>\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"Тариф: <b>{_esc(plan.title)}</b>\n"
        f"Сумма: <b>{price} ₽</b>{extra}"
        f"① «Перейти к оплате»\n"
        f"② Вернитесь → «Я оплатил»\n"
        f"③ «Мой ключ»"
    )


def screen_pay(plan: TariffPlan) -> str:
    return screen_order(plan)


def screen_pay_error() -> str:
    return (
        f"💜 <b>Ошибка оплаты</b>\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"Не удалось создать платёж. Попробуйте позже или напишите в поддержку."
    )


def screen_help() -> str:
    name = _esc(config.BOT_NAME)
    return (
        f"💜 <b>Инструкция · {name}</b>\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"<b>Быстрый способ</b>\n"
        f"«Мой ключ» → «Открыть в Happ / INCY / Happ Plus» — "
        f"приложение само подставит ключ.\n\n"
        f"<b>Вручную</b>\n"
        f"① «Мой ключ»\n"
        f"② Нажмите на ссылку → «Копировать»\n"
        f"③ В приложении: добавить подписку / вставить URL\n"
        f"④ Включите автообновление\n"
        f"⑤ Выберите сервер и подключитесь\n\n"
        f"<b>Устройства</b>\n"
        f"База — 1 устройство. Можно докупить до 5 — цена продления вырастет.\n"
        f"Сброс привязок — смена телефона без смены цены.\n"
        f"«Вернуть 1 устройство» — снова 69 ₽/мес.\n\n"
        f"Вопросы — «Поддержка»."
    )


def screen_payment_success(plan_title: str, user: User) -> str:
    from devices import monthly_price_for_user, user_device_limit

    badge, detail, _ = status_info(user)
    return (
        f"💜 <b>Оплата принята</b>\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"Тариф: {_esc(plan_title)}\n"
        f"🟢  {_esc(badge)} · {_esc(detail)}\n"
        f"📱  Лимит устройств: <b>{user_device_limit(user)}</b>\n"
        f"💎  Продление: <b>{monthly_price_for_user(user)} ₽/мес</b>\n\n"
        f"Откройте «Мой ключ» → Happ / INCY."
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


def format_tariffs_text() -> str:
    return screen_tariffs()


def format_order_text(plan: TariffPlan) -> str:
    return screen_order(plan)