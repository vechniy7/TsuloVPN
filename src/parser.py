import base64
import copy
import html
import ipaddress
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

# Известные подсети RU-cloud / whitelist CIDR (Yandex, VK, Selectel, …)
RU_CLOUD_IP_PREFIXES: tuple[str, ...] = (
    "5.188.",
    "5.189.",
    "5.35.",
    "31.130.",
    "37.139.",
    "45.12.",
    "45.146.",
    "46.8.",
    "46.253.",
    "51.250.",
    "77.110.",
    "82.117.",
    "83.168.",
    "84.32.",
    "89.208.",
    "91.185.",
    "91.240.",
    "95.163.",
    "158.160.",
    "178.154.",
    "185.221.",
    "193.168.",
    "194.55.",
    "217.16.",
)

_cidr_networks: list[ipaddress.IPv4Network] | None = None


def set_whitelist_cidrs(lines: list[str]) -> None:
    """Подгрузка cidrwhitelist.txt (hxehex) для точного матча IP."""
    global _cidr_networks
    nets: list[ipaddress.IPv4Network] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            nets.append(ipaddress.ip_network(line, strict=False))
        except ValueError:
            continue
    _cidr_networks = nets or None


def is_whitelist_host_ip(host: str) -> bool:
    """IP сервера в типичных whitelist-подсетях RU-cloud."""
    try:
        ip = ipaddress.ip_address(host.strip())
    except ValueError:
        return False
    if not isinstance(ip, ipaddress.IPv4Address):
        return False
    if _cidr_networks:
        return any(ip in net for net in _cidr_networks)
    text = str(ip)
    return any(text.startswith(p) for p in RU_CLOUD_IP_PREFIXES)


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
            stripped = decoded.lstrip()
            if stripped.startswith("{") or stripped.startswith("["):
                return decoded
        except Exception:
            pass
    return data


def _xray_outbound_to_uri(outbound: dict, remark: str = "") -> str | None:
    """Конвертация Xray outbound (Remnawave JSON) → share-link URI."""
    protocol = str(outbound.get("protocol") or "").lower()
    if protocol not in ("vless", "trojan", "vmess", "shadowsocks"):
        return None

    stream = outbound.get("streamSettings") or {}
    network = str(stream.get("network") or "tcp").lower()
    security = str(stream.get("security") or "none").lower()
    params: dict[str, str] = {"encryption": "none", "type": network, "security": security}

    if network == "ws":
        ws = stream.get("wsSettings") or {}
        path = ws.get("path") or "/"
        params["path"] = str(path)
        headers = ws.get("headers") or {}
        if headers.get("Host"):
            params["host"] = str(headers["Host"])
    elif network == "grpc":
        grpc = stream.get("grpcSettings") or {}
        if grpc.get("serviceName"):
            params["serviceName"] = str(grpc["serviceName"])
    elif network == "httpupgrade":
        hu = stream.get("httpupgradeSettings") or stream.get("httpUpgradeSettings") or {}
        if hu.get("path"):
            params["path"] = str(hu["path"])
        if hu.get("host"):
            params["host"] = str(hu["host"])

    if security == "reality":
        rs = stream.get("realitySettings") or {}
        sni = rs.get("serverName") or rs.get("server_name") or ""
        if sni:
            params["sni"] = str(sni)
        pbk = rs.get("publicKey") or rs.get("public_key") or ""
        if pbk:
            params["pbk"] = str(pbk)
        sid = rs.get("shortId") or rs.get("short_id") or ""
        if sid:
            params["sid"] = str(sid)
        fp = rs.get("fingerprint") or "chrome"
        params["fp"] = str(fp)
        spx = rs.get("spiderX") or rs.get("spider_x") or ""
        if spx:
            params["spx"] = str(spx)
    elif security in ("tls", "xtls"):
        ts = stream.get("tlsSettings") or {}
        sni = ts.get("serverName") or ""
        if sni:
            params["sni"] = str(sni)
        fp = ts.get("fingerprint") or ""
        if fp:
            params["fp"] = str(fp)
        alpn = ts.get("alpn")
        if isinstance(alpn, list) and alpn:
            params["alpn"] = ",".join(str(x) for x in alpn)

    host = ""
    port = 0
    userinfo = ""

    if protocol == "vless":
        settings = outbound.get("settings") or {}
        vnext = (settings.get("vnext") or [{}])[0]
        host = str(vnext.get("address") or "")
        port = int(vnext.get("port") or 0)
        user = (vnext.get("users") or [{}])[0]
        userinfo = str(user.get("id") or "")
        if user.get("encryption"):
            params["encryption"] = str(user["encryption"])
        if user.get("flow"):
            params["flow"] = str(user["flow"])
        scheme = "vless"
    elif protocol == "trojan":
        settings = outbound.get("settings") or {}
        server = (settings.get("servers") or [{}])[0]
        host = str(server.get("address") or "")
        port = int(server.get("port") or 0)
        userinfo = str(server.get("password") or "")
        scheme = "trojan"
    elif protocol == "vmess":
        settings = outbound.get("settings") or {}
        vnext = (settings.get("vnext") or [{}])[0]
        host = str(vnext.get("address") or "")
        port = int(vnext.get("port") or 0)
        user = (vnext.get("users") or [{}])[0]
        userinfo = str(user.get("id") or "")
        if user.get("alterId") is not None:
            params["aid"] = str(user.get("alterId"))
        if user.get("security"):
            params["scy"] = str(user.get("security"))
        scheme = "vmess"
    else:
        return None

    if not host or not port or not userinfo:
        return None
    if host in ("0.0.0.0", "127.0.0.1", "localhost"):
        return None

    query = urllib.parse.urlencode(params, safe=",:/")
    label = urllib.parse.quote(remark or outbound.get("tag") or host, safe="")
    return f"{scheme}://{userinfo}@{host}:{port}?{query}#{label}"


_FLAG_RE = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}")

_SKIP_NAME_MARKERS = (
    "[free]",
    "только tg",
    "tg бот",
    "tg bot",
    "бот + сайт",
    "бот  сайт",
    "hysteria",
    "x-hwid",
    "hwid",
    "превысили лимит",
    "необходимо передавать",
)

# Happ ставит иконкой только флаг страны (regional indicators) в начале remark.
# Обычные ⚡/📱 остаются в тексте, а иконка становится планетой — поэтому тут флаги.
_DECOR_RE = re.compile(
    r"[\U000026A1\U0000FE0F\U00002728\U0001F4A1\U0001F525\U00002B50"
    r"\U0001F9F6\U0001F4A7\U0001F525]+"
)

_NAME_RESTYLE: tuple[tuple[str, str], ...] = (
    ("самый быстрый авто", "🇪🇺 Автовыбор"),
    ("автовыбор", "🇪🇺 Автовыбор"),
    ("lte авто", "🇫🇮 LTE Авто"),
    ("lte reserve", "🇫🇮 LTE Резерв"),
    ("lte резерв", "🇫🇮 LTE Резерв"),
    ("lte #1", "🇫🇮 LTE 1"),
    ("lte #2", "🇫🇮 LTE 2"),
    ("lte #3", "🇫🇮 LTE 3"),
    ("lte 1", "🇫🇮 LTE 1"),
    ("lte 2", "🇫🇮 LTE 2"),
    ("lte 3", "🇫🇮 LTE 3"),
    ("нидерланды", "🇳🇱 Нидерланды"),
    ("великобритания", "🇬🇧 Британия"),
    ("германия", "🇩🇪 Германия"),
    ("финляндия", "🇫🇮 Финляндия"),
    ("хельсинки", "🇫🇮 Финляндия"),
    ("швеция", "🇸🇪 Швеция"),
    ("эстония", "🇪🇪 Эстония"),
    ("польша", "🇵🇱 Польша"),
    ("литва", "🇱🇹 Литва"),
    ("латвия", "🇱🇻 Латвия"),
    ("франция", "🇫🇷 Франция"),
    ("италия", "🇮🇹 Италия"),
    ("венгрия", "🇭🇺 Венгрия"),
    ("турция", "🇹🇷 Турция"),
    ("казахстан", "🇰🇿 Казахстан"),
    ("россия", "🇷🇺 Россия"),
    ("сша", "🇺🇸 США"),
    ("кипр", "🇨🇾 Кипр"),
    ("норвегия", "🇳🇴 Норвегия"),
    ("монако", "🇲🇨 Монако"),
    ("швейцария", "🇨🇭 Швейцария"),
    ("болгария", "🇧🇬 Болгария"),
    ("чехия", "🇨🇿 Чехия"),
)

_MOBILE_INTERNET_MARKERS = (
    "белые списки",
    "белый список",
    "обход белых",
    "white list",
    "whitelist",
    "[bl]",
    "*cidr*",
    "cidr]",
    "мобильный интернет",
    "мобильная связь",
    "mobile internet",
    "обход lte",
    "lte обход",
    "обход глушил",
    "глушилок",
    "глушилк",
    "anti-dpi",
    "antidpi",
    "bypass",
)

_LTE_NAME_RE = re.compile(
    r"(?:^|[\s|\[\(·])lte(?:[\s#\-]|$|\d|\)|\]|$)",
    re.IGNORECASE,
)


def is_bypass_profile_name(name: str) -> bool:
    """Конфиг обхода глушилок / белых списков / LTE по названию в подписке."""
    if is_mobile_internet_name(name):
        return True
    compact = " ".join((name or "").lower().split())
    noflag = _FLAG_RE.sub(" ", compact)
    noflag = _DECOR_RE.sub(" ", noflag)
    noflag = re.sub(r"\s+", " ", noflag).strip()
    if _LTE_NAME_RE.search(noflag):
        return True
    if noflag in ("lte", "bl", "cidr"):
        return True
    return False


def is_mobile_internet_name(name: str) -> bool:
    """Серверы обхода белых списков (бывш. «Белые списки» / «Обход Wi-Fi»)."""
    compact = " ".join((name or "").lower().split())
    noflag = _FLAG_RE.sub(" ", compact)
    noflag = _DECOR_RE.sub(" ", noflag)
    noflag = re.sub(r"\s+", " ", noflag).strip()
    if re.search(r"обход\s*wi", noflag):
        return True
    return any(marker in noflag for marker in _MOBILE_INTERNET_MARKERS)


EXTRA_BYPASS_FIRE = "🔥"


def mobile_internet_label(index: int, *, extra: bool = False) -> str:
    label = f"🇪🇺 Мобильный Интернет #{index}"
    if extra:
        return f"{label} {EXTRA_BYPASS_FIRE}"
    return label


def is_extra_bypass_label(name: str) -> bool:
    return EXTRA_BYPASS_FIRE in (name or "")


def uri_profile_name(uri: str) -> str:
    if "#" not in uri:
        return ""
    return urllib.parse.unquote(uri.split("#", 1)[1]).strip()


def is_bypass_uri(uri: str) -> bool:
    name = uri_profile_name(uri)
    return is_bypass_profile_name(name) or is_bypass_label(uri)


def split_uris_by_bypass(uris: list[str]) -> tuple[list[str], list[str]]:
    """Разделить URI на основные и обходные (глушилки / LTE / белые списки)."""
    main: list[str] = []
    bypass: list[str] = []
    for uri in uris:
        if is_placeholder_config(uri):
            continue
        if is_bypass_uri(uri):
            bypass.append(uri)
        else:
            main.append(uri)
    return main, bypass


def filter_bypass_uris(uris: list[str]) -> list[str]:
    """Только обходные конфиги по названию / метке [BL]."""
    return [uri for uri in uris if not is_placeholder_config(uri) and is_bypass_uri(uri)]


def select_extra_bypass_uris(uris: list[str]) -> list[str]:
    """
    Конфиги из VPN_BYPASS_SOURCE_URL:
    1) по названию (LTE, белые списки, …)
    2) по SNI/протоколу (whitelist bypass)
    3) иначе все конфиги ключа (отдельная подписка обхода)
    """
    real = [uri for uri in uris if not is_placeholder_config(uri)]
    if not real:
        return []

    named = filter_bypass_uris(real)
    if named:
        return dedupe_uris(named)

    sni_based = [uri for uri in real if is_bypass_whitelist_config(uri)]
    if sni_based:
        return dedupe_uris(sni_based)

    return dedupe_uris(real)


def dedupe_uris(uris: list[str], *, exclude_bases: set[str] | None = None) -> list[str]:
    seen: set[str] = set(exclude_bases or ())
    result: list[str] = []
    for uri in uris:
        base = uri.split("#", 1)[0].strip().lower()
        if not base or base in seen:
            continue
        seen.add(base)
        result.append(uri)
    return result


def uri_identity(uri: str) -> str:
    return uri.split("#", 1)[0].strip().lower()


def brand_main_uris(uris: list[str]) -> list[str]:
    """Основные серверы — названия чуть другие, не 1:1 с источником."""
    seen: set[str] = set()
    result: list[str] = []
    fallback_idx = 0
    for uri in uris:
        if is_placeholder_config(uri) or is_bypass_uri(uri):
            continue
        original = uri_profile_name(uri)
        styled = restyle_server_name(original) if original else None
        if not styled:
            fallback_idx += 1
            styled = build_server_label("vpn", uri, fallback_idx)
        key = styled.lower()
        if key in seen or should_skip_profile(styled) or should_skip_profile(original):
            continue
        seen.add(key)
        result.append(brand_config(uri, styled))
    return result


def brand_bypass_uris(
    uris: list[str],
    *,
    start_index: int = 1,
    extra: bool = False,
) -> list[str]:
    """Обходные серверы — «🇪🇺 Мобильный Интернет #N» (+ 🔥 для доп. ключа)."""
    unique = dedupe_uris([uri for uri in uris if not is_placeholder_config(uri)])
    return [
        brand_config(uri, mobile_internet_label(idx, extra=extra))
        for idx, uri in enumerate(unique, start=start_index)
    ]


def renumber_mobile_profiles(profiles: list[dict]) -> list[dict]:
    """Переименовать обходные серверы в «Мобильный Интернет #N» (+ 🔥 для доп. ключа)."""
    mobile_idx = 0
    result: list[dict] = []
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        remark = str(profile.get("remarks") or profile.get("remark") or "")
        is_bypass = is_bypass_profile_name(remark) or is_extra_bypass_label(remark)
        if is_bypass:
            mobile_idx += 1
            cloned = copy.deepcopy(profile)
            cloned["remarks"] = mobile_internet_label(
                mobile_idx,
                extra=is_extra_bypass_label(remark),
            )
            result.append(cloned)
        else:
            result.append(profile)
    return result


def should_skip_profile(name: str) -> bool:
    compact = " ".join((name or "").lower().split())
    return any(marker in compact for marker in _SKIP_NAME_MARKERS)


def restyle_server_name(name: str) -> str | None:
    """Чуть другие названия, тот же смысл. None = не выдавать."""
    raw = " ".join((name or "").split()).strip()
    if not raw or should_skip_profile(raw):
        return None

    compact = raw.lower()
    noflag = _FLAG_RE.sub(" ", compact)
    noflag = _DECOR_RE.sub(" ", noflag)
    noflag = re.sub(r"\s+", " ", noflag).strip()
    flags = _FLAG_RE.findall(raw)
    flag = flags[0] if flags else ""

    if "игровой" in noflag:
        num = ""
        match = re.search(r"(\d+)", noflag)
        if match:
            num = f" {match.group(1)}"
        return f"{flag or '🎮'} Игровой{num}".strip()

    for needle, styled in _NAME_RESTYLE:
        if needle in noflag or needle in compact:
            styled_flag = _FLAG_RE.findall(styled)
            styled_text = _FLAG_RE.sub(" ", styled).strip()
            styled_text = _DECOR_RE.sub(" ", styled_text).strip()
            use_flag = flag or (styled_flag[0] if styled_flag else "")
            if use_flag and styled_text:
                return f"{use_flag} {styled_text}"
            return styled

    cleaned = _FLAG_RE.sub(" ", raw)
    cleaned = _DECOR_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ·-–|")
    if flag and cleaned:
        return f"{flag} {cleaned}"
    return cleaned or raw


def _outbound_score(outbound: dict) -> int:
    """Чем выше — тем стабильнее для Happ (tcp+reality+443+vision)."""
    proto = str(outbound.get("protocol") or "").lower()
    if proto not in ("vless", "trojan"):
        return -1

    stream = outbound.get("streamSettings") or {}
    network = str(stream.get("network") or "tcp").lower()
    if network in ("xhttp", "splithttp"):
        return -1
    security = str(stream.get("security") or "").lower()

    port = 0
    flow = ""
    settings = outbound.get("settings") or {}
    if proto == "vless":
        vnext = (settings.get("vnext") or [{}])[0]
        port = int(vnext.get("port") or 0)
        user = (vnext.get("users") or [{}])[0]
        flow = str(user.get("flow") or "").lower()
    else:
        server = (settings.get("servers") or [{}])[0]
        port = int(server.get("port") or 0)

    score = 10
    if proto == "vless":
        score += 40
    if security == "reality":
        score += 50
    elif security == "tls":
        score += 20
    if network == "tcp":
        score += 35
    elif network == "grpc":
        score += 8
    elif network == "ws":
        score += 4
    if port == 443:
        score += 20
    elif port in (8443, 2053, 2083, 2087, 2096):
        score += 5
    if "vision" in flow:
        score += 15
    return score


def _best_outbound(outbounds: list) -> dict | None:
    best: dict | None = None
    best_score = -1
    for outbound in outbounds:
        if not isinstance(outbound, dict):
            continue
        proto = str(outbound.get("protocol") or "").lower()
        if proto in ("freedom", "blackhole", "dns", "loopback"):
            continue
        score = _outbound_score(outbound)
        if score > best_score:
            best_score = score
            best = outbound
    return best if best_score >= 0 else None


def extract_uris_from_xray_json(data: str) -> list[str]:
    """Один рабочий share-link на профиль (как в оригинальном клиенте)."""
    text = data.strip()
    if not text or text[0] not in "[{":
        return []
    try:
        payload = json.loads(text)
    except Exception:
        return []

    profiles: list[dict]
    if isinstance(payload, list):
        profiles = [p for p in payload if isinstance(p, dict)]
    elif isinstance(payload, dict):
        profiles = [payload]
    else:
        return []

    uris: list[str] = []
    seen_names: set[str] = set()
    for profile in profiles:
        remark = str(profile.get("remarks") or profile.get("remark") or "")
        styled = restyle_server_name(remark)
        if not styled or styled.lower() in seen_names:
            continue
        outbounds = profile.get("outbounds") or []
        if not isinstance(outbounds, list):
            continue
        best = _best_outbound(outbounds)
        if not best:
            continue
        uri = _xray_outbound_to_uri(best, styled)
        if not uri:
            continue
        seen_names.add(styled.lower())
        uris.append(uri)
    return uris


_NON_PROXY_PROTOCOLS = frozenset({"freedom", "blackhole", "dns", "loopback"})


def extract_happ_json_profiles(data: str) -> list[dict]:
    """Оригинальные Xray-профили Happ (JSON). Без vless:// — в клиенте нет «Копировать URL»."""
    text = data.strip()
    if not text or text[0] not in "[{":
        return []
    try:
        payload = json.loads(text)
    except Exception:
        return []

    if isinstance(payload, list):
        profiles = [p for p in payload if isinstance(p, dict)]
    elif isinstance(payload, dict):
        profiles = [payload]
    else:
        return []

    result: list[dict] = []
    seen_names: set[str] = set()
    for profile in profiles:
        remark = str(profile.get("remarks") or profile.get("remark") or "")
        if is_bypass_profile_name(remark):
            styled = remark
        else:
            styled = restyle_server_name(remark)
        if not styled or styled.lower() in seen_names:
            continue
        outbounds = profile.get("outbounds") or []
        if not isinstance(outbounds, list):
            continue
        has_proxy = any(
            isinstance(outbound, dict)
            and str(outbound.get("protocol") or "").lower() not in _NON_PROXY_PROTOCOLS
            for outbound in outbounds
        )
        if not has_proxy:
            continue
        cloned = copy.deepcopy(profile)
        cloned["remarks"] = styled
        seen_names.add(styled.lower())
        result.append(cloned)
    return result


def _split_config_lines(data: str) -> list[str]:
    data = try_decode_base64(data)
    json_uris = extract_uris_from_xray_json(data.strip())
    if json_uris:
        return json_uris
    pattern = "|".join(p.replace("://", "") for p in PROTOCOL_PREFIXES)
    data = re.sub(rf"({pattern})://", r"\n\1://", data, flags=re.IGNORECASE)
    return data.splitlines()


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
    LTE АВТО: TCP/Vision или gRPC:443+Reality.
    WS/xhttp на мобильном БС нестабильны.
    """
    transport = get_transport(uri)
    security = get_security(uri)
    hostport = extract_host_port(uri)

    if transport in ("ws", "xhttp", "h2", "httpupgrade", "splithttp"):
        return False
    if transport == "grpc":
        if not hostport or hostport[1] != 443 or security != "reality":
            return False
        if not is_ru_whitelist_sni(get_sni(uri)) and not is_bypass_label(uri):
            return False
        return bool((_query_params(uri).get("pbk") or "").strip())
    if transport not in ("tcp", "raw", ""):
        return False
    if security not in ("reality", "tls"):
        return False
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

    if hostport and is_whitelist_host_ip(hostport[0]):
        score += 250

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
    elif port == 443 and get_transport(uri) == "grpc" and ru_sni:
        pass
    else:
        return False

    bypass = bypass_whitelist_score(uri)
    fragment = get_fragment(uri)

    # На LTE whitelist критичен IP из белого списка (RU-cloud)
    if is_whitelist_host_ip(hostport[0]):
        return bypass >= min_score - 25

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


_FP_RANK = {
    "firefox": 20,
    "chrome": 12,
    "edge": 8,
    "safari": 6,
    "ios": 5,
    "android": 4,
    "qq": 2,
}

# Хостинги из zieng2 с 🇷🇺 — пингуются, интернета нет
RU_HOSTING_MARKERS = (
    "timeweb",
    "spaceweb",
    "xorek",
    "selectel",
    "beget",
    "aeza",
    "ihc",
    "megamax",
    "4vps",
    "vypnet",
    "ufo hosting",
    "reg.ru",
)

PREFERRED_EU_FLAGS = ("🇳🇱", "🇸🇪", "🇪🇪", "🇩🇪", "🇫🇷", "🇱🇹", "🇫🇮")
PREFERRED_EU_NAMES = (
    "netherland",
    "sweden",
    "estonia",
    "germany",
    "france",
    "lithuania",
    "finland",
    "niederlande",
    "schweden",
    "estland",
    "deutschland",
    "frankreich",
    "lietuva",
    "suomi",
)

# Подтверждённый живой узел (Ingushetia LTE): Reality+Vision, SNI yandexcloud, 🇸🇪
KNOWN_WORKING_HOSTS = ("46.8.210.148",)
KNOWN_WORKING_UUIDS = ("daa246bf-ed1e-0001-8959-cf4aa67b913e",)


def is_ru_hosting_config(uri: str) -> bool:
    """Российский флаг или RU-хостинг из источника — не класть в ключ."""
    if is_russian_config(uri):
        return True
    fragment = get_fragment(uri)
    return any(marker in fragment for marker in RU_HOSTING_MARKERS)


def zieng_working_score(uri: str) -> int:
    """
    Живые у клиента: зарубежный флаг (NL/SE/EE/DE/FR/LT/FI) + Reality Vision + RU SNI.
    RU-хостинги и 🇷🇺 не скорим — их отсекает is_ru_hosting_config.
    """
    uri_l = uri.lower()
    if not uri_l.startswith("vless://"):
        return 0
    params = _query_params(uri)
    transport = get_transport(uri)
    security = get_security(uri)
    sni = (get_sni(uri) or "").lower()
    hostport = extract_host_port(uri)
    fragment = get_fragment(uri)
    flag = extract_country_flag(uri)
    score = 10

    if flag in PREFERRED_EU_FLAGS:
        score += 80
    if any(name in fragment for name in PREFERRED_EU_NAMES):
        score += 40

    if "flow=xtls-rprx-vision" in uri_l and transport in ("tcp", "raw", ""):
        score += 140
    if security == "reality" and transport in ("tcp", "raw", ""):
        score += 80
    if security == "reality":
        score += 20

    if hostport:
        port = hostport[1]
        if port == 443:
            score += 50
        elif port in (8443, 5443, 7443):
            score += 15
        elif port in (2200, 4100):
            score -= 80
        elif port == 80:
            score -= 50

    if is_ru_whitelist_sni(sni):
        score += 70
    if "yandexcloud" in sni or "smartcaptcha" in sni:
        score += 50
    if any(x in sni for x in ("vk.com", "max.ru", "yandex", "ads.x5.ru", "ya.ru")):
        score += 30

    if transport in ("ws", "xhttp"):
        score -= 40
    if transport == "grpc":
        score -= 30

    fp = (params.get("fp") or "").strip().lower()
    score += _FP_RANK.get(fp, 0)

    uuid = uri.split("://", 1)[-1].split("@", 1)[0].lower()
    host = (hostport[0] if hostport else "").lower()
    if uuid in KNOWN_WORKING_UUIDS or host in KNOWN_WORKING_HOSTS:
        score += 1000
    return score


def rank_universal_configs(uris: list[str], limit: int = 50) -> list[str]:
    """Без РФ/Timeweb/SpaceWeb/Xorek. Один host:port, топ-limit."""
    best_by_host: dict[str, tuple[int, str]] = {}

    for uri in uris:
        if INSECURE_PATTERN.search(urllib.parse.unquote(uri)):
            continue
        if not uri.lower().startswith("vless://"):
            continue
        if is_ru_hosting_config(uri):
            continue
        hostport = extract_host_port(uri)
        if not hostport:
            continue
        key = f"{hostport[0].lower()}:{hostport[1]}"
        scored = zieng_working_score(uri)
        prev = best_by_host.get(key)
        if prev is None or scored > prev[0]:
            best_by_host[key] = (scored, uri)

    ranked = sorted(best_by_host.values(), key=lambda item: item[0], reverse=True)
    return [uri for _, uri in ranked[: max(1, limit)]]


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


_PLACEHOLDER_MARKERS = (
    "не поддерживается",
    "превышено число",
    "превышено",
    "превысили лимит",
    "device limit",
    "not supported",
    "x-hwid",
    "hwid",
    "необходимо передавать",
    "00000000-0000-0000-0000-000000000000",
)


def is_placeholder_config(uri: str) -> bool:
    """Заглушки Remnawave (HWID / device limit), не рабочие узлы."""
    if not uri:
        return True
    lower = uri.lower()
    if "00000000-0000-0000-0000-000000000000" in lower:
        return True
    hp = extract_host_port(uri)
    if hp and hp[0] in ("0.0.0.0", "127.0.0.1", "::", "localhost"):
        return True
    try:
        frag = urllib.parse.unquote(uri.split("#", 1)[1]).lower() if "#" in uri else ""
    except Exception:
        frag = ""
    return any(m in frag or m in lower for m in _PLACEHOLDER_MARKERS)


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
        if is_placeholder_config(processed):
            continue
        name = urllib.parse.unquote(processed.split("#", 1)[1]) if "#" in processed else ""
        if should_skip_profile(name) or restyle_server_name(name) is None:
            continue
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
    """Подпись сервера: оригинальное имя из источника или fallback."""
    if config.KEEP_SOURCE_NAMES and "#" in uri:
        original = urllib.parse.unquote(uri.split("#", 1)[1]).strip()
        if original:
            return original
    flag = extract_country_flag(uri) or "🌐"
    if flag == RUSSIA_FLAG:
        flag = "🌐"
    return f"{flag} {config.BOT_NAME} · Сервер #{index}"


def brand_config(uri: str, label: str) -> str:
    base = uri.split("#", 1)[0]
    return f"{base}#{urllib.parse.quote(label, safe='')}"


def unique_source_labels(uris: list[str]) -> list[str]:
    """Одно имя — один конфиг. Без ·2/·3 дублей."""
    seen: set[str] = set()
    result: list[str] = []
    mobile_idx = 0
    for idx, uri in enumerate(uris, start=1):
        original = urllib.parse.unquote(uri.split("#", 1)[1]).strip() if "#" in uri else ""
        if original and is_bypass_profile_name(original):
            mobile_idx += 1
            label = mobile_internet_label(mobile_idx)
        else:
            label = restyle_server_name(original) if original else None
            if not label:
                label = build_server_label("vpn", uri, idx)
        key = label.lower()
        if key in seen:
            continue
        if should_skip_profile(label) or should_skip_profile(original):
            continue
        seen.add(key)
        result.append(brand_config(uri, label))
    return result
