import os
import re
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

load_dotenv()

ZIENG2_RAW = "https://raw.githubusercontent.com/zieng2/wl/main"
ZIENG2_UNIVERSAL = f"{ZIENG2_RAW}/vless_universal.txt"

SHADOWNET_DEFAULT_TOKEN = "aD8WEfTdIimbF1yE-M2w-LWK5w9kWBEur4jTVPvkGnE"


def normalize_subscription_url(url: str) -> str:
    """connect?token=… → sub.shadow-net.site/sub/{token}; остальное без изменений."""
    raw = (url or "").strip()
    if not raw:
        return raw
    lower = raw.lower()
    if "shadow-net.site" in lower and "token=" in lower:
        parsed = urlparse(raw)
        token = (parse_qs(parsed.query).get("token") or [None])[0]
        if token:
            return f"https://sub.shadow-net.site/sub/{token.strip()}"
    match = re.search(r"shadow-net\.site/connect[^?]*\?token=([^&\s#]+)", raw, re.I)
    if match:
        return f"https://sub.shadow-net.site/sub/{match.group(1).strip()}"
    return raw


def _default_primary_sub_url() -> str:
    for key in ("PRIMARY_SUB_URL", "SHADOWNET_CONNECT_URL", "WIFI_SOURCE_URLS"):
        val = normalize_subscription_url(os.getenv(key, ""))
        if val:
            return val
    token = os.getenv("SHADOWNET_TOKEN", SHADOWNET_DEFAULT_TOKEN).strip()
    return f"https://sub.shadow-net.site/sub/{token}"


# Основной источник конфигов (PRIMARY_SUB_URL / SHADOWNET_CONNECT_URL / WIFI_SOURCE_URLS)
PRIMARY_SUB_URL = _default_primary_sub_url()
# legacy alias
LIDERVPN_SUB_URL = normalize_subscription_url(os.getenv("LIDERVPN_SUB_URL", "")) or PRIMARY_SUB_URL
DEFAULT_WIFI_SOURCES = PRIMARY_SUB_URL
DEFAULT_LTE_SOURCES = PRIMARY_SUB_URL


class Config(BaseModel):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMINS: list[int] = Field(default_factory=list)
    BOT_NAME: str = os.getenv("BOT_NAME", "TsuloVPN")

    SUBSCRIPTION_PUBLIC_URL: str = os.getenv("SUBSCRIPTION_PUBLIC_URL", "https://your-domain.com")
    SUBSCRIPTION_PORT: int = Field(
        default=int(os.getenv("PORT", os.getenv("SUBSCRIPTION_PORT", "8080")))
    )

    PRIMARY_SUB_URL: str = PRIMARY_SUB_URL
    LIDERVPN_SUB_URL: str = LIDERVPN_SUB_URL
    WIFI_SOURCE_URLS: str = os.getenv("WIFI_SOURCE_URLS", DEFAULT_WIFI_SOURCES)
    LTE_SOURCE_URLS: str = os.getenv("LTE_SOURCE_URLS", DEFAULT_LTE_SOURCES)

    # Remnawave HWID — без него панель отдаёт заглушку; в панели видно как обычный телефон
    SUB_HWID: str = os.getenv("SUB_HWID", "8f3a2c1d-4b5e-6f70-8a9b-0c1d2e3f4a5b")
    SUB_DEVICE_OS: str = os.getenv("SUB_DEVICE_OS", "Android")
    SUB_DEVICE_OS_VER: str = os.getenv("SUB_DEVICE_OS_VER", "14")
    SUB_DEVICE_MODEL: str = os.getenv("SUB_DEVICE_MODEL", "SM-S918B")
    SUB_FETCH_UA: str = os.getenv("SUB_FETCH_UA", "Happ/3.5.0")
    # Сохранять оригинальные названия серверов из источника
    KEEP_SOURCE_NAMES: bool = os.getenv("KEEP_SOURCE_NAMES", "true").lower() in (
        "1",
        "true",
        "yes",
    )

    SUBSCRIPTION_CONFIG_LIMIT: int = int(os.getenv("SUBSCRIPTION_CONFIG_LIMIT", "50"))
    LTE_CONFIG_LIMIT: int = int(os.getenv("LTE_CONFIG_LIMIT", "50"))
    LTE_BALANCER_NODES: int = int(os.getenv("LTE_BALANCER_NODES", "10"))
    # happ_ping = отдельные минимальные профили; balancer = observatory
    LTE_DELIVERY: str = os.getenv("LTE_DELIVERY", "happ_ping").strip().lower()
    # В подписку только IP из whitelist CIDR (критично для Билайн/МТС/Мегафон на LTE)
    LTE_REQUIRE_WHITELIST_IP: bool = os.getenv(
        "LTE_REQUIRE_WHITELIST_IP", "true"
    ).lower() in ("1", "true", "yes")
    # Мин. bypass-score для попадания в LTE-пул (отсекает мусор из агрегаторов)
    LTE_MIN_BYPASS_SCORE: int = int(os.getenv("LTE_MIN_BYPASS_SCORE", "55"))
    # 0 = leastPing (совместимее с Happ); >0 = leastLoad+maxRTT
    LTE_MAX_RTT_MS: int = int(os.getenv("LTE_MAX_RTT_MS", "0"))
    # TCP-проверка :443 с сервера перед выдачей в подписку
    LTE_TCP_CHECK: bool = os.getenv("LTE_TCP_CHECK", "false").lower() in ("1", "true", "yes")
    WHITELIST_CIDR_URL: str = os.getenv(
        "WHITELIST_CIDR_URL",
        "https://raw.githubusercontent.com/hxehex/russia-mobile-internet-whitelist/main/cidrwhitelist.txt",
    )
    SUBSCRIPTION_SHOW_INDIVIDUAL: bool = os.getenv(
        "SUBSCRIPTION_SHOW_INDIVIDUAL", "false"
    ).lower() in ("1", "true", "yes")

    POOL_REFRESH_INTERVAL: int = int(os.getenv("POOL_REFRESH_INTERVAL", "300"))
    FETCH_TIMEOUT: int = int(os.getenv("FETCH_TIMEOUT", "45"))
    AUTO_PROBE_INTERVAL_SEC: int = int(os.getenv("AUTO_PROBE_INTERVAL_SEC", "12"))
    WIFI_PROBE_URL: str = os.getenv(
        "WIFI_PROBE_URL",
        "https://www.gstatic.com/generate_204",
    )
    # gstatic — стабильный probe; при fail observatory Happ не уводит трафик в direct так долго
    LTE_PROBE_URL: str = os.getenv(
        "LTE_PROBE_URL",
        "https://www.gstatic.com/generate_204",
    )
    LTE_PROBE_INTERVAL_SEC: int = int(os.getenv("LTE_PROBE_INTERVAL_SEC", "10"))

    HAPP_ENCRYPT_SUBSCRIPTION: bool = os.getenv("HAPP_ENCRYPT_SUBSCRIPTION", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    # В боте plain https надёжнее: crypt5 ~850 символов, Telegram плохо копирует из <code>
    BOT_ENCRYPT_SUBSCRIPTION: bool = os.getenv("BOT_ENCRYPT_SUBSCRIPTION", "false").lower() in (
        "1",
        "true",
        "yes",
    )

    PAYMENTS_ENFORCE: bool = os.getenv("PAYMENTS_ENFORCE", "false").lower() in ("1", "true", "yes")

    SUPPORT_URL: str = os.getenv("SUPPORT_URL", "https://t.me/tsuloew")
    INSTAGRAM_URL: str = os.getenv("INSTAGRAM_URL", "https://www.instagram.com/tsulo.it")
    DONATE_CARD: str = os.getenv("DONATE_CARD", "2202209226540747")
    DONATE_CARD_NAME: str = os.getenv("DONATE_CARD_NAME", "АЛИ Ц")
    DONATE_BANK: str = os.getenv("DONATE_BANK", "Сбербанк")

    CARDLINK_API_TOKEN: str = os.getenv("CARDLINK_API_TOKEN", "")
    CARDLINK_SHOP_ID: str = os.getenv("CARDLINK_SHOP_ID", "")
    CARDLINK_PAYMENT_METHOD: str = os.getenv("CARDLINK_PAYMENT_METHOD", "")

    UPSTASH_REDIS_REST_URL: str = os.getenv("UPSTASH_REDIS_REST_URL", "")
    UPSTASH_REDIS_REST_TOKEN: str = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

    @field_validator("UPSTASH_REDIS_REST_URL", mode="before")
    @classmethod
    def normalize_upstash_url(cls, value):
        if not value or not isinstance(value, str):
            return value or ""
        url = value.strip()
        if url and not url.lower().startswith(("http://", "https://")):
            url = f"https://{url.lstrip('/')}"
        return url

    @field_validator("UPSTASH_REDIS_REST_TOKEN", mode="before")
    @classmethod
    def normalize_upstash_token(cls, value):
        if not value or not isinstance(value, str):
            return value or ""
        return value.strip()

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

    @property
    def miniapp_url(self) -> str:
        return f"{self.SUBSCRIPTION_PUBLIC_URL.rstrip('/')}/miniapp"

    def donation_card_spaced(self) -> str:
        digits = "".join(ch for ch in self.DONATE_CARD if ch.isdigit())
        return " ".join(digits[i : i + 4] for i in range(0, len(digits), 4)) or self.DONATE_CARD

    def subscription_url_for_token(self, token: str) -> str:
        base = self.SUBSCRIPTION_PUBLIC_URL.rstrip("/")
        return f"{base}/sub/{token}"

    def subscription_lte_url_for_token(self, token: str) -> str:
        base = self.SUBSCRIPTION_PUBLIC_URL.rstrip("/")
        return f"{base}/sub/{token}/lte"

    @staticmethod
    def _split_urls(raw: str) -> list[str]:
        return [
            normalize_subscription_url(u.strip())
            for u in raw.split(",")
            if u.strip()
        ]

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
