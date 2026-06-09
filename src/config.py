import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

load_dotenv()


class Config(BaseModel):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMINS: list[int] = Field(default_factory=list)
    BOT_NAME: str = os.getenv("BOT_NAME", "TsuloVPN")

    SUBSCRIPTION_PUBLIC_URL: str = os.getenv("SUBSCRIPTION_PUBLIC_URL", "https://your-domain.com")
    SUBSCRIPTION_PORT: int = Field(
        default=int(os.getenv("PORT", os.getenv("SUBSCRIPTION_PORT", "8080")))
    )

    # igareck/vpn-configs-for-russia — конфиги проверяются на сервере в РФ
    IGARECK_RAW_BASE: str = os.getenv(
        "IGARECK_RAW_BASE",
        "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main",
    )

    # Обычный VPN (чёрные списки) — mobile TOP-150, уже отфильтрованы автором
    REGULAR_SOURCES: list[str] = Field(
        default_factory=lambda: [
            "BLACK_VLESS_RUS_mobile.txt",
            "BLACK_VLESS_RUS.txt",
        ]
    )

    # Обход белых списков — mobile TOP-150, проверены пользователем
    WHITELIST_SOURCES: list[str] = Field(
        default_factory=lambda: [
            "Vless-Reality-White-Lists-Rus-Mobile.txt",
            "Vless-Reality-White-Lists-Rus-Mobile-2.txt",
            "WHITE-CIDR-RU-checked.txt",
        ]
    )

    TARGET_REGULAR_COUNT: int = int(os.getenv("TARGET_REGULAR_COUNT", "25"))
    TARGET_WHITELIST_COUNT: int = int(os.getenv("TARGET_WHITELIST_COUNT", "7"))

    # igareck уже тестирует с РФ — доп. проверка с Render обычно не нужна
    SKIP_HEALTH_CHECK: bool = os.getenv("SKIP_HEALTH_CHECK", "true").lower() == "true"
    POOL_REFRESH_INTERVAL: int = int(os.getenv("POOL_REFRESH_INTERVAL", "3600"))
    HEALTH_CHECK_TIMEOUT: float = float(os.getenv("HEALTH_CHECK_TIMEOUT", "5.0"))
    HEALTH_CHECK_CONCURRENCY: int = int(os.getenv("HEALTH_CHECK_CONCURRENCY", "40"))
    MAX_HEALTH_CHECK_CANDIDATES: int = int(os.getenv("MAX_HEALTH_CHECK_CANDIDATES", "80"))
    FETCH_TIMEOUT: int = int(os.getenv("FETCH_TIMEOUT", "25"))

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
