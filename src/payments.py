from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from config import config
from database import PaymentOrder, User, get_payment_order, get_user, mark_payment_order_paid, save_payment_order, save_user


@dataclass(frozen=True)
class TariffPlan:
    id: str
    title: str
    months: int
    price_rub: int


# Единственный тариф сервиса. Доступ сейчас бесплатный (PAYMENTS_ENFORCE=false).
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


async def process_cardlink_payment(
    *,
    order_id: str,
    telegram_id: int,
    plan_id: str,
) -> tuple[User | None, TariffPlan | None, bool]:
    plan = get_plan(plan_id)
    if not plan:
        return None, None, False

    order = await get_payment_order(order_id)
    if order and order.status == "paid":
        user = await get_user(telegram_id)
        return user, plan, False

    user = await get_user(telegram_id)
    if not user:
        return None, plan, False

    user = await extend_subscription(user, plan_id)
    await mark_payment_order_paid(order_id)
    return user, plan, True


async def try_activate_from_bill(bill_id: str) -> tuple[User | None, TariffPlan | None, bool]:
    from cardlink import get_bill_status
    from database import get_payment_order_by_bill

    status = await get_bill_status(bill_id)
    if status != "SUCCESS":
        return None, None, False

    order = await get_payment_order_by_bill(bill_id)
    if not order:
        return None, None, False

    return await process_cardlink_payment(
        order_id=order.order_id,
        telegram_id=order.telegram_id,
        plan_id=order.plan_id,
    )
