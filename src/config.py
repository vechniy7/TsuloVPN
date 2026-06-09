import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

load_dotenv()


class Config(BaseModel):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMINS: list[int] = Field(default_factory=list)
    BOT_NAME: str = os.getenv("BOT_NAME", "TsuloVPN")

    # Публичный URL подписок (должен быть HTTPS для Hiddify / Happ)
    SUBSCRIPTION_PUBLIC_URL: str = os.getenv("SUBSCRIPTION_PUBLIC_URL", "https://your-domain.com")
    # Render.com передаёт PORT; локально по умолчанию 8080
    SUBSCRIPTION_PORT: int = Field(
        default=int(os.getenv("PORT", os.getenv("SUBSCRIPTION_PORT", "8080")))
    )

    # Источники goida-vpn-configs (рекомендованные + обход белых списков)
    GOIDA_RAW_BASE: str = os.getenv(
        "GOIDA_RAW_BASE",
        "https://github.com/AvenCores/goida-vpn-configs/raw/refs/heads/main/githubmirror",
    )
    REGULAR_SOURCE_IDS: list[int] = Field(default_factory=lambda: [1, 6, 22, 23, 24, 25])
    WHITELIST_SOURCE_ID: int = int(os.getenv("WHITELIST_SOURCE_ID", "26"))

    TARGET_REGULAR_COUNT: int = int(os.getenv("TARGET_REGULAR_COUNT", "25"))
    TARGET_WHITELIST_COUNT: int = int(os.getenv("TARGET_WHITELIST_COUNT", "7"))
    MAX_HEALTH_CHECK_CANDIDATES: int = int(os.getenv("MAX_HEALTH_CHECK_CANDIDATES", "600"))

    POOL_REFRESH_INTERVAL: int = int(os.getenv("POOL_REFRESH_INTERVAL", "600"))
    HEALTH_CHECK_TIMEOUT: float = float(os.getenv("HEALTH_CHECK_TIMEOUT", "6.0"))
    HEALTH_CHECK_CONCURRENCY: int = int(os.getenv("HEALTH_CHECK_CONCURRENCY", "60"))
    FETCH_TIMEOUT: int = int(os.getenv("FETCH_TIMEOUT", "20"))

    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///tsulovpn.db")

    @field_validator("ADMINS", mode="before")
    @classmethod
    def parse_admins(cls, value):
        if isinstance(value, str):
            return [int(admin) for admin in value.split(",") if admin.strip()]
        return value or []

    @property
    def target_total_count(self) -> int:
        return self.TARGET_REGULAR_COUNT + self.TARGET_WHITELIST_COUNT

    def subscription_url_for_token(self, token: str) -> str:
        base = self.SUBSCRIPTION_PUBLIC_URL.rstrip("/")
        return f"{base}/sub/{token}"


config = Config(ADMINS=os.getenv("ADMINS", ""))
