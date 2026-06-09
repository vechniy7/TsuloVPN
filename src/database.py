import logging
import os
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, create_engine, func
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


def _resolve_database_url() -> str:
    url = config.DATABASE_URL
    if url == "sqlite:///tsulovpn.db":
        return f"sqlite:///{_DEFAULT_DB_PATH}"
    return url


engine = create_engine(_resolve_database_url(), echo=False)
Session = sessionmaker(bind=engine)


async def init_db() -> None:
    Base.metadata.create_all(engine)
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


async def get_all_users() -> list[User]:
    with Session() as session:
        return session.query(User).order_by(User.registration_date.desc()).all()


async def get_user_count() -> int:
    with Session() as session:
        return session.query(func.count(User.id)).scalar() or 0
