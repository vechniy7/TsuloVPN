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


def is_valid_config(uri: str) -> bool:
    uri_l = uri.lower()
    if not uri_l.startswith(SUPPORTED_PREFIXES):
        return False
    if INSECURE_PATTERN.search(urllib.parse.unquote(uri)):
        return False
    # vless/trojan/vmess должны иметь tls или reality (кроме ss/hy2)
    if uri_l.startswith(("vless://", "trojan://", "vmess://")):
        security = get_security(uri)
        if security not in ("tls", "reality"):
            return False
    return True


def parse_igareck_configs(data: str) -> list[str]:
    """Парсит файлы igareck, сохраняя порядок (рейтинг после тестов в РФ)."""
    data = try_decode_base64(data)
    pattern = "|".join(p.replace("://", "") for p in PROTOCOL_PREFIXES)
    data = re.sub(rf"({pattern})://", r"\n\1://", data, flags=re.IGNORECASE)

    result: list[str] = []
    seen: set[str] = set()

    for line in data.splitlines():
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
