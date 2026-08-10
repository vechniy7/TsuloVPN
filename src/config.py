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
    # Дополнение (legacy + часть multi-source пула)
    CONFIG_FILL_SOURCE_URL: str = os.getenv(
        "CONFIG_FILL_SOURCE_URL",
        f"{IGARECK_RAW}/Vless-Reality-White-Lists-Rus-Mobile.txt",
    )
    # Доп. источники через запятую; пусто = Mobile-2 + WHITE-CIDR-RU-all
    CONFIG_EXTRA_SOURCE_URLS: str = os.getenv("CONFIG_EXTRA_SOURCE_URLS", "")
    # Полный список через запятую перекрывает URL выше
    CONFIG_SOURCE_URLS: str = os.getenv("CONFIG_SOURCE_URLS", "")

    # Сколько узлов внутри «АВТО-ВЫБОР» (клиент видит только 1 профиль)
    SUBSCRIPTION_CONFIG_LIMIT: int = int(os.getenv("SUBSCRIPTION_CONFIG_LIMIT", "120"))
    # Показывать ли отдельные серверы в ключе (по умолчанию только АВТО)
    SUBSCRIPTION_SHOW_INDIVIDUAL: bool = os.getenv(
        "SUBSCRIPTION_SHOW_INDIVIDUAL", "false"
    ).lower() in ("1", "true", "yes")

    # Как часто проверять обновления на GitHub (секунды)
    POOL_REFRESH_INTERVAL: int = int(os.getenv("POOL_REFRESH_INTERVAL", "300"))
    FETCH_TIMEOUT: int = int(os.getenv("FETCH_TIMEOUT", "45"))

    # Шифровать ссылку подписки через Happ API (happ://crypt5/...)
    HAPP_ENCRYPT_SUBSCRIPTION: bool = os.getenv("HAPP_ENCRYPT_SUBSCRIPTION", "true").lower() in (
        "1",
        "true",
        "yes",
    )

    # Оплата: Cardlink или ЮKassa — включите PAYMENTS_ENFORCE=true
    PAYMENTS_ENFORCE: bool = os.getenv("PAYMENTS_ENFORCE", "false").lower() in ("1", "true", "yes")

    CARDLINK_API_TOKEN: str = os.getenv("CARDLINK_API_TOKEN", "")
    CARDLINK_SHOP_ID: str = os.getenv("CARDLINK_SHOP_ID", "")
    # SBP или BANK_CARD — пусто = клиент выбирает сам
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

    def config_source_urls(self) -> list[str]:
        """Ordered list of raw GitHub (or mirror) subscription URLs."""
        if self.CONFIG_SOURCE_URLS.strip():
            return [u.strip() for u in self.CONFIG_SOURCE_URLS.split(",") if u.strip()]

        urls: list[str] = []
        for url in (self.CONFIG_SOURCE_URL, self.CONFIG_FILL_SOURCE_URL):
            if url and url not in urls:
                urls.append(url)

        if self.CONFIG_EXTRA_SOURCE_URLS.strip():
            extras = [
                u.strip() for u in self.CONFIG_EXTRA_SOURCE_URLS.split(",") if u.strip()
            ]
        else:
            # Mobile-2 удалён у igareck (404). Вместо него: SNI + verified-агрегатор.
            extras = [
                f"{IGARECK_RAW}/WHITE-CIDR-RU-all.txt",
                f"{IGARECK_RAW}/WHITE-SNI-RU-all.txt",
                "https://raw.githubusercontent.com/aviamastersgh/vpn-free-russia/main/verified_configs.txt",
            ]
        for url in extras:
            if url not in urls:
                urls.append(url)
        return urls


config = Config(ADMINS=os.getenv("ADMINS", ""))
