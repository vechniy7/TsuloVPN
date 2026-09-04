"""Лимит устройств и цены за доп. слоты."""

from __future__ import annotations

from config import config

# Базовый тариф включает 1 устройство. Доп. слоты 2..5:
# слот 2 = 35 ₽, каждый следующий +5 ₽.
BASE_DEVICE_SLOTS = 1
MAX_DEVICE_SLOTS = 5
FIRST_EXTRA_SLOT_PRICE = 35
EXTRA_SLOT_STEP = 5
BASE_MONTHLY_PRICE = 69


def default_device_limit() -> int:
    raw = int(config.DEVICE_LIMIT or BASE_DEVICE_SLOTS)
    return max(BASE_DEVICE_SLOTS, min(MAX_DEVICE_SLOTS, raw))


def clamp_device_limit(value: int | None) -> int:
    try:
        n = int(value if value is not None else default_device_limit())
    except (TypeError, ValueError):
        n = default_device_limit()
    return max(BASE_DEVICE_SLOTS, min(MAX_DEVICE_SLOTS, n))


def user_device_limit(user) -> int:
    if user is None:
        return default_device_limit()
    raw = getattr(user, "device_limit", None)
    if raw is None:
        return default_device_limit()
    return clamp_device_limit(raw)


def bound_hwid_list(user) -> list[str]:
    if user is None:
        return []
    items = getattr(user, "bound_hwids", None)
    if isinstance(items, list) and items:
        return [str(x).strip() for x in items if str(x).strip()]
    legacy = (getattr(user, "bound_hwid", None) or "").strip()
    return [legacy] if legacy else []


def slot_price(slot_number: int) -> int:
    """Цена за конкретный слот (2 → 35, 3 → 40, …)."""
    if slot_number <= BASE_DEVICE_SLOTS:
        return 0
    return FIRST_EXTRA_SLOT_PRICE + (slot_number - 2) * EXTRA_SLOT_STEP


def cost_to_add_slots(current_limit: int, add: int) -> int:
    current = clamp_device_limit(current_limit)
    add = max(0, int(add))
    target = min(MAX_DEVICE_SLOTS, current + add)
    return sum(slot_price(slot) for slot in range(current + 1, target + 1))


def monthly_price_for_limit(device_limit: int) -> int:
    limit = clamp_device_limit(device_limit)
    return BASE_MONTHLY_PRICE + sum(
        slot_price(slot) for slot in range(BASE_DEVICE_SLOTS + 1, limit + 1)
    )


def monthly_price_for_user(user) -> int:
    return monthly_price_for_limit(user_device_limit(user))


def parse_device_addon_plan(plan_id: str | None) -> int | None:
    """plan_id вида dev+1 / dev+2 / dev+3 → число слотов."""
    if not plan_id or not plan_id.startswith("dev+"):
        return None
    try:
        n = int(plan_id[4:].strip())
    except ValueError:
        return None
    if n < 1 or n > (MAX_DEVICE_SLOTS - BASE_DEVICE_SLOTS):
        return None
    return n


def device_addon_plan_id(add: int) -> str:
    return f"dev+{int(add)}"


def can_add_slots(user, add: int) -> bool:
    add = int(add)
    if add < 1:
        return False
    return user_device_limit(user) + add <= MAX_DEVICE_SLOTS


def addon_options(user) -> list[dict]:
    """Доступные пакеты +1/+2/+3 с ценой."""
    current = user_device_limit(user)
    free = MAX_DEVICE_SLOTS - current
    options = []
    for add in (1, 2, 3):
        if add > free:
            continue
        options.append(
            {
                "add": add,
                "plan_id": device_addon_plan_id(add),
                "price_rub": cost_to_add_slots(current, add),
                "new_limit": current + add,
            }
        )
    return options
