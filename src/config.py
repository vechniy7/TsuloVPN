import os
import re
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

load_dotenv()

# Панели, которые отдают конфиги только с Happ UA + HWID (маскируемся под Android-телефон)
HAPP_HWID_HOST_MARKERS = (
    "shadow-net.site",
    "mystatic-cdn.ru",
    "eu-fffast.com",
    "disketa.net",
    "lidervpn.com",
    "remnawave",
    "remna.st",
    "pnl.",
)

PRIVATE_SOURCE_HOST_MARKERS = HAPP_HWID_HOST_MARKERS + (
    "ecobuy.ltd",
    "shuka.site",
    "subs.",
)

CLASSIC_SUB_HOST_MARKERS = ("ecobuy.ltd", "shuka.site")

# Стабильный профиль «одного Android-устройства» — не менять без причины (слот HWID в панели)
DEFAULT_DEVICE_HWID = "8f3a2c1d-4b5e-6f70-8a9b-0c1d2e3f4a5b"
DEFAULT_DEVICE_OS = "Android"
DEFAULT_DEVICE_OS_VER = "14"
DEFAULT_DEVICE_MODEL = "SM-S918B"
DEFAULT_FETCH_UA = "Happ/3.5.0"


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


def requires_happ_hwid(url: str) -> bool:
    host = (url or "").lower()
    return any(marker in host for marker in HAPP_HWID_HOST_MARKERS)


def is_private_source(url: str) -> bool:
    host = (url or "").lower()
    return any(marker in host for marker in PRIVATE_SOURCE_HOST_MARKERS)


def is_classic_sub_url(url: str) -> bool:
    host = (url or "").lower()
    return any(marker in host for marker in CLASSIC_SUB_HOST_MARKERS)


def resolve_vpn_source_url() -> str:
    """Одна точка смены ключа: VPN_SOURCE_URL (или legacy PRIMARY_SUB_URL / WIFI_SOURCE_URLS)."""
    for key in ("VPN_SOURCE_URL", "PRIMARY_SUB_URL", "SHADOWNET_CONNECT_URL", "WIFI_SOURCE_URLS"):
        val = normalize_subscription_url(os.getenv(key, ""))
        if val:
            return val
    return ""


VPN_SOURCE_URL = resolve_vpn_source_url()


class Config(BaseModel):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMINS: list[int] = Field(default_factory=list)
    BOT_NAME: str = os.getenv("BOT_NAME", "TsuloVPN")

    SUBSCRIPTION_PUBLIC_URL: str = os.getenv("SUBSCRIPTION_PUBLIC_URL", "https://your-domain.com")
    SUBSCRIPTION_PORT: int = Field(
        default=int(os.getenv("PORT", os.getenv("SUBSCRIPTION_PORT", "8080")))
    )

    # Единственное поле для смены источника конфигов
    VPN_SOURCE_URL: str = VPN_SOURCE_URL
    # legacy aliases (читаются, но не нужны в env)
    PRIMARY_SUB_URL: str = VPN_SOURCE_URL
    LIDERVPN_SUB_URL: str = normalize_subscription_url(os.getenv("LIDERVPN_SUB_URL", "")) or VPN_SOURCE_URL
    WIFI_SOURCE_URLS: str = os.getenv("WIFI_SOURCE_URLS", VPN_SOURCE_URL)
    LTE_SOURCE_URLS: str = os.getenv("LTE_SOURCE_URLS", VPN_SOURCE_URL)

    # Профиль устройства для панели подписки (по умолчанию — обычный Samsung Android)
    SUB_HWID: str = os.getenv("SUB_HWID", DEFAULT_DEVICE_HWID)
    SUB_DEVICE_OS: str = os.getenv("SUB_DEVICE_OS", DEFAULT_DEVICE_OS)
    SUB_DEVICE_OS_VER: str = os.getenv("SUB_DEVICE_OS_VER", DEFAULT_DEVICE_OS_VER)
    SUB_DEVICE_MODEL: str = os.getenv("SUB_DEVICE_MODEL", DEFAULT_DEVICE_MODEL)
    SUB_FETCH_UA: str = os.getenv("SUB_FETCH_UA", DEFAULT_FETCH_UA)
    KEEP_SOURCE_NAMES: bool = os.getenv("KEEP_SOURCE_NAMES", "true").lower() in (
        "1",
        "true",
        "yes",
    )

    SUBSCRIPTION_CONFIG_LIMIT: int = int(os.getenv("SUBSCRIPTION_CONFIG_LIMIT", "50"))
    LTE_CONFIG_LIMIT: int = int(os.getenv("LTE_CONFIG_LIMIT", "50"))
    LTE_BALANCER_NODES: int = int(os.getenv("LTE_BALANCER_NODES", "10"))
    LTE_DELIVERY: str = os.getenv("LTE_DELIVERY", "happ_ping").strip().lower()
    LTE_REQUIRE_WHITELIST_IP: bool = os.getenv(
        "LTE_REQUIRE_WHITELIST_IP", "true"
    ).lower() in ("1", "true", "yes")
    LTE_MIN_BYPASS_SCORE: int = int(os.getenv("LTE_MIN_BYPASS_SCORE", "55"))
    LTE_MAX_RTT_MS: int = int(os.getenv("LTE_MAX_RTT_MS", "0"))
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
    AUTO_PROBE_INTERVAL_SEC: int = int(os.getenv("AUTO_PROBE_INTERVAL_SEC", "8"))
    WIFI_PROBE_URL: str = os.getenv(
        "WIFI_PROBE_URL",
        "https://www.gstatic.com/generate_204",
    )
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

    def resolved_source_url(self) -> str:
        for candidate in (
            self.VPN_SOURCE_URL,
            self.PRIMARY_SUB_URL,
            normalize_subscription_url(self.WIFI_SOURCE_URLS.split(",")[0] if self.WIFI_SOURCE_URLS else ""),
        ):
            url = normalize_subscription_url((candidate or "").strip())
            if url:
                return url
        return ""

    def fetch_hwid_headers(self) -> dict[str, str]:
        """Заголовки Happ HWID — панель видит одно Android-устройство."""
        return {
            "x-hwid": (self.SUB_HWID or DEFAULT_DEVICE_HWID).strip(),
            "x-device-os": self.SUB_DEVICE_OS or DEFAULT_DEVICE_OS,
            "x-ver-os": self.SUB_DEVICE_OS_VER or DEFAULT_DEVICE_OS_VER,
            "x-device-model": self.SUB_DEVICE_MODEL or DEFAULT_DEVICE_MODEL,
        }

    def donation_card_spaced(self) -> str:
        digits = "".join(ch for ch in self.DONATE_CARD if ch.isdigit())
        return " ".join(digits[i : i + 4] for i in range(0, len(digits), 4)) or self.DONATE_CARD

    def subscription_url_for_token(self, token: str) -> str:
        base = self.SUBSCRIPTION_PUBLIC_URL.rstrip("/")
        return f"{base}/sub/{token}"

    def subscription_lte_url_for_token(self, token: str) -> str:
        base = self.SUBSCRIPTION_PUBLIC_URL.rstrip("/")
        return f"{base}/sub/{token}/lte"

    def wifi_source_urls(self) -> list[str]:
        url = self.resolved_source_url()
        return [url] if url else []

    def lte_source_urls(self) -> list[str]:
        return self.wifi_source_urls()

    def all_source_urls(self) -> list[str]:
        return self.wifi_source_urls()


config = Config(ADMINS=os.getenv("ADMINS", ""))
