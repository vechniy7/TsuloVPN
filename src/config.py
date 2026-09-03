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
    "accessboy.com",
    "projectcube.tech",
)

PRIVATE_SOURCE_HOST_MARKERS = HAPP_HWID_HOST_MARKERS + (
    "ecobuy.ltd",
    "shuka.site",
    "accessboy.com",
    "subs.",
)

CLASSIC_SUB_HOST_MARKERS = ("ecobuy.ltd", "shuka.site")

# Стабильный профиль устройства для Happ HWID (слот в панели — не менять без причины)
DEFAULT_DEVICE_HWID = "cdjymarydl3xgyv8"
DEFAULT_DEVICE_OS = "iOS"
DEFAULT_DEVICE_OS_VER = "17.7"
DEFAULT_DEVICE_MODEL = "iPhone12,3"  # iPhone 11 Pro
DEFAULT_FETCH_UA = "Happ/5.5.0"

_DISABLED_SOURCE_MARKERS = frozenset({"-", "none", "null", "off", "disabled", "n/a", "na"})


def blank_subscription_url(url: str) -> str:
    """Пустой или отключённый URL («-», none, …) → \"\"."""
    raw = (url or "").strip()
    if not raw or raw.lower() in _DISABLED_SOURCE_MARKERS:
        return ""
    return normalize_subscription_url(raw)


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
    if "projectcube.tech" in lower:
        parsed = urlparse(raw)
        path = (parsed.path or "").strip("/")
        if path and "/" not in path and not any(
            path.endswith(suffix) for suffix in ("json", "clash", "yaml", "yml")
        ):
            return f"{raw.rstrip('/')}/json"
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
        val = blank_subscription_url(os.getenv(key, ""))
        if val:
            return val
    return ""


def resolve_vpn_bypass_source_url() -> str:
    """Доп. ключ мобильных профилей (LTE). Может быть пустым."""
    return blank_subscription_url(os.getenv("VPN_BYPASS_SOURCE_URL", ""))


def resolve_vpn_bypass_source_url_2() -> str:
    """Второй доп. ключ мобильных профилей (⚡). Может быть пустым."""
    return blank_subscription_url(os.getenv("VPN_BYPASS_SOURCE_URL_2", ""))


VPN_SOURCE_URL = resolve_vpn_source_url()
VPN_BYPASS_SOURCE_URL = resolve_vpn_bypass_source_url()
VPN_BYPASS_SOURCE_URL_2 = resolve_vpn_bypass_source_url_2()


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
    # Доп. источник мобильных профилей (🔥). Пусто / "-" = не используется.
    VPN_BYPASS_SOURCE_URL: str = VPN_BYPASS_SOURCE_URL
    # Второй доп. источник мобильных профилей (⚡).
    VPN_BYPASS_SOURCE_URL_2: str = VPN_BYPASS_SOURCE_URL_2
    # legacy aliases (читаются, но не нужны в env)
    PRIMARY_SUB_URL: str = VPN_SOURCE_URL
    LIDERVPN_SUB_URL: str = normalize_subscription_url(os.getenv("LIDERVPN_SUB_URL", "")) or VPN_SOURCE_URL
    WIFI_SOURCE_URLS: str = os.getenv("WIFI_SOURCE_URLS", VPN_SOURCE_URL)
    LTE_SOURCE_URLS: str = os.getenv("LTE_SOURCE_URLS", VPN_SOURCE_URL)

    # Профиль устройства для всех источников (Happ HWID)
    SUB_HWID: str = os.getenv("SUB_HWID", DEFAULT_DEVICE_HWID)
    SUB_DEVICE_OS: str = os.getenv("SUB_DEVICE_OS", DEFAULT_DEVICE_OS)
    SUB_DEVICE_OS_VER: str = os.getenv("SUB_DEVICE_OS_VER", DEFAULT_DEVICE_OS_VER)
    SUB_DEVICE_MODEL: str = os.getenv("SUB_DEVICE_MODEL", DEFAULT_DEVICE_MODEL)
    SUB_DEVICE_LOCALE: str = os.getenv("SUB_DEVICE_LOCALE", "ru")
    SUB_FETCH_UA: str = os.getenv("SUB_FETCH_UA", DEFAULT_FETCH_UA)
    # В /health не показывать ID ключа посторонним (только статус)
    HEALTH_PUBLIC_DETAILS: bool = os.getenv("HEALTH_PUBLIC_DETAILS", "false").lower() in (
        "1",
        "true",
        "yes",
    )
    KEEP_SOURCE_NAMES: bool = os.getenv("KEEP_SOURCE_NAMES", "true").lower() in (
        "1",
        "true",
        "yes",
    )

    SUBSCRIPTION_CONFIG_LIMIT: int = int(os.getenv("SUBSCRIPTION_CONFIG_LIMIT", "50"))
    # Макс. «Мобильный Интернет» — не срезаются ради Wi‑Fi серверов
    BYPASS_CONFIG_LIMIT: int = int(os.getenv("BYPASS_CONFIG_LIMIT", "25"))
    # Лимит Wi‑Fi/стран в профиле (0 = авто: общий лимит минус обход)
    SUBSCRIPTION_WIFI_LIMIT: int = int(os.getenv("SUBSCRIPTION_WIFI_LIMIT", "0"))
    LTE_CONFIG_LIMIT: int = int(os.getenv("LTE_CONFIG_LIMIT", "50"))
    LTE_BALANCER_NODES: int = int(os.getenv("LTE_BALANCER_NODES", "10"))
    LTE_DELIVERY: str = os.getenv("LTE_DELIVERY", "happ_ping").strip().lower()
    LTE_REQUIRE_WHITELIST_IP: bool = os.getenv(
        "LTE_REQUIRE_WHITELIST_IP", "true"
    ).lower() in ("1", "true", "yes")
    LTE_MIN_BYPASS_SCORE: int = int(os.getenv("LTE_MIN_BYPASS_SCORE", "55"))
    LTE_MAX_RTT_MS: int = int(os.getenv("LTE_MAX_RTT_MS", "900"))
    LTE_TCP_CHECK: bool = os.getenv("LTE_TCP_CHECK", "false").lower() in ("1", "true", "yes")
    WHITELIST_CIDR_URL: str = os.getenv(
        "WHITELIST_CIDR_URL",
        "https://raw.githubusercontent.com/hxehex/russia-mobile-internet-whitelist/main/cidrwhitelist.txt",
    )
    SUBSCRIPTION_SHOW_INDIVIDUAL: bool = os.getenv(
        "SUBSCRIPTION_SHOW_INDIVIDUAL", "false"
    ).lower() in ("1", "true", "yes")

    # Реже опрашиваем панель — меньше шанс ban по «серверному» IP (Amvera/VPS)
    POOL_REFRESH_INTERVAL: int = int(os.getenv("POOL_REFRESH_INTERVAL", "7200"))
    POOL_REFRESH_JITTER_SEC: int = int(os.getenv("POOL_REFRESH_JITTER_SEC", "1800"))
    POOL_STARTUP_DELAY_SEC: int = int(os.getenv("POOL_STARTUP_DELAY_SEC", "180"))
    CIDR_REFRESH_INTERVAL: int = int(os.getenv("CIDR_REFRESH_INTERVAL", "86400"))
    SOURCE_FETCH_BACKOFF_SEC: int = int(os.getenv("SOURCE_FETCH_BACKOFF_SEC", "7200"))
    # legacy — не используется (оставлено для совместимости env)
    UPSTREAM_PROXY_URL: str = os.getenv("UPSTREAM_PROXY_URL", "").strip()
    # Telegram: webhook вместо long polling (рекомендуется на Amvera)
    TELEGRAM_WEBHOOK_ENABLED: bool = os.getenv("TELEGRAM_WEBHOOK_ENABLED", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    TELEGRAM_WEBHOOK_PATH: str = os.getenv("TELEGRAM_WEBHOOK_PATH", "/telegram/webhook").strip()
    TELEGRAM_WEBHOOK_SECRET: str = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    ADMIN_FORCE_REFRESH_COOLDOWN_SEC: int = int(
        os.getenv("ADMIN_FORCE_REFRESH_COOLDOWN_SEC", "3600")
    )
    # Пароль входа в веб-панель /panel (обязателен для доступа)
    ADMIN_PANEL_TOKEN: str = os.getenv("ADMIN_PANEL_TOKEN", "").strip()
    SOURCE_ALERT_COOLDOWN_SEC: int = int(os.getenv("SOURCE_ALERT_COOLDOWN_SEC", "3600"))
    SOURCE_MIN_REAL_CONFIGS: int = int(os.getenv("SOURCE_MIN_REAL_CONFIGS", "2"))
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

    REQUIRED_CHANNEL: str = os.getenv("REQUIRED_CHANNEL", "@TsuloVPN").strip()
    REQUIRED_CHANNEL_URL: str = os.getenv("REQUIRED_CHANNEL_URL", "https://t.me/TsuloVPN").strip()
    CHANNEL_GATE_ENABLED: bool = os.getenv("CHANNEL_GATE_ENABLED", "true").lower() in (
        "1",
        "true",
        "yes",
    )

    SUPPORT_URL: str = os.getenv("SUPPORT_URL", "https://t.me/tsuloew")
    SUPPORT_EMAIL: str = os.getenv("SUPPORT_EMAIL", "").strip()
    INSTAGRAM_URL: str = os.getenv("INSTAGRAM_URL", "https://www.instagram.com/tsulo.it")

    # Оплата: по умолчанию выключена — доступ бесплатный для всех.
    # Cardlink — legacy; Platega подключается после регистрации кассы.
    PAYMENTS_ENFORCE: bool = os.getenv("PAYMENTS_ENFORCE", "false").lower() in ("1", "true", "yes")
    CARDLINK_API_TOKEN: str = os.getenv("CARDLINK_API_TOKEN", "")
    CARDLINK_SHOP_ID: str = os.getenv("CARDLINK_SHOP_ID", "")
    CARDLINK_PAYMENT_METHOD: str = os.getenv("CARDLINK_PAYMENT_METHOD", "")
    PLATEGA_MERCHANT_ID: str = os.getenv("PLATEGA_MERCHANT_ID", "").strip()
    PLATEGA_API_KEY: str = os.getenv("PLATEGA_API_KEY", "").strip()
    # Пусто = пользователь выбирает способ на пейформе. 2=СБП, 11=карты RUB.
    PLATEGA_PAYMENT_METHOD: str = os.getenv("PLATEGA_PAYMENT_METHOD", "").strip()

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
    def required_channel_id(self) -> str:
        return (self.REQUIRED_CHANNEL or "").strip()

    @property
    def channel_gate_enabled(self) -> bool:
        return self.CHANNEL_GATE_ENABLED and bool(self.required_channel_id)

    @property
    def required_channel_url(self) -> str:
        channel = self.required_channel_id
        if self.REQUIRED_CHANNEL_URL:
            return self.REQUIRED_CHANNEL_URL
        if channel.startswith("@"):
            return f"https://t.me/{channel.lstrip('@')}"
        return channel

    @property
    def use_cardlink(self) -> bool:
        return bool(self.CARDLINK_API_TOKEN and self.CARDLINK_SHOP_ID)

    @property
    def payments_active(self) -> bool:
        # Платные подписки только при Platega + явном флаге.
        return self.PAYMENTS_ENFORCE and self.use_platega

    @property
    def use_platega(self) -> bool:
        return bool(self.PLATEGA_MERCHANT_ID and self.PLATEGA_API_KEY)

    @property
    def platega_webhook_url(self) -> str:
        return f"{self.SUBSCRIPTION_PUBLIC_URL.rstrip('/')}/platega/webhook"

    @field_validator("SUB_HWID", mode="before")
    @classmethod
    def normalize_hwid(cls, value):
        if not value or not isinstance(value, str):
            return DEFAULT_DEVICE_HWID
        hwid = re.sub(r"[^a-zA-Z0-9=-]", "", value.strip())
        if len(hwid) < 10:
            return DEFAULT_DEVICE_HWID
        return hwid[:64]

    @field_validator("ADMINS", mode="before")
    @classmethod
    def parse_admins(cls, value):
        if isinstance(value, str):
            return [int(admin) for admin in value.split(",") if admin.strip()]
        return value or []

    @property
    def miniapp_url(self) -> str:
        return f"{self.SUBSCRIPTION_PUBLIC_URL.rstrip('/')}/miniapp"

    @property
    def privacy_page_url(self) -> str:
        return f"{self.SUBSCRIPTION_PUBLIC_URL.rstrip('/')}/privacy"

    @property
    def terms_page_url(self) -> str:
        return f"{self.SUBSCRIPTION_PUBLIC_URL.rstrip('/')}/terms"

    @property
    def tariffs_page_url(self) -> str:
        return f"{self.SUBSCRIPTION_PUBLIC_URL.rstrip('/')}/tariffs"

    @property
    def panel_url(self) -> str:
        return f"{self.SUBSCRIPTION_PUBLIC_URL.rstrip('/')}/panel"

    @property
    def panel_enabled(self) -> bool:
        return bool(self.ADMIN_PANEL_TOKEN)

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

    def source_label(self) -> str:
        """Последний сегмент URL — для логов и алертов без полного пути."""
        url = self.resolved_source_url()
        return url.rstrip("/").split("/")[-1] if url else "не задан"

    def bypass_source_url(self) -> str:
        url = blank_subscription_url(self.VPN_BYPASS_SOURCE_URL or "")
        main = self.resolved_source_url()
        if url and main and url.rstrip("/") == main.rstrip("/"):
            return ""
        return url

    def bypass_source_label(self) -> str:
        url = self.bypass_source_url()
        return url.rstrip("/").split("/")[-1] if url else ""

    def bypass_source_url_2(self) -> str:
        url = blank_subscription_url(self.VPN_BYPASS_SOURCE_URL_2 or "")
        main = self.resolved_source_url()
        bypass1 = self.bypass_source_url()
        if not url:
            return ""
        normalized = url.rstrip("/")
        if main and normalized == main.rstrip("/"):
            return ""
        if bypass1 and normalized == bypass1.rstrip("/"):
            return ""
        return url

    def bypass_source_label_2(self) -> str:
        url = self.bypass_source_url_2()
        return url.rstrip("/").split("/")[-1] if url else ""

    def upstream_fetch_plan(self) -> list[tuple[str, str]]:
        """(роль, url): main, bypass (🔥), bypass2 (⚡)."""
        plan: list[tuple[str, str]] = []
        main = self.resolved_source_url()
        if main:
            plan.append(("main", main))
        bypass = self.bypass_source_url()
        if bypass:
            plan.append(("bypass", bypass))
        bypass2 = self.bypass_source_url_2()
        if bypass2:
            plan.append(("bypass2", bypass2))
        return plan

    def telegram_webhook_enabled(self) -> bool:
        if not self.TELEGRAM_WEBHOOK_ENABLED:
            return False
        return self.SUBSCRIPTION_PUBLIC_URL.lower().startswith("https://")

    def telegram_webhook_url(self) -> str:
        base = self.SUBSCRIPTION_PUBLIC_URL.rstrip("/")
        path = self.TELEGRAM_WEBHOOK_PATH or "/telegram/webhook"
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{base}{path}"

    def telegram_webhook_secret(self) -> str:
        """Только явный TELEGRAM_WEBHOOK_SECRET. Пусто = без проверки (проще для Amvera)."""
        return (self.TELEGRAM_WEBHOOK_SECRET or "").strip()

    def subscription_wifi_limit(self) -> int:
        """Слоты под страны/Wi‑Fi; обходные конфиги не вытесняют «Мобильный Интернет»."""
        if self.SUBSCRIPTION_WIFI_LIMIT > 0:
            return self.SUBSCRIPTION_WIFI_LIMIT
        reserved = self.BYPASS_CONFIG_LIMIT + 2
        return max(8, self.SUBSCRIPTION_CONFIG_LIMIT - reserved)

    def fetch_hwid_headers(self, *, role: str = "") -> dict[str, str]:
        """Заголовки Happ для панели — один профиль устройства для всех источников."""
        _ = role
        return {
            "User-Agent": (self.SUB_FETCH_UA or DEFAULT_FETCH_UA).strip(),
            "Accept": "*/*",
            "Accept-Encoding": "gzip",
            "x-hwid": (self.SUB_HWID or DEFAULT_DEVICE_HWID).strip(),
            "x-device-os": self.SUB_DEVICE_OS or DEFAULT_DEVICE_OS,
            "x-ver-os": self.SUB_DEVICE_OS_VER or DEFAULT_DEVICE_OS_VER,
            "x-device-model": self.SUB_DEVICE_MODEL or DEFAULT_DEVICE_MODEL,
            "x-device-locale": (self.SUB_DEVICE_LOCALE or "ru").strip() or "ru",
        }

    def subscription_url_for_token(self, token: str) -> str:
        base = self.SUBSCRIPTION_PUBLIC_URL.rstrip("/")
        return f"{base}/sub/{token}"

    def subscription_lte_url_for_token(self, token: str) -> str:
        base = self.SUBSCRIPTION_PUBLIC_URL.rstrip("/")
        return f"{base}/sub/{token}/lte"

    # --- IKEv2 Personal VPN catalog (iOS Tsulo app; Amvera serves JSON only) ---
    IKEV2_APP_TOKEN: str = os.getenv(
        "IKEV2_APP_TOKEN", "b97c0f5dad444522a17a4240f33d3e3d"
    ).strip()
    IKEV2_GATEWAYS_JSON: str = os.getenv("IKEV2_GATEWAYS_JSON", "").strip()
    IKEV2_SERVER: str = os.getenv("IKEV2_SERVER", "").strip()
    IKEV2_USERNAME: str = os.getenv("IKEV2_USERNAME", "tsulo").strip()
    IKEV2_PASSWORD: str = os.getenv("IKEV2_PASSWORD", "").strip()
    IKEV2_REMOTE_ID: str = os.getenv("IKEV2_REMOTE_ID", "").strip()
    IKEV2_LOCAL_ID: str = os.getenv("IKEV2_LOCAL_ID", "").strip()
    IKEV2_PSK: str = os.getenv("IKEV2_PSK", "").strip()
    IKEV2_LTE_SERVER: str = os.getenv("IKEV2_LTE_SERVER", "").strip()
    IKEV2_LTE_USERNAME: str = os.getenv("IKEV2_LTE_USERNAME", "").strip()
    IKEV2_LTE_PASSWORD: str = os.getenv("IKEV2_LTE_PASSWORD", "").strip()
    IKEV2_LTE_REMOTE_ID: str = os.getenv("IKEV2_LTE_REMOTE_ID", "").strip()
    IKEV2_LTE_LOCAL_ID: str = os.getenv("IKEV2_LTE_LOCAL_ID", "").strip()

    def ikev2_catalog_url(self) -> str:
        base = self.SUBSCRIPTION_PUBLIC_URL.rstrip("/")
        token = self.IKEV2_APP_TOKEN or "app"
        return f"{base}/ikev2/{token}"

    def ikev2_gateways(self) -> list[dict]:
        """Catalog for iOS Personal VPN. Not Xray — points at your IKEv2 VPS."""
        if self.IKEV2_GATEWAYS_JSON:
            try:
                import json

                raw = json.loads(self.IKEV2_GATEWAYS_JSON)
                if isinstance(raw, dict) and isinstance(raw.get("gateways"), list):
                    return [g for g in raw["gateways"] if isinstance(g, dict)]
                if isinstance(raw, list):
                    return [g for g in raw if isinstance(g, dict)]
            except Exception:
                pass

        gateways: list[dict] = []
        if self.IKEV2_SERVER and (self.IKEV2_PASSWORD or self.IKEV2_PSK):
            gateways.append(
                {
                    "remarks": "Tsulo Wi‑Fi",
                    "server": self.IKEV2_SERVER,
                    "remoteId": self.IKEV2_REMOTE_ID or self.IKEV2_SERVER,
                    "localId": self.IKEV2_LOCAL_ID or self.IKEV2_USERNAME or "tsulo",
                    "username": self.IKEV2_USERNAME or "tsulo",
                    "password": self.IKEV2_PASSWORD,
                    "psk": self.IKEV2_PSK or None,
                    "isBypass": False,
                }
            )
        lte_server = self.IKEV2_LTE_SERVER or self.IKEV2_SERVER
        lte_user = self.IKEV2_LTE_USERNAME or self.IKEV2_USERNAME or "tsulo"
        lte_pass = self.IKEV2_LTE_PASSWORD or self.IKEV2_PASSWORD
        if lte_server and (lte_pass or self.IKEV2_PSK):
            gateways.append(
                {
                    "remarks": "Tsulo LTE",
                    "server": lte_server,
                    "remoteId": self.IKEV2_LTE_REMOTE_ID
                    or self.IKEV2_REMOTE_ID
                    or lte_server,
                    "localId": self.IKEV2_LTE_LOCAL_ID or lte_user,
                    "username": lte_user,
                    "password": lte_pass,
                    "psk": self.IKEV2_PSK or None,
                    "isBypass": True,
                }
            )
        cleaned: list[dict] = []
        for g in gateways:
            item = {k: v for k, v in g.items() if v is not None and v != ""}
            cleaned.append(item)
        return cleaned

    def wifi_source_urls(self) -> list[str]:
        url = self.resolved_source_url()
        return [url] if url else []

    def lte_source_urls(self) -> list[str]:
        return self.wifi_source_urls()

    def all_source_urls(self) -> list[str]:
        return self.wifi_source_urls()


config = Config(ADMINS=os.getenv("ADMINS", ""))
