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

    CONFIG_RAW_BASE: str = (
        os.getenv("CONFIG_RAW_BASE")
        or os.getenv("IGARECK_RAW_BASE")  # совместимость со старым деплоем
        or "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main"
    )

    # Обычный VPN (чёрные списки) — mobile TOP-150, уже отфильтрованы автором
    REGULAR_SOURCES: list[str] = Field(
        default_factory=lambda: [
            "BLACK_VLESS_RUS_mobile.txt",
            "BLACK_VLESS_RUS.txt",
        ]
    )

    # Обход белых списков — только bypass-all.txt
    BYPASS_SOURCE_URL: str = os.getenv(
        "BYPASS_SOURCE_URL",
        "https://raw.githubusercontent.com/whoahaow/rjsxrd/main/githubmirror/bypass/bypass-all.txt",
    )

    TARGET_REGULAR_COUNT: int = int(os.getenv("TARGET_REGULAR_COUNT", "20"))
    TARGET_WHITELIST_COUNT: int = int(os.getenv("TARGET_WHITELIST_COUNT", "15"))

    # SNI/паттерны, которые чаще всего работают на мобильном БС (Мегафон и др.)
    WHITELIST_PRIORITY_SNIS: list[str] = Field(
        default_factory=lambda: [
            "loadtest.dev.urent.ru",
            "sfera.x5.ru",
            "www.vk.com",
            "top707762634.mwscdn.ru",
        ]
    )
    WHITELIST_PER_PRIORITY_SNI: int = int(os.getenv("WHITELIST_PER_PRIORITY_SNI", "3"))

    SKIP_HEALTH_CHECK: bool = os.getenv("SKIP_HEALTH_CHECK", "false").lower() == "true"
    # Reality/grpc/ws не проходят TLS-проверку с датацентра — только TCP для БС
    WHITELIST_TCP_ONLY_CHECK: bool = os.getenv("WHITELIST_TCP_ONLY_CHECK", "true").lower() == "true"
    # Не отсекать БС при обновлении подписки в Happ (проверка только на телефоне)
    WHITELIST_SKIP_VERIFY_ON_SUBSCRIBE: bool = (
        os.getenv("WHITELIST_SKIP_VERIFY_ON_SUBSCRIBE", "true").lower() == "true"
    )
    VERIFY_ON_SUBSCRIBE: bool = os.getenv("VERIFY_ON_SUBSCRIBE", "true").lower() == "true"
    VERIFY_CACHE_TTL: int = int(os.getenv("VERIFY_CACHE_TTL", "90"))
    POOL_REFRESH_INTERVAL: int = int(os.getenv("POOL_REFRESH_INTERVAL", "3600"))
    HEALTH_CHECK_TIMEOUT: float = float(os.getenv("HEALTH_CHECK_TIMEOUT", "4.0"))
    HEALTH_CHECK_CONCURRENCY: int = int(os.getenv("HEALTH_CHECK_CONCURRENCY", "30"))
    MAX_HEALTH_CHECK_CANDIDATES: int = int(os.getenv("MAX_HEALTH_CHECK_CANDIDATES", "120"))
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
