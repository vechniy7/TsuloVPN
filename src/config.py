import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

load_dotenv()

IGARECK_RAW = "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main"
RJSXRD_RAW = "https://raw.githubusercontent.com/whoahaow/rjsxrd/refs/heads/main"


class Config(BaseModel):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMINS: list[int] = Field(default_factory=list)
    BOT_NAME: str = os.getenv("BOT_NAME", "TsuloVPN")

    SUBSCRIPTION_PUBLIC_URL: str = os.getenv("SUBSCRIPTION_PUBLIC_URL", "https://your-domain.com")
    SUBSCRIPTION_PORT: int = Field(
        default=int(os.getenv("PORT", os.getenv("SUBSCRIPTION_PORT", "8080")))
    )

    # Обход белых списков
    WHITELIST_SOURCE_URLS: list[str] = Field(
        default_factory=lambda: [
            f"{RJSXRD_RAW}/githubmirror/bypass/bypass-all.txt",
            f"{IGARECK_RAW}/WHITE-CIDR-RU-all.txt",
            f"{IGARECK_RAW}/Vless-Reality-White-Lists-Rus-Mobile.txt",
        ]
    )

    # Обычный VPN
    REGULAR_SOURCE_URLS: list[str] = Field(
        default_factory=lambda: [
            f"{IGARECK_RAW}/BLACK_VLESS_RUS_mobile.txt",
        ]
    )

    TARGET_REGULAR_COUNT: int = int(os.getenv("TARGET_REGULAR_COUNT", "250"))
    TARGET_WHITELIST_COUNT: int = int(os.getenv("TARGET_WHITELIST_COUNT", "250"))

    # Автообновление пула при изменении источников (секунды)
    POOL_REFRESH_INTERVAL: int = int(os.getenv("POOL_REFRESH_INTERVAL", "1800"))
    FETCH_TIMEOUT: int = int(os.getenv("FETCH_TIMEOUT", "45"))
    FETCH_CONCURRENCY: int = int(os.getenv("FETCH_CONCURRENCY", "6"))

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

    @property
    def miniapp_url(self) -> str:
        return f"{self.SUBSCRIPTION_PUBLIC_URL.rstrip('/')}/miniapp/"


config = Config(ADMINS=os.getenv("ADMINS", ""))
