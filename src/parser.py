import base64
import html
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
    "socks5://",
    "socks4://",
    "wireguard://",
    "ssh://",
    "snell://",
    "brook://",
    "juicity://",
)

INSECURE_PATTERN = re.compile(
    r"(?:[?&;]|3%[Bb])(allowinsecure|allow_insecure|insecure)=(?:1|true|yes)(?:[&;#]|$|(?=\s|$))",
    re.IGNORECASE,
)


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


def parse_configs(data: str) -> list[str]:
    data = try_decode_base64(data)
    pattern = "|".join(p.replace("://", "") for p in PROTOCOL_PREFIXES)
    data = re.sub(rf"({pattern})://", r"\n\1://", data, flags=re.IGNORECASE)

    result: list[str] = []
    for line in data.splitlines():
        line_stripped = line.strip()
        if not line_stripped.lower().startswith(PROTOCOL_PREFIXES):
            continue
        processed = urllib.parse.unquote(html.unescape(line_stripped))
        if not INSECURE_PATTERN.search(processed):
            result.append(line_stripped)
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
                import json

                data = json.loads(decoded)
                host = data.get("add") or data.get("host") or data.get("ip")
                port = data.get("port")
                if host and port:
                    return str(host), int(port)
        except Exception:
            return None

    match = re.search(r"(?:@|//)([\w\.-]+):(\d{1,5})", uri)
    if match:
        return match.group(1), int(match.group(2))
    return None


def brand_config(uri: str, label: str) -> str:
    base = uri.split("#", 1)[0]
    return f"{base}#{urllib.parse.quote(label, safe='')}"
