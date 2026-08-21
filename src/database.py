import asyncio
import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from config import config

logger = logging.getLogger(__name__)

PREFIX = "tsulovpn"
USERS_SET = f"{PREFIX}:users"
ORDERS_PREFIX = f"{PREFIX}:order"

_redis = None


@dataclass
class User:
    telegram_id: int
    full_name: str | None
    username: str | None
    subscription_token: str
    registration_date: str
    is_admin: bool = False
    expires_at: str | None = None
    plan: str | None = None


@dataclass
class PaymentOrder:
    order_id: str
    telegram_id: int
    plan_id: str
    amount: int
    bill_id: str | None
    status: str
    created_at: str


def _user_key(telegram_id: int) -> str:
    return f"{PREFIX}:user:{telegram_id}"


def _token_key(token: str) -> str:
    return f"{PREFIX}:token:{token}"


def _order_key(order_id: str) -> str:
    return f"{ORDERS_PREFIX}:{order_id}"


def _bill_order_key(bill_id: str) -> str:
    return f"{ORDERS_PREFIX}:bill:{bill_id}"


def _new_token() -> str:
    return uuid.uuid4().hex


def _get_redis():
    global _redis
    if _redis is None:
        if not config.use_upstash:
            raise RuntimeError("UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN are required")
        from upstash_redis import Redis

        _redis = Redis(url=config.UPSTASH_REDIS_REST_URL, token=config.UPSTASH_REDIS_REST_TOKEN)
    return _redis


async def _run(func):
    return await asyncio.to_thread(func)


def _parse_user(raw: str | bytes | None) -> User | None:
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    data = json.loads(raw)
    data.setdefault("expires_at", None)
    data.setdefault("plan", None)
    return User(**data)


async def init_db() -> None:
    if not config.use_upstash:
        logger.error("Upstash Redis is not configured — users will not persist!")
        return

    def _ping():
        try:
            _get_redis().ping()
        except Exception as exc:
            url = config.UPSTASH_REDIS_REST_URL
            hint = "https://YOUR-DB.upstash.io"
            raise RuntimeError(
                f"Upstash Redis ping failed ({exc}). "
                f"Check UPSTASH_REDIS_REST_URL (must start with https://, e.g. {hint}) "
                "and UPSTASH_REDIS_REST_TOKEN on Render."
            ) from exc

    await _run(_ping)
    logger.info("Upstash Redis connected")


async def get_user(telegram_id: int) -> User | None:
    def _get():
        return _parse_user(_get_redis().get(_user_key(telegram_id)))

    return await _run(_get)


async def get_user_by_token(token: str) -> User | None:
    def _get():
        redis = _get_redis()
        telegram_id = redis.get(_token_key(token))
        if not telegram_id:
            return None
        return _parse_user(redis.get(_user_key(int(telegram_id))))

    return await _run(_get)


async def save_user(user: User) -> User:
    def _save():
        redis = _get_redis()
        redis.set(_user_key(user.telegram_id), json.dumps(asdict(user), ensure_ascii=False))

    await _run(_save)
    return user


async def create_user(
    telegram_id: int,
    full_name: str,
    username: str | None = None,
    is_admin: bool = False,
) -> User:
    existing = await get_user(telegram_id)
    if existing:
        return existing

    user = User(
        telegram_id=telegram_id,
        full_name=full_name,
        username=username,
        subscription_token=_new_token(),
        registration_date=datetime.now(timezone.utc).isoformat(),
        is_admin=is_admin,
    )

    def _save():
        redis = _get_redis()
        payload = json.dumps(asdict(user), ensure_ascii=False)
        redis.set(_user_key(telegram_id), payload)
        redis.set(_token_key(user.subscription_token), str(telegram_id))
        redis.sadd(USERS_SET, str(telegram_id))

    await _run(_save)
    logger.info("New user: %s (token %s…)", telegram_id, user.subscription_token[:8])
    return user


async def update_admins_status() -> None:
    if not config.use_upstash:
        return

    def _update():
        redis = _get_redis()
        admin_ids = set(config.ADMINS)
        for tid_raw in redis.smembers(USERS_SET):
            telegram_id = int(tid_raw)
            user = _parse_user(redis.get(_user_key(telegram_id)))
            if not user:
                continue
            user.is_admin = telegram_id in admin_ids
            redis.set(_user_key(telegram_id), json.dumps(asdict(user), ensure_ascii=False))

    await _run(_update)


async def get_all_users() -> list[User]:
    def _all():
        redis = _get_redis()
        users: list[User] = []
        for tid_raw in redis.smembers(USERS_SET):
            user = _parse_user(redis.get(_user_key(int(tid_raw))))
            if user:
                users.append(user)
        users.sort(key=lambda item: item.registration_date, reverse=True)
        return users

    return await _run(_all)


async def get_all_user_ids() -> list[int]:
    """ID всех пользователей — один запрос к Redis (для рассылки)."""

    def _ids():
        redis = _get_redis()
        result: list[int] = []
        for tid_raw in redis.smembers(USERS_SET):
            if isinstance(tid_raw, bytes):
                tid_raw = tid_raw.decode()
            try:
                result.append(int(tid_raw))
            except (TypeError, ValueError):
                continue
        return result

    return await _run(_ids)


async def get_user_count() -> int:
    def _count():
        return int(_get_redis().scard(USERS_SET) or 0)

    return await _run(_count)


def _parse_order(raw: str | bytes | None) -> PaymentOrder | None:
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    return PaymentOrder(**json.loads(raw))


async def save_payment_order(order: PaymentOrder) -> PaymentOrder:
    def _save():
        redis = _get_redis()
        payload = json.dumps(asdict(order), ensure_ascii=False)
        redis.set(_order_key(order.order_id), payload)
        if order.bill_id:
            redis.set(_bill_order_key(order.bill_id), order.order_id)

    await _run(_save)
    return order


async def get_payment_order(order_id: str) -> PaymentOrder | None:
    def _get():
        return _parse_order(_get_redis().get(_order_key(order_id)))

    return await _run(_get)


async def get_payment_order_by_bill(bill_id: str) -> PaymentOrder | None:
    def _get():
        redis = _get_redis()
        order_id = redis.get(_bill_order_key(bill_id))
        if not order_id:
            return None
        if isinstance(order_id, bytes):
            order_id = order_id.decode()
        return _parse_order(redis.get(_order_key(order_id)))

    return await _run(_get)


async def mark_payment_order_paid(order_id: str) -> PaymentOrder | None:
    order = await get_payment_order(order_id)
    if not order:
        return None
    if order.status == "paid":
        return order
    order.status = "paid"
    return await save_payment_order(order)
