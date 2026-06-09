import base64
import html
import json
import re
import urllib.parse

PROTOCOL_PREFIXES = (
    "vmess://",
    "vless://",
    "trojan://",
    "ss://",
    "ssr://",
    "tuic://",
    "hysteria://",
    "hysteria2://",
    "hy2://",
)

SUPPORTED_PREFIXES = ("vless://", "vmess://", "trojan://", "ss://", "hysteria2://", "hy2://")

INSECURE_PATTERN = re.compile(
    r"(?:[?&;]|3%[Bb])(allowinsecure|allow_insecure|insecure)=(?:1|true|yes)(?:[&;#]|$|(?=\s|$))",
    re.IGNORECASE,
)

# SNI домены из белых списков операторов (Мегафон, МТС, Билайн и др.)
RU_WHITELIST_SNI_KEYWORDS = (
    "yandex",
    "vk.com",
    "vk.ru",
    "max.ru",
    "x5.ru",
    "rutube",
    "kinopoisk",
    "mail.ru",
    "ozon",
    "wildberries",
    "avito",
    "sber",
    "mts.ru",
    "megafon",
    "beeline",
    "tinkoff",
    "ok.ru",
    "cdnvideo",
    "urent",
    "wb.ru",
    "gosuslugi",
)

# SNI которые НЕ работают на мобильном интернете с белыми списками
BAD_WHITELIST_SNI = (
    "google.com",
    "www.google.com",
    "mediastreamer",
    "colorlib.com",
    "fasssst.online",
    "riotvpn.eu",
    "obhod.riotvpn",
)


def normalize_uri(uri: str) -> str:
    return html.unescape(uri).strip()


def try_decode_base64(data: str) -> str:
    if "://" not in data:
        try:
            clean_data = "".join(data.split())
            rem = len(clean_data) % 4
            if rem:
                clean_data += "=" * (4 - rem)
            decoded = base64.b64decode(clean_data).decode("utf-8", errors="ignore")
            if any(prefix in decoded.lower() for prefix in PROTOCOL_PREFIXES):
                return decoded
        except Exception:
            pass
    return data


def _query_params(uri: str) -> dict[str, str]:
    try:
        if "?" not in uri:
            return {}
        query = uri.split("?", 1)[1].split("#", 1)[0]
        return {k.lower(): v for k, v in urllib.parse.parse_qsl(query, keep_blank_values=True)}
    except Exception:
        return {}


def get_security(uri: str) -> str:
    return (_query_params(uri).get("security") or "").strip().lower()


def get_sni(uri: str) -> str | None:
    params = _query_params(uri)
    sni = (params.get("sni") or params.get("host") or "").strip()
    return sni or None


def is_ru_whitelist_sni(sni: str | None) -> bool:
    if not sni:
        return False
    sni_l = sni.lower()
    if any(bad in sni_l for bad in BAD_WHITELIST_SNI):
        return False
    return any(kw in sni_l for kw in RU_WHITELIST_SNI_KEYWORDS)


def whitelist_score(uri: str) -> int:
    """Чем выше — тем лучше для обхода белых списков на мобильном интернете."""
    if not uri.lower().startswith("vless://"):
        return 0
    if get_security(uri) != "reality":
        return 0

    sni = get_sni(uri)
    if not is_ru_whitelist_sni(sni):
        return 0

    score = 50
    sni_l = (sni or "").lower()

    # Топовые SNI для Мегафон/МТС
    if "ads.x5.ru" in sni_l or "cdp.x5.ru" in sni_l:
        score += 40
    if "yandex" in sni_l:
        score += 35
    if "vk.com" in sni_l or "vk.ru" in sni_l or "max.ru" in sni_l:
        score += 35
    if "rutube" in sni_l:
        score += 30

    hostport = extract_host_port(uri)
    if hostport and hostport[1] in (443, 8443, 5443, 7443):
        score += 15
    elif hostport and hostport[1] == 80:
        score -= 30  # порт 80 плохо работает на мобильном БС

    if "flow=xtls-rprx-vision" in uri.lower():
        score += 10

    return score


def is_whitelist_config(uri: str) -> bool:
    return whitelist_score(uri) >= 50


def is_valid_config(uri: str) -> bool:
    uri_l = uri.lower()
    if not uri_l.startswith(SUPPORTED_PREFIXES):
        return False
    if INSECURE_PATTERN.search(urllib.parse.unquote(uri)):
        return False
    if uri_l.startswith(("vless://", "trojan://", "vmess://")):
        if get_security(uri) not in ("tls", "reality"):
            return False
    return True


def _split_config_lines(data: str) -> list[str]:
    data = try_decode_base64(data)
    pattern = "|".join(p.replace("://", "") for p in PROTOCOL_PREFIXES)
    data = re.sub(rf"({pattern})://", r"\n\1://", data, flags=re.IGNORECASE)
    return data.splitlines()


def parse_igareck_configs(data: str) -> list[str]:
    """Парсит обычные VPN-конфиги (чёрные списки)."""
    result: list[str] = []
    seen: set[str] = set()

    for line in _split_config_lines(data):
        line_stripped = normalize_uri(line.strip())
        if not line_stripped or line_stripped.startswith("#"):
            continue
        if not is_valid_config(line_stripped):
            continue
        processed = urllib.parse.unquote(line_stripped)
        if processed in seen:
            continue
        seen.add(processed)
        result.append(processed)

    return result


def parse_whitelist_configs(data: str) -> list[str]:
    """Парсит конфиги для обхода белых списков — только Reality + российский SNI."""
    candidates: list[str] = []
    seen: set[str] = set()

    for line in _split_config_lines(data):
        line_stripped = normalize_uri(line.strip())
        if not line_stripped or line_stripped.startswith("#"):
            continue
        if not line_stripped.lower().startswith("vless://"):
            continue
        processed = urllib.parse.unquote(line_stripped)
        if not is_whitelist_config(processed):
            continue
        if processed in seen:
            continue
        seen.add(processed)
        candidates.append(processed)

    candidates.sort(key=whitelist_score, reverse=True)
    return candidates


def extract_host_port(uri: str) -> tuple[str, int] | None:
    if not uri:
        return None

    if uri.startswith("vmess://"):
        try:
            payload = uri[8:]
            rem = len(payload) % 4
            if rem:
                payload += "=" * (4 - rem)
            decoded = base64.b64decode(payload).decode("utf-8", errors="ignore")
            if decoded.startswith("{"):
                data = json.loads(decoded)
                host = data.get("add") or data.get("host") or data.get("ip")
                port = data.get("port")
                if host and port:
                    return str(host), int(port)
        except Exception:
            return None

    match = re.search(r"(?:@|//)([^@/:?\s]+):(\d{1,5})", uri)
    if match:
        return match.group(1), int(match.group(2))
    return None


def brand_config(uri: str, label: str) -> str:
    base = uri.split("#", 1)[0]
    return f"{base}#{urllib.parse.quote(label, safe='')}"
