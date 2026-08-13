import base64
import html
import json
import re
import urllib.parse

from config import config

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
    "yandexcloud",
    "yandex.net",
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
    "ngenix",
    "mwscdn",
    "dendiboss",
    "dendibase",
)

BYPASS_LABEL_MARKERS = (
    "[bl]",
    "white list",
    "whitelist",
    "обход",
    "*cidr*",
    "cidr]",
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
    security = (_query_params(uri).get("security") or "").strip().lower()
    if security:
        return security
    if uri.lower().startswith("trojan://"):
        return "tls"
    return ""


def get_transport(uri: str) -> str:
    return (_query_params(uri).get("type") or "tcp").strip().lower()


def get_sni(uri: str) -> str | None:
    params = _query_params(uri)
    sni = (params.get("sni") or params.get("host") or "").strip()
    return sni or None


def get_fragment(uri: str) -> str:
    if "#" not in uri:
        return ""
    return urllib.parse.unquote(uri.split("#", 1)[1]).lower()


def is_bypass_label(uri: str) -> bool:
    fragment = get_fragment(uri)
    return any(marker in fragment for marker in BYPASS_LABEL_MARKERS)


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


def parse_vpn_configs(data: str) -> list[str]:
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


def is_bypass_whitelist_config(uri: str) -> bool:
    """Конфиг подходит для обхода белых списков (расширенные правила)."""
    uri_l = uri.lower()
    if not uri_l.startswith(("vless://", "trojan://")):
        return False
    if INSECURE_PATTERN.search(urllib.parse.unquote(uri)):
        return False

    security = get_security(uri)
    sni = (get_sni(uri) or "").lower()

    if uri_l.startswith("vless://"):
        if security == "reality" and is_ru_whitelist_sni(get_sni(uri)):
            return True
        if security == "tls" and sni and is_ru_whitelist_sni(get_sni(uri)):
            return True

    if uri_l.startswith("trojan://") and security in ("tls", "reality", ""):
        if is_bypass_label(uri) or is_ru_whitelist_sni(get_sni(uri)):
            return True

    if is_bypass_label(uri) and security in ("tls", "reality"):
        return True

    return is_whitelist_config(uri)


def bypass_whitelist_score(uri: str) -> int:
    score = whitelist_score(uri)
    fragment = get_fragment(uri)
    security = get_security(uri)
    transport = get_transport(uri)
    sni_l = (get_sni(uri) or "").lower()

    # Проверенные на мобильном БС SNI — максимальный приоритет
    if "loadtest.dev.urent.ru" in sni_l:
        score += 200
    if "sfera.x5.ru" in sni_l:
        score += 200
    if sni_l == "www.vk.com" or sni_l.endswith(".vk.com"):
        score += 180
    if "top707762634.mwscdn.ru" in sni_l or "mwscdn.ru" in sni_l:
        score += 200

    # grpc-Reality и ws-TLS — типичные рабочие обходы
    if transport == "grpc" and security == "reality":
        score += 80
    if transport == "ws" and security == "tls":
        score += 80

    if "[bl]" in fragment:
        score += 30
    if "white list" in fragment:
        score += 25
    if "*cidr*" in fragment or "[*cidr*]" in fragment:
        score += 40
    if "обход" in fragment:
        score += 35

    if "ads.x5.ru" in sni_l or "cdp.x5.ru" in sni_l:
        score += 45
    if "storage.yandex.net" in sni_l:
        score += 40
    if "ngenix" in sni_l:
        score += 35

    if uri.lower().startswith("trojan://") and is_bypass_label(uri):
        score += 25

    # dendibase и прочие — ниже приоритет без российского CDN SNI
    if "dendibase" in sni_l or "dendiboss" in sni_l:
        score -= 50

    return score


def speed_score(uri: str) -> int:
    """Приоритет для более быстрых/качественных конфигов в ключе."""
    uri_l = uri.lower()
    score = bypass_whitelist_score(uri)
    transport = get_transport(uri)
    security = get_security(uri)
    hostport = extract_host_port(uri)
    fragment = get_fragment(uri)

    # Hysteria2 обычно даёт лучший throughput (в АВТО пока не конвертим)
    if uri_l.startswith(("hysteria2://", "hy2://")):
        score += 120

    # Vision + TCP Reality — лучший баланс скорости на мобильном БС
    if "flow=xtls-rprx-vision" in uri_l and transport in ("tcp", "raw", ""):
        score += 120
    elif transport in ("tcp", "raw", "") and security == "reality":
        score += 70
    elif transport in ("tcp", "raw", ""):
        score += 35

    # gRPC/WS чаще медленнее и нестабильнее при смене сети
    if transport == "grpc":
        score -= 50
    if transport == "ws":
        score -= 35
    if transport == "xhttp":
        score -= 25

    if security == "reality":
        score += 30

    if hostport:
        port = hostport[1]
        if port == 443:
            score += 25
        elif port in (8443, 7443, 5443):
            score += 10
        elif port == 80:
            score -= 50

    # Метки мобильного CIDR / white-list из источников igareck
    if "*cidr*" in fragment or "[*cidr*]" in fragment:
        score += 60
    if "white" in fragment and "list" in fragment:
        score += 40
    if "mobile" in fragment or "телефон" in fragment:
        score += 35

    if "anycast" in fragment:
        score += 15
    # Не бустим по «стране в названии» — это не скорость
    if "finland" in fragment or "estonia" in fragment:
        score += 5

    return score


def is_lte_fast_candidate(uri: str) -> bool:
    """
    LTE АВТО: только стабильные быстрые транспорты.
    gRPC/WS/xhttp часто дают «живой» пинг, но мизерный throughput до YouTube.
    """
    transport = get_transport(uri)
    if transport in ("grpc", "ws", "xhttp", "h2", "httpupgrade", "splithttp"):
        return False
    if transport not in ("tcp", "raw", ""):
        return False
    security = get_security(uri)
    if security not in ("reality", "tls"):
        return False
    # Нужен рабочий Reality/TLS endpoint
    if security == "reality" and not (_query_params(uri).get("pbk") or "").strip():
        return False
    return True


def lte_speed_score(uri: str) -> int:
    """Эвристика «быстрее до YouTube/Instagram» для обхода LTE."""
    score = speed_score(uri)
    uri_l = uri.lower()
    transport = get_transport(uri)
    security = get_security(uri)
    sni = (get_sni(uri) or "").lower()
    hostport = extract_host_port(uri)

    if "flow=xtls-rprx-vision" in uri_l and transport in ("tcp", "raw", ""):
        score += 80
    if security == "reality" and transport in ("tcp", "raw", ""):
        score += 40
    if hostport and hostport[1] == 443:
        score += 30

    # RU CDN SNI обычно лучше проходит мобильный БС к зарубежным сервисам
    if is_ru_whitelist_sni(sni):
        score += 50
    if any(x in sni for x in ("vk.com", "vkvideo", "yandex", "mail.ru", "okcdn", "mycdn")):
        score += 40

    return score


def is_lte_eligible(uri: str, min_score: int = 45) -> bool:
    """
    LTE whitelist bypass: TCP/Vision Reality, RU SNI or CIDR label, port 443 (или vision+RU на 5443/8443).
    Отсекает gRPC/dl.google.com/нестандартные порты — типичные ложные «рабочие» конфиги.
    """
    uri_l = uri.lower()
    if not uri_l.startswith(("vless://", "trojan://")):
        return False
    if INSECURE_PATTERN.search(urllib.parse.unquote(uri)):
        return False
    if not is_lte_fast_candidate(uri):
        return False

    sni = get_sni(uri)
    sni_l = (sni or "").lower()
    if any(bad in sni_l for bad in BAD_WHITELIST_SNI):
        return False
    if "dl.google" in sni_l:
        return False

    hostport = extract_host_port(uri)
    if not hostport:
        return False
    port = hostport[1]
    has_vision = "flow=xtls-rprx-vision" in uri_l
    ru_sni = is_ru_whitelist_sni(sni)

    if port == 443:
        pass
    elif port in (5443, 8443) and ru_sni and has_vision:
        pass
    else:
        return False

    fragment = get_fragment(uri)
    bypass = bypass_whitelist_score(uri)
    if ru_sni or is_bypass_label(uri):
        return bypass >= min_score - 15
    if "*cidr*" in fragment or "[*cidr*]" in fragment:
        return bypass >= min_score - 10
    return bypass >= min_score


def rank_lte_configs(uris: list[str], min_score: int = 45) -> list[str]:
    """Один лучший вариант на host:port, только LTE-eligible, сортировка по lte_speed_score."""
    best_by_host: dict[str, tuple[int, str]] = {}

    for uri in uris:
        if not is_lte_eligible(uri, min_score=min_score):
            continue
        hostport = extract_host_port(uri)
        if not hostport:
            continue
        key = f"{hostport[0].lower()}:{hostport[1]}"
        scored = lte_speed_score(uri)
        prev = best_by_host.get(key)
        if prev is None or scored > prev[0]:
            best_by_host[key] = (scored, uri)

    ranked = sorted(best_by_host.values(), key=lambda item: item[0], reverse=True)
    return [uri for _, uri in ranked]


def rank_configs_for_speed(uris: list[str]) -> list[str]:
    """Без РФ, один лучший конфиг на host:port, сортировка по speed_score."""
    best_by_host: dict[str, tuple[int, str]] = {}
    no_host: list[tuple[int, str]] = []

    for uri in uris:
        if is_russian_config(uri):
            continue
        hostport = extract_host_port(uri)
        scored = speed_score(uri)
        if not hostport:
            no_host.append((scored, uri))
            continue
        key = f"{hostport[0].lower()}:{hostport[1]}"
        prev = best_by_host.get(key)
        if prev is None or scored > prev[0]:
            best_by_host[key] = (scored, uri)

    ranked = list(best_by_host.values()) + no_host
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [uri for _, uri in ranked]


def parse_whitelist_configs(data: str) -> list[str]:
    """Парсит конфиги для обхода белых списков — Reality/TLS + российский SNI."""
    return _parse_bypass_candidates(data, min_score=50)


def parse_bypass_subscription(data: str) -> list[str]:
    """Парсит агрегированную подписку обходов (bypass-all и аналоги)."""
    return _parse_bypass_candidates(data, min_score=40)


def parse_subscription_lines(data: str) -> list[str]:
    """Все поддерживаемые конфиги из файла подписки (без фильтра SNI)."""
    result: list[str] = []
    seen: set[str] = set()

    for line in _split_config_lines(data):
        line_stripped = normalize_uri(line.strip())
        if not line_stripped or line_stripped.startswith("#"):
            continue
        if not line_stripped.lower().startswith(SUPPORTED_PREFIXES):
            continue
        if INSECURE_PATTERN.search(urllib.parse.unquote(line_stripped)):
            continue
        processed = html.unescape(urllib.parse.unquote(line_stripped))
        if processed in seen:
            continue
        seen.add(processed)
        result.append(processed)

    return result


def parse_bypass_subscription_all(data: str) -> list[str]:
    return parse_subscription_lines(data)


def _parse_bypass_candidates(data: str, min_score: int) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    for line in _split_config_lines(data):
        line_stripped = normalize_uri(line.strip())
        if not line_stripped or line_stripped.startswith("#"):
            continue
        processed = urllib.parse.unquote(line_stripped)
        if not is_bypass_whitelist_config(processed):
            continue
        if bypass_whitelist_score(processed) < min_score:
            continue
        if processed in seen:
            continue
        seen.add(processed)
        candidates.append(processed)

    candidates.sort(key=bypass_whitelist_score, reverse=True)
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


# Флаг страны в remark (Happ берёт первый emoji как иконку сервера)
_COUNTRY_FLAG_RE = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}")
RUSSIA_FLAG = "🇷🇺"
_RUSSIA_MARKERS = (
    "russia",
    "россий",
    "россия",
    " рф",
    "rf ",
)


def extract_country_flag(uri: str) -> str:
    """Извлекает emoji-флаг из исходного названия конфига."""
    if "#" not in uri:
        return ""
    fragment = urllib.parse.unquote(uri.split("#", 1)[1])
    match = _COUNTRY_FLAG_RE.search(fragment)
    return match.group(0) if match else ""


def is_russian_config(uri: str) -> bool:
    """Конфиг помечен как российский (флаг/название в remark)."""
    fragment = get_fragment(uri)
    if not fragment:
        return False
    if RUSSIA_FLAG in fragment:
        return True
    return any(marker in fragment for marker in _RUSSIA_MARKERS)


def build_server_label(category: str, uri: str, index: int) -> str:
    """Подпись сервера в подписке — флаг страны и номер."""
    flag = extract_country_flag(uri) or "🌐"
    if flag == RUSSIA_FLAG:
        flag = "🌐"
    return f"{flag} {config.BOT_NAME} · Сервер #{index}"


def brand_config(uri: str, label: str) -> str:
    base = uri.split("#", 1)[0]
    return f"{base}#{urllib.parse.quote(label, safe='')}"
