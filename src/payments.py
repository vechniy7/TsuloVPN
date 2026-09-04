from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from config import config
from database import PaymentOrder, User, get_payment_order, get_user, mark_payment_order_paid, save_payment_order, save_user
from devices import (
    clamp_device_limit,
    monthly_price_for_user,
    parse_device_addon_plan,
    user_device_limit,
)


@dataclass(frozen=True)
class TariffPlan:
    id: str
    title: str
    months: int
    price_rub: int


# Единственный базовый тариф: 69 ₽ / месяц (1 устройство).
PLANS: dict[str, TariffPlan] = {
    "1m": TariffPlan(id="1m", title="1 месяц", months=1, price_rub=69),
}


def get_plan(plan_id: str) -> TariffPlan | None:
    return PLANS.get(plan_id)


def format_tariffs_text() -> str:
    from ui import screen_tariffs

    return screen_tariffs()


def format_order_text(plan: TariffPlan) -> str:
    from ui import screen_order

    return screen_order(plan)


def format_access_until(user: User) -> str:
    from ui import format_access_until as _fmt

    return _fmt(user)


def is_subscription_active(user: User) -> bool:
    if not config.payments_active:
        return True
    if not user.expires_at:
        return False
    try:
        expires = datetime.fromisoformat(user.expires_at)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires > datetime.now(timezone.utc)
    except ValueError:
        return True


async def extend_subscription(user: User, plan_id: str) -> User:
    plan = get_plan(plan_id)
    if not plan:
        raise ValueError(f"Unknown plan: {plan_id}")

    now = datetime.now(timezone.utc)
    if user.expires_at:
        try:
            current = datetime.fromisoformat(user.expires_at)
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)
            base = current if current > now else now
        except ValueError:
            base = now
    else:
        base = now

    user.expires_at = (base + timedelta(days=plan.months * 30)).isoformat()
    user.plan = plan_id
    return await save_user(user)


async def apply_device_addon(user: User, add: int) -> User:
    add = int(add)
    current = user_device_limit(user)
    user.device_limit = clamp_device_limit(current + add)
    return await save_user(user)


async def create_pending_order(
    *,
    order_id: str,
    telegram_id: int,
    plan_id: str,
    amount: int,
    bill_id: str,
) -> PaymentOrder:
    order = PaymentOrder(
        order_id=order_id,
        telegram_id=telegram_id,
        plan_id=plan_id,
        amount=amount,
        bill_id=bill_id,
        status="pending",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    return await save_payment_order(order)


async def process_payment(
    *,
    order_id: str,
    telegram_id: int,
    plan_id: str,
) -> tuple[User | None, TariffPlan | None, bool]:
    order = await get_payment_order(order_id)
    if order and order.status == "paid":
        user = await get_user(telegram_id)
        plan = get_plan(plan_id) or (
            TariffPlan(id=plan_id, title="Устройства", months=0, price_rub=order.amount)
            if parse_device_addon_plan(plan_id)
            else None
        )
        return user, plan, False

    user = await get_user(telegram_id)
    if not user:
        return None, get_plan(plan_id), False

    addon = parse_device_addon_plan(plan_id)
    if addon is not None:
        user = await apply_device_addon(user, addon)
        await mark_payment_order_paid(order_id)
        title = f"+{addon} устройств" if addon > 1 else "+1 устройство"
        amount = order.amount if order else 0
        fake = TariffPlan(id=plan_id, title=title, months=0, price_rub=amount)
        return user, fake, True

    plan = get_plan(plan_id)
    if not plan:
        return None, None, False

    user = await extend_subscription(user, plan_id)
    await mark_payment_order_paid(order_id)
    return user, plan, True


# Alias for legacy Cardlink routes
process_cardlink_payment = process_payment


async def try_activate_from_bill(bill_id: str) -> tuple[User | None, TariffPlan | None, bool]:
    from database import get_payment_order_by_bill

    order = await get_payment_order_by_bill(bill_id)
    if not order:
        return None, None, False

    if config.use_platega:
        from platega import get_transaction_status

        status = await get_transaction_status(bill_id)
        if status == "CONFIRMED":
            return await process_payment(
                order_id=order.order_id,
                telegram_id=order.telegram_id,
                plan_id=order.plan_id,
            )

    if config.use_cardlink:
        from cardlink import get_bill_status

        status = await get_bill_status(bill_id)
        if status == "SUCCESS":
            return await process_payment(
                order_id=order.order_id,
                telegram_id=order.telegram_id,
                plan_id=order.plan_id,
            )

    return None, None, False


def renewal_amount_for_user(user: User | None) -> int:
    """Сумма продления с учётом купленных слотов устройств."""
    return monthly_price_for_user(user)
