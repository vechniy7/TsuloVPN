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

SUPPORTED_PREFIXES = ("vless://", "vmess://", "trojan://")

INSECURE_PATTERN = re.compile(
    r"(?:[?&;]|3%[Bb])(allowinsecure|allow_insecure|insecure)=(?:1|true|yes)(?:[&;#]|$|(?=\s|$))",
    re.IGNORECASE,
)

SECURITY_PATTERN = re.compile(r"security=([^&;#]+)", re.IGNORECASE)
SNI_PATTERN = re.compile(r"sni=([^&;#]+)", re.IGNORECASE)
TYPE_PATTERN = re.compile(r"type=([^&;#]+)", re.IGNORECASE)


def normalize_uri(uri: str) -> str:
    """Исправляет &amp; и другие HTML-сущности в URI."""
    uri = html.unescape(uri).strip()
    if "#" in uri:
        base, fragment = uri.split("#", 1)
        return f"{base}#{fragment}"
    return uri


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
    params = _query_params(uri)
    return (params.get("security") or "").strip().lower()


def get_sni(uri: str) -> str | None:
    params = _query_params(uri)
    sni = (params.get("sni") or params.get("host") or "").strip()
    return sni or None


def get_transport(uri: str) -> str:
    params = _query_params(uri)
    return (params.get("type") or "tcp").strip().lower()


def quality_score(uri: str) -> int:
    """Чем выше — тем вероятнее рабочий конфиг."""
    uri_l = uri.lower()
    if not uri_l.startswith(SUPPORTED_PREFIXES):
        return 0

    score = 10
    security = get_security(uri)
    hostport = extract_host_port(uri)
    port = hostport[1] if hostport else 0

    if security == "reality":
        score += 50
        if "flow=xtls-rprx-vision" in uri_l:
            score += 15
        if get_sni(uri):
            score += 10
    elif security == "tls":
        score += 35
        if get_sni(uri):
            score += 10
    else:
        return 0  # без tls/reality — отбрасываем

    if port in (443, 8443, 2053, 2083, 2096):
        score += 10
    elif port == 80:
        score -= 20

    transport = get_transport(uri)
    if transport in ("tcp", "ws", "grpc", "xhttp"):
        score += 5
    if transport == "raw":
        score += 3

    # Российские SNI для обхода белых списков
    sni = (get_sni(uri) or "").lower()
    if any(
        x in sni
        for x in (
            "yandex",
            "kinopoisk",
            "vk.com",
            "mail.ru",
            "max.ru",
            "avito",
            "ozon",
            "wildberries",
        )
    ):
        score += 20

    return score


def is_quality_config(uri: str) -> bool:
    return quality_score(uri) >= 40


def parse_configs(data: str) -> list[str]:
    data = try_decode_base64(data)
    pattern = "|".join(p.replace("://", "") for p in PROTOCOL_PREFIXES)
    data = re.sub(rf"({pattern})://", r"\n\1://", data, flags=re.IGNORECASE)

    result: list[str] = []
    seen: set[str] = set()

    for line in data.splitlines():
        line_stripped = normalize_uri(line.strip())
        if not line_stripped.lower().startswith(SUPPORTED_PREFIXES):
            continue
        if not is_quality_config(line_stripped):
            continue
        processed = urllib.parse.unquote(line_stripped)
        if INSECURE_PATTERN.search(processed):
            continue
        if processed in seen:
            continue
        seen.add(processed)
        result.append(processed)

    result.sort(key=quality_score, reverse=True)
    return result


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
