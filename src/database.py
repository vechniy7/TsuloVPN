import json
import logging
import os
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, create_engine, func, text
from sqlalchemy.orm import declarative_base, sessionmaker

from config import config

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DB_PATH = os.path.join(_PROJECT_ROOT, "tsulovpn.db")

logger = logging.getLogger(__name__)

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False, index=True)
    full_name = Column(String)
    username = Column(String)
    subscription_token = Column(String, unique=True, nullable=False, index=True)
    registration_date = Column(DateTime, default=datetime.utcnow)
    is_admin = Column(Boolean, default=False)
    personal_bypass_uris = Column(Text, default="[]")
    personal_bypass_latencies = Column(Text, default="[]")
    personal_bypass_updated_at = Column(DateTime, nullable=True)


def _resolve_database_url() -> str:
    url = config.DATABASE_URL
    if url == "sqlite:///tsulovpn.db":
        return f"sqlite:///{_DEFAULT_DB_PATH}"
    return url


engine = create_engine(_resolve_database_url(), echo=False)
Session = sessionmaker(bind=engine)


def _migrate_users_table() -> None:
    """Добавляет колонки персонального обхода в существующую SQLite БД."""
    if not config.DATABASE_URL.startswith("sqlite"):
        return
    migrations = [
        ("personal_bypass_uris", "TEXT DEFAULT '[]'"),
        ("personal_bypass_latencies", "TEXT DEFAULT '[]'"),
        ("personal_bypass_updated_at", "DATETIME"),
    ]
    with engine.connect() as conn:
        existing = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()
        }
        for column, col_type in migrations:
            if column not in existing:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {column} {col_type}"))
                logger.info("Migration: added users.%s", column)
        conn.commit()


async def init_db() -> None:
    Base.metadata.create_all(engine)
    _migrate_users_table()
    logger.info("Database initialized")


def _new_token() -> str:
    return uuid.uuid4().hex


async def get_user(telegram_id: int) -> User | None:
    with Session() as session:
        return session.query(User).filter_by(telegram_id=telegram_id).first()


async def get_user_by_token(token: str) -> User | None:
    with Session() as session:
        return session.query(User).filter_by(subscription_token=token).first()


async def create_user(
    telegram_id: int,
    full_name: str,
    username: str | None = None,
    is_admin: bool = False,
) -> User:
    with Session() as session:
        user = User(
            telegram_id=telegram_id,
            full_name=full_name,
            username=username,
            subscription_token=_new_token(),
            is_admin=is_admin,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        logger.info("New user: %s", telegram_id)
        return user


async def save_personal_bypass(
    telegram_id: int,
    uris: list[str],
    latencies: list[int],
) -> User | None:
    with Session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            return None
        user.personal_bypass_uris = json.dumps(uris, ensure_ascii=False)
        user.personal_bypass_latencies = json.dumps(latencies)
        user.personal_bypass_updated_at = datetime.utcnow()
        session.commit()
        session.refresh(user)
        logger.info("Saved %s personal bypass configs for user %s", len(uris), telegram_id)
        return user


def get_personal_bypass_uris(user: User) -> list[str]:
    if not user.personal_bypass_uris:
        return []
    try:
        data = json.loads(user.personal_bypass_uris)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def has_personal_bypass(user: User) -> bool:
    return len(get_personal_bypass_uris(user)) > 0


async def get_all_users() -> list[User]:
    with Session() as session:
        return session.query(User).order_by(User.registration_date.desc()).all()


async def get_user_count() -> int:
    with Session() as session:
        return session.query(func.count(User.id)).scalar() or 0
