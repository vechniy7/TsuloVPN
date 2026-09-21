"""Хранение пользователей и платежей в SQLite (диск Amvera /data)."""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import os
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

from config import config

logger = logging.getLogger(__name__)

_users_cache: list[User] | None = None
_users_cache_at: float = 0.0
_USERS_CACHE_TTL = 45.0

_db_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def _invalidate_users_cache() -> None:
    global _users_cache, _users_cache_at
    _users_cache = None
    _users_cache_at = 0.0


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
    last_seen_at: str | None = None
    sub_fetch_count: int = 0
    disabled: bool = False
    note: str | None = None
    bound_hwid: str | None = None
    hwid_bound_at: str | None = None
    device_limit: int | None = None
    bound_hwids: list | None = None


@dataclass
class PaymentOrder:
    order_id: str
    telegram_id: int
    plan_id: str
    amount: int
    bill_id: str | None
    status: str
    created_at: str


def _new_token() -> str:
    return uuid.uuid4().hex


def resolve_db_path() -> Path:
    """Amvera persistent disk = /data; локально — ./data рядом с кодом."""
    raw = (os.getenv("TSULO_DB_PATH") or config.TSULO_DB_PATH or "").strip()
    if raw:
        return Path(raw)
    amvera = Path("/data")
    if amvera.is_dir() and os.access(amvera, os.W_OK):
        return amvera / "tsulovpn.db"
    local = Path(__file__).resolve().parent / "data"
    local.mkdir(parents=True, exist_ok=True)
    return local / "tsulovpn.db"


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn
    path = resolve_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _conn = conn
    logger.info("SQLite database: %s", path)
    return conn


async def _run(func):
    return await asyncio.to_thread(func)


def _parse_user_dict(data: dict) -> User | None:
    if not data:
        return None
    data = dict(data)
    data.setdefault("expires_at", None)
    data.setdefault("plan", None)
    data.setdefault("last_seen_at", None)
    data.setdefault("sub_fetch_count", 0)
    data.setdefault("disabled", False)
    data.setdefault("note", None)
    data.setdefault("bound_hwid", None)
    data.setdefault("hwid_bound_at", None)
    data.setdefault("device_limit", None)
    data.setdefault("bound_hwids", None)
    try:
        data["telegram_id"] = int(data["telegram_id"])
    except (TypeError, ValueError, KeyError):
        return None
    try:
        data["sub_fetch_count"] = int(data.get("sub_fetch_count") or 0)
    except (TypeError, ValueError):
        data["sub_fetch_count"] = 0
    data["is_admin"] = bool(data.get("is_admin"))
    data["disabled"] = bool(data.get("disabled"))
    raw_limit = data.get("device_limit")
    if raw_limit is not None and raw_limit != "":
        try:
            data["device_limit"] = int(raw_limit)
        except (TypeError, ValueError):
            data["device_limit"] = None
    else:
        data["device_limit"] = None
    hwids = data.get("bound_hwids")
    if isinstance(hwids, str):
        try:
            hwids = json.loads(hwids)
        except json.JSONDecodeError:
            hwids = [hwids] if hwids.strip() else []
    if not isinstance(hwids, list):
        hwids = []
    hwids = [str(x).strip() for x in hwids if str(x).strip()]
    legacy = (data.get("bound_hwid") or "").strip()
    if legacy and legacy not in hwids:
        hwids.insert(0, legacy)
    data["bound_hwids"] = hwids or None
    data["bound_hwid"] = hwids[0] if hwids else None
    allowed = {f.name for f in fields(User)}
    return User(**{k: v for k, v in data.items() if k in allowed})


def _row_to_user(row: sqlite3.Row | None) -> User | None:
    if row is None:
        return None
    data = dict(row)
    return _parse_user_dict(data)


def _row_to_order(row: sqlite3.Row | None) -> PaymentOrder | None:
    if row is None:
        return None
    data = dict(row)
    try:
        data["telegram_id"] = int(data["telegram_id"])
        data["amount"] = int(data["amount"])
    except (TypeError, ValueError, KeyError):
        return None
    return PaymentOrder(
        order_id=str(data["order_id"]),
        telegram_id=data["telegram_id"],
        plan_id=str(data["plan_id"]),
        amount=data["amount"],
        bill_id=(str(data["bill_id"]) if data.get("bill_id") else None),
        status=str(data["status"]),
        created_at=str(data["created_at"]),
    )


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            subscription_token TEXT NOT NULL UNIQUE,
            registration_date TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            expires_at TEXT,
            plan TEXT,
            last_seen_at TEXT,
            sub_fetch_count INTEGER NOT NULL DEFAULT 0,
            disabled INTEGER NOT NULL DEFAULT 0,
            note TEXT,
            bound_hwid TEXT,
            hwid_bound_at TEXT,
            device_limit INTEGER,
            bound_hwids TEXT
        );
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            telegram_id INTEGER NOT NULL,
            plan_id TEXT NOT NULL,
            amount INTEGER NOT NULL,
            bill_id TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_orders_bill ON orders(bill_id);
        CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at DESC);
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    conn.commit()


def _user_to_params(user: User) -> tuple:
    hwids_json = json.dumps(user.bound_hwids, ensure_ascii=False) if user.bound_hwids else None
    return (
        int(user.telegram_id),
        user.full_name,
        user.username,
        user.subscription_token,
        user.registration_date,
        1 if user.is_admin else 0,
        user.expires_at,
        user.plan,
        user.last_seen_at,
        int(user.sub_fetch_count or 0),
        1 if user.disabled else 0,
        user.note,
        user.bound_hwid,
        user.hwid_bound_at,
        user.device_limit,
        hwids_json,
    )


def _upsert_user(conn: sqlite3.Connection, user: User) -> None:
    conn.execute(
        """
        INSERT INTO users (
            telegram_id, full_name, username, subscription_token, registration_date,
            is_admin, expires_at, plan, last_seen_at, sub_fetch_count, disabled, note,
            bound_hwid, hwid_bound_at, device_limit, bound_hwids
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            full_name=excluded.full_name,
            username=excluded.username,
            subscription_token=excluded.subscription_token,
            registration_date=excluded.registration_date,
            is_admin=excluded.is_admin,
            expires_at=excluded.expires_at,
            plan=excluded.plan,
            last_seen_at=excluded.last_seen_at,
            sub_fetch_count=excluded.sub_fetch_count,
            disabled=excluded.disabled,
            note=excluded.note,
            bound_hwid=excluded.bound_hwid,
            hwid_bound_at=excluded.hwid_bound_at,
            device_limit=excluded.device_limit,
            bound_hwids=excluded.bound_hwids
        """,
        _user_to_params(user),
    )


def _upsert_order(conn: sqlite3.Connection, order: PaymentOrder) -> None:
    conn.execute(
        """
        INSERT INTO orders (order_id, telegram_id, plan_id, amount, bill_id, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(order_id) DO UPDATE SET
            telegram_id=excluded.telegram_id,
            plan_id=excluded.plan_id,
            amount=excluded.amount,
            bill_id=excluded.bill_id,
            status=excluded.status,
            created_at=excluded.created_at
        """,
        (
            order.order_id,
            int(order.telegram_id),
            order.plan_id,
            int(order.amount),
            order.bill_id,
            order.status,
            order.created_at,
        ),
    )


def _meta_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row else None


def _meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def _seed_paths() -> list[Path]:
    here = Path(__file__).resolve().parent
    return [
        Path("/data/from_rdb.json.gz"),
        Path("/data/from_rdb.json"),
        here / "data_migrate" / "from_rdb.json.gz",
        here / "data_migrate" / "from_rdb.json",
    ]


def _load_seed_payload() -> dict | None:
    for path in _seed_paths():
        if not path.is_file():
            continue
        try:
            raw = path.read_bytes()
            if path.suffix == ".gz" or path.name.endswith(".json.gz"):
                raw = gzip.decompress(raw)
            payload = json.loads(raw.decode("utf-8"))
            if isinstance(payload, dict) and (
                payload.get("users") or payload.get("orders")
            ):
                logger.info("Loaded migration seed from %s", path)
                return payload
        except Exception as exc:
            logger.warning("Failed to read seed %s: %s", path, exc)
    return None


def _import_seed_if_needed(conn: sqlite3.Connection) -> None:
    if _meta_get(conn, "rdb_imported") == "1":
        return
    count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if int(count) > 0:
        _meta_set(conn, "rdb_imported", "1")
        conn.commit()
        return
    payload = _load_seed_payload()
    if not payload:
        logger.warning("SQLite empty and no RDB seed found — starting fresh")
        return

    users_raw = payload.get("users") or []
    orders_raw = payload.get("orders") or []
    imported_users = 0
    imported_orders = 0
    with conn:
        for item in users_raw:
            if not isinstance(item, dict):
                continue
            user = _parse_user_dict(item)
            if not user:
                continue
            _upsert_user(conn, user)
            imported_users += 1
        for item in orders_raw:
            if not isinstance(item, dict):
                continue
            try:
                order = PaymentOrder(
                    order_id=str(item["order_id"]),
                    telegram_id=int(item["telegram_id"]),
                    plan_id=str(item["plan_id"]),
                    amount=int(item["amount"]),
                    bill_id=(str(item["bill_id"]) if item.get("bill_id") else None),
                    status=str(item.get("status") or "pending"),
                    created_at=str(item.get("created_at") or datetime.now(timezone.utc).isoformat()),
                )
            except (KeyError, TypeError, ValueError):
                continue
            _upsert_order(conn, order)
            imported_orders += 1
        _meta_set(conn, "rdb_imported", "1")
        _meta_set(
            conn,
            "rdb_imported_at",
            datetime.now(timezone.utc).isoformat(),
        )
    logger.info(
        "Imported from Upstash RDB seed: %s users, %s orders",
        imported_users,
        imported_orders,
    )


async def init_db() -> None:
    def _init():
        with _db_lock:
            conn = _connect()
            _ensure_schema(conn)
            _import_seed_if_needed(conn)
            users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
            orders = conn.execute("SELECT COUNT(*) AS c FROM orders").fetchone()["c"]
            logger.info("SQLite ready (%s users, %s orders)", users, orders)

    await _run(_init)


async def get_user(telegram_id: int) -> User | None:
    def _get():
        with _db_lock:
            conn = _connect()
            row = conn.execute(
                "SELECT * FROM users WHERE telegram_id=?", (int(telegram_id),)
            ).fetchone()
            return _row_to_user(row)

    return await _run(_get)


async def get_user_by_token(token: str) -> User | None:
    def _get():
        with _db_lock:
            conn = _connect()
            row = conn.execute(
                "SELECT * FROM users WHERE subscription_token=?", (token,)
            ).fetchone()
            return _row_to_user(row)

    return await _run(_get)


async def save_user(user: User) -> User:
    def _save():
        with _db_lock:
            conn = _connect()
            _upsert_user(conn, user)
            conn.commit()

    await _run(_save)
    _invalidate_users_cache()
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
        with _db_lock:
            conn = _connect()
            # race: another request may have created the user
            row = conn.execute(
                "SELECT * FROM users WHERE telegram_id=?", (int(telegram_id),)
            ).fetchone()
            if row:
                return _row_to_user(row)
            _upsert_user(conn, user)
            conn.commit()
            return user

    created = await _run(_save)
    _invalidate_users_cache()
    logger.info("New user: %s (token %s…)", telegram_id, user.subscription_token[:8])
    return created or user


async def update_admins_status() -> None:
    def _update():
        with _db_lock:
            conn = _connect()
            admin_ids = set(config.ADMINS)
            rows = conn.execute("SELECT * FROM users").fetchall()
            updated = 0
            for row in rows:
                user = _row_to_user(row)
                if not user:
                    continue
                should_be = user.telegram_id in admin_ids
                if user.is_admin == should_be:
                    continue
                user.is_admin = should_be
                _upsert_user(conn, user)
                updated += 1
            if updated:
                conn.commit()
                logger.info("Admin flags updated for %s users", updated)

    await _run(_update)
    _invalidate_users_cache()


async def get_all_users(*, use_cache: bool = True) -> list[User]:
    global _users_cache, _users_cache_at
    import time as _time

    if use_cache and _users_cache is not None and (_time.monotonic() - _users_cache_at) < _USERS_CACHE_TTL:
        return list(_users_cache)

    def _all():
        with _db_lock:
            conn = _connect()
            rows = conn.execute(
                "SELECT * FROM users ORDER BY registration_date DESC"
            ).fetchall()
            users = []
            for row in rows:
                user = _row_to_user(row)
                if user:
                    users.append(user)
            return users

    users = await _run(_all)
    _users_cache = list(users)
    _users_cache_at = _time.monotonic()
    return list(users)


async def get_all_user_ids() -> list[int]:
    def _ids():
        with _db_lock:
            conn = _connect()
            rows = conn.execute("SELECT telegram_id FROM users").fetchall()
            return [int(r["telegram_id"]) for r in rows]

    return await _run(_ids)


async def get_user_count() -> int:
    def _count():
        with _db_lock:
            conn = _connect()
            return int(conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"])

    return await _run(_count)


async def save_payment_order(order: PaymentOrder) -> PaymentOrder:
    def _save():
        with _db_lock:
            conn = _connect()
            _upsert_order(conn, order)
            conn.commit()

    await _run(_save)
    return order


async def get_payment_order(order_id: str) -> PaymentOrder | None:
    def _get():
        with _db_lock:
            conn = _connect()
            row = conn.execute(
                "SELECT * FROM orders WHERE order_id=?", (order_id,)
            ).fetchone()
            return _row_to_order(row)

    return await _run(_get)


async def get_payment_order_by_bill(bill_id: str) -> PaymentOrder | None:
    def _get():
        with _db_lock:
            conn = _connect()
            row = conn.execute(
                "SELECT * FROM orders WHERE bill_id=? ORDER BY created_at DESC LIMIT 1",
                (bill_id,),
            ).fetchone()
            return _row_to_order(row)

    return await _run(_get)


async def mark_payment_order_paid(order_id: str) -> PaymentOrder | None:
    order = await get_payment_order(order_id)
    if not order:
        return None
    if order.status == "paid":
        return order
    order.status = "paid"
    return await save_payment_order(order)


async def get_all_orders(*, limit: int = 200) -> list[PaymentOrder]:
    def _all():
        with _db_lock:
            conn = _connect()
            rows = conn.execute(
                "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
            orders = []
            for row in rows:
                order = _row_to_order(row)
                if order:
                    orders.append(order)
            return orders

    return await _run(_all)


async def touch_subscription_fetch(telegram_id: int) -> None:
    def _touch():
        with _db_lock:
            conn = _connect()
            row = conn.execute(
                "SELECT * FROM users WHERE telegram_id=?", (int(telegram_id),)
            ).fetchone()
            user = _row_to_user(row)
            if not user:
                return
            user.last_seen_at = datetime.now(timezone.utc).isoformat()
            user.sub_fetch_count = int(user.sub_fetch_count or 0) + 1
            _upsert_user(conn, user)
            conn.commit()

    await _run(_touch)


async def regenerate_user_token(telegram_id: int) -> User | None:
    def _regen():
        with _db_lock:
            conn = _connect()
            row = conn.execute(
                "SELECT * FROM users WHERE telegram_id=?", (int(telegram_id),)
            ).fetchone()
            user = _row_to_user(row)
            if not user:
                return None
            user.subscription_token = _new_token()
            user.bound_hwid = None
            user.bound_hwids = None
            user.hwid_bound_at = None
            _upsert_user(conn, user)
            conn.commit()
            return user

    user = await _run(_regen)
    _invalidate_users_cache()
    return user


def normalize_client_hwid(raw: str | None) -> str:
    if not raw or not isinstance(raw, str):
        return ""
    import re

    hwid = re.sub(r"[^a-zA-Z0-9=\-_.:]", "", raw.strip())
    return hwid[:128]


async def check_and_bind_hwid(telegram_id: int, client_hwid: str) -> tuple[User | None, str | None]:
    from devices import bound_hwid_list, user_device_limit

    hwid = normalize_client_hwid(client_hwid)
    if not config.DEVICE_LIMIT_ENABLED:
        return await get_user(telegram_id), None

    def _check():
        with _db_lock:
            conn = _connect()
            row = conn.execute(
                "SELECT * FROM users WHERE telegram_id=?", (int(telegram_id),)
            ).fetchone()
            user = _row_to_user(row)
            if not user:
                return None, "not_found", False
            if not hwid:
                return user, None, False
            limit = user_device_limit(user)
            if limit <= 0:
                return user, None, False
            hwids = bound_hwid_list(user)
            if hwid in hwids:
                return user, None, False
            if len(hwids) >= limit:
                return user, "hwid_limit", False
            hwids.append(hwid)
            user.bound_hwids = hwids
            user.bound_hwid = hwids[0]
            user.hwid_bound_at = datetime.now(timezone.utc).isoformat()
            _upsert_user(conn, user)
            conn.commit()
            return user, None, True

    user, reason, changed = await _run(_check)
    if changed:
        _invalidate_users_cache()
    return user, reason


async def reset_user_hwid(telegram_id: int) -> User | None:
    def _reset():
        with _db_lock:
            conn = _connect()
            row = conn.execute(
                "SELECT * FROM users WHERE telegram_id=?", (int(telegram_id),)
            ).fetchone()
            user = _row_to_user(row)
            if not user:
                return None
            user.bound_hwid = None
            user.bound_hwids = None
            user.hwid_bound_at = None
            _upsert_user(conn, user)
            conn.commit()
            return user

    user = await _run(_reset)
    _invalidate_users_cache()
    return user


async def set_user_device_limit(telegram_id: int, limit: int) -> User | None:
    from devices import bound_hwid_list, clamp_device_limit

    def _set():
        with _db_lock:
            conn = _connect()
            row = conn.execute(
                "SELECT * FROM users WHERE telegram_id=?", (int(telegram_id),)
            ).fetchone()
            user = _row_to_user(row)
            if not user:
                return None
            user.device_limit = clamp_device_limit(limit)
            hwids = bound_hwid_list(user)
            if len(hwids) > user.device_limit:
                hwids = hwids[: user.device_limit]
                user.bound_hwids = hwids or None
                user.bound_hwid = hwids[0] if hwids else None
            _upsert_user(conn, user)
            conn.commit()
            return user

    user = await _run(_set)
    _invalidate_users_cache()
    return user
