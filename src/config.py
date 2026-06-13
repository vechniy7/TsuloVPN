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

    CONFIG_SOURCE_URL: str = os.getenv(
        "CONFIG_SOURCE_URL",
        f"{IGARECK_RAW}/WHITE-CIDR-RU-checked.txt",
    )

    # Сколько конфигов в подписке пользователя (или меньше, если в источнике меньше)
    SUBSCRIPTION_CONFIG_LIMIT: int = int(os.getenv("SUBSCRIPTION_CONFIG_LIMIT", "35"))

    # Как часто проверять обновления на GitHub (секунды)
    POOL_REFRESH_INTERVAL: int = int(os.getenv("POOL_REFRESH_INTERVAL", "300"))
    FETCH_TIMEOUT: int = int(os.getenv("FETCH_TIMEOUT", "45"))

    # Шифровать ссылку подписки через Happ API (happ://crypt5/...)
    HAPP_ENCRYPT_SUBSCRIPTION: bool = os.getenv("HAPP_ENCRYPT_SUBSCRIPTION", "true").lower() in (
        "1",
        "true",
        "yes",
    )

    UPSTASH_REDIS_REST_URL: str = os.getenv("UPSTASH_REDIS_REST_URL", "")
    UPSTASH_REDIS_REST_TOKEN: str = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

    @property
    def use_upstash(self) -> bool:
        return bool(self.UPSTASH_REDIS_REST_URL and self.UPSTASH_REDIS_REST_TOKEN)

    @field_validator("ADMINS", mode="before")
    @classmethod
    def parse_admins(cls, value):
        if isinstance(value, str):
            return [int(admin) for admin in value.split(",") if admin.strip()]
        return value or []

    def subscription_url_for_token(self, token: str) -> str:
        base = self.SUBSCRIPTION_PUBLIC_URL.rstrip("/")
        return f"{base}/sub/{token}"


config = Config(ADMINS=os.getenv("ADMINS", ""))
