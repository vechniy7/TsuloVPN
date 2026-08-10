import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

load_dotenv()

IGARECK_RAW = "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main"


class Config(BaseModel):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMINS: list[int] = Field(default_factory=list)
    BOT_NAME: str = os.getenv("BOT_NAME", "TsuloVPN")

    SUBSCRIPTION_PUBLIC_URL: str = os.getenv("SUBSCRIPTION_PUBLIC_URL", "https://your-domain.com")
    SUBSCRIPTION_PORT: int = Field(
        default=int(os.getenv("PORT", os.getenv("SUBSCRIPTION_PORT", "8080")))
    )

    # АВТО WIFI — чёрные списки (обычный Wi‑Fi / домашний инет)
    WIFI_SOURCE_URLS: str = os.getenv(
        "WIFI_SOURCE_URLS",
        f"{IGARECK_RAW}/BLACK_VLESS_RUS_mobile.txt",
    )
    # АВТО LTE — белые списки (мобильный интернет / CIDR+SNI)
    LTE_SOURCE_URLS: str = os.getenv(
        "LTE_SOURCE_URLS",
        f"{IGARECK_RAW}/WHITE-CIDR-RU-all.txt,{IGARECK_RAW}/WHITE-SNI-RU-all.txt",
    )

    # Сколько узлов внутри КАЖДОГО АВТО-профиля (точность leastPing)
    SUBSCRIPTION_CONFIG_LIMIT: int = int(os.getenv("SUBSCRIPTION_CONFIG_LIMIT", "40"))
    SUBSCRIPTION_SHOW_INDIVIDUAL: bool = os.getenv(
        "SUBSCRIPTION_SHOW_INDIVIDUAL", "false"
    ).lower() in ("1", "true", "yes")

    POOL_REFRESH_INTERVAL: int = int(os.getenv("POOL_REFRESH_INTERVAL", "300"))
    FETCH_TIMEOUT: int = int(os.getenv("FETCH_TIMEOUT", "45"))
    # RTT-пробы на клиенте; при реконнекте Happ снова прогревает leastPing
    AUTO_PROBE_INTERVAL_SEC: int = int(os.getenv("AUTO_PROBE_INTERVAL_SEC", "12"))

    HAPP_ENCRYPT_SUBSCRIPTION: bool = os.getenv("HAPP_ENCRYPT_SUBSCRIPTION", "true").lower() in (
        "1",
        "true",
        "yes",
    )

    PAYMENTS_ENFORCE: bool = os.getenv("PAYMENTS_ENFORCE", "false").lower() in ("1", "true", "yes")

    CARDLINK_API_TOKEN: str = os.getenv("CARDLINK_API_TOKEN", "")
    CARDLINK_SHOP_ID: str = os.getenv("CARDLINK_SHOP_ID", "")
    CARDLINK_PAYMENT_METHOD: str = os.getenv("CARDLINK_PAYMENT_METHOD", "")

    UPSTASH_REDIS_REST_URL: str = os.getenv("UPSTASH_REDIS_REST_URL", "")
    UPSTASH_REDIS_REST_TOKEN: str = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

    @property
    def use_upstash(self) -> bool:
        return bool(self.UPSTASH_REDIS_REST_URL and self.UPSTASH_REDIS_REST_TOKEN)

    @property
    def use_cardlink(self) -> bool:
        return bool(self.CARDLINK_API_TOKEN and self.CARDLINK_SHOP_ID)

    @property
    def payments_active(self) -> bool:
        return self.PAYMENTS_ENFORCE or self.use_cardlink

    @field_validator("ADMINS", mode="before")
    @classmethod
    def parse_admins(cls, value):
        if isinstance(value, str):
            return [int(admin) for admin in value.split(",") if admin.strip()]
        return value or []

    def subscription_url_for_token(self, token: str) -> str:
        base = self.SUBSCRIPTION_PUBLIC_URL.rstrip("/")
        return f"{base}/sub/{token}"

    @staticmethod
    def _split_urls(raw: str) -> list[str]:
        return [u.strip() for u in raw.split(",") if u.strip()]

    def wifi_source_urls(self) -> list[str]:
        return self._split_urls(self.WIFI_SOURCE_URLS)

    def lte_source_urls(self) -> list[str]:
        return self._split_urls(self.LTE_SOURCE_URLS)

    def all_source_urls(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for url in self.wifi_source_urls() + self.lte_source_urls():
            if url not in seen:
                seen.add(url)
                out.append(url)
        return out


config = Config(ADMINS=os.getenv("ADMINS", ""))
