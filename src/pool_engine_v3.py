import asyncio
import hashlib
import logging
import random
import time
import urllib.parse
from dataclasses import dataclass, field

import aiohttp
from aiohttp import ClientResponseError

from bot_notify import notify_admins_source_alert
from config import config, is_classic_sub_url, is_private_source, requires_happ_hwid
from parser import (
    brand_bypass_uris,
    brand_main_uris,
    brand_config,
    build_server_label,
    dedupe_uris,
    extract_happ_json_profiles,
    extract_host_port,
    filter_bypass_uris,
    get_sni,
    is_bypass_profile_name,
    is_placeholder_config,
    is_ru_whitelist_sni,
    is_whitelist_host_ip,
    lte_speed_score,
    parse_subscription_lines,
    rank_configs_for_speed,
    rank_lte_configs,
    rank_universal_configs,
    restyle_server_name,
    select_extra_bypass_profiles,
    select_extra_bypass_uris,
    set_whitelist_cidrs,
    should_skip_profile,
    split_uris_by_bypass,
    speed_score,
    tag_extra_bypass_profiles,
    uri_identity,
    unique_source_labels,
)
from xray_builder import build_happ_profiles, uri_to_outbound

logger = logging.getLogger(__name__)

POOL_ENGINE_VERSION = 4
POOL_ENGINE_MODULE = "pool_engine_v3"

@dataclass
class PoolState:
    wifi_uris: list[str] = field(default_factory=list)
    lte_uris: list[str] = field(default_factory=list)
    wifi_count: int = 0
    lte_count: int = 0
    wifi_source_counts: dict[str, int] = field(default_factory=dict)
    lte_source_counts: dict[str, int] = field(default_factory=dict)
    # Legacy aliases for admin/health compatibility
    configs: list[str] = field(default_factory=list)
    source_total: int = 0
    primary_count: int = 0
    fill_count: int = 0
    source_counts: dict[str, int] = field(default_factory=dict)
    subscription_count: int = 0
    last_refresh_at: float = 0.0
    last_refresh_duration: float = 0.0
    last_error: str | None = None
    is_refreshing: bool = False
    content_fingerprint: str = ""
    source_status: str = "unknown"
    last_fetch_status: int | None = None
    consecutive_fetch_failures: int = 0
    source_real_count: int = 0


_pool = PoolState()
_refresh_lock = asyncio.Lock()
_session: aiohttp.ClientSession | None = None
_upstream_session: aiohttp.ClientSession | None = None
_cached_wifi_lines: list[str] = []
_cached_lte_lines: list[str] = []
_cached_json_profiles: list[dict] = []
_cidr_last_fetch_at: float = 0.0


def get_pool_state() -> PoolState:
    return _pool


def get_wifi_lines() -> list[str]:
    return _cached_wifi_lines


def get_lte_uris() -> list[str]:
    return list(_pool.lte_uris)


def get_lte_lines() -> list[str]:
    return _cached_lte_lines


def get_happ_json_profiles() -> list[dict]:
    return _cached_json_profiles


def get_subscription_lines() -> list[str]:
    """Legacy: combined list (prefer get_wifi_lines / get_lte_lines)."""
    return _cached_wifi_lines + _cached_lte_lines


def _build_lines(uris: list[str], kind: str) -> list[str]:
    if config.KEEP_SOURCE_NAMES:
        return unique_source_labels(uris)
    lines: list[str] = []
    for idx, uri in enumerate(uris, start=1):
        label = build_server_label(kind, uri, idx)
        lines.append(brand_config(uri, label))
    return lines


def _is_private_source_url(url: str) -> bool:
    return is_private_source(url)


def _is_remnawave_url(url: str) -> bool:
    host = url.lower()
    return any(token in host for token in ("lidervpn.com", "remnawave", "remna.st", "pnl."))


def _is_happ_hwid_url(url: str) -> bool:
    return requires_happ_hwid(url)


def _is_classic_sub_url(url: str) -> bool:
    return is_classic_sub_url(url)


def _content_fingerprint(texts: list[str], wifi: list[str], lte: list[str]) -> str:
    payload = "\n".join(texts) + f"|w{len(wifi)}|l{len(lte)}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{len(wifi)}:{len(lte)}:{digest[:16]}"


def _config_identity(uri: str) -> str:
    base = uri.split("#", 1)[0].strip().lower()
    return base


def _source_label(url: str) -> str:
    return url.rstrip("/").split("/")[-1] or url


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        timeout = aiohttp.ClientTimeout(total=config.FETCH_TIMEOUT)
        _session = aiohttp.ClientSession(timeout=timeout)
    return _session


async def _get_upstream_session() -> aiohttp.ClientSession:
    """Сессия для VPN_SOURCE_URL — через UPSTREAM_PROXY_URL (HTTP/SOCKS5), если задан."""
    global _upstream_session
    if _upstream_session is None or _upstream_session.closed:
        timeout = aiohttp.ClientTimeout(total=config.FETCH_TIMEOUT)
        jar = aiohttp.CookieJar(unsafe=True)
        proxy_url = (config.UPSTREAM_PROXY_URL or "").strip()
        if proxy_url:
            from aiohttp_socks import ProxyConnector

            connector = ProxyConnector.from_url(proxy_url)
            _upstream_session = aiohttp.ClientSession(
                timeout=timeout,
                cookie_jar=jar,
                connector=connector,
            )
        else:
            _upstream_session = aiohttp.ClientSession(timeout=timeout, cookie_jar=jar)
    return _upstream_session


def _fetch_headers_for_url(url: str) -> dict[str, str]:
    """Заголовки под тип панели. HWID-панели — только Happ/Android, без Chrome UA."""
    if _is_happ_hwid_url(url) or _is_private_source_url(url):
        headers = dict(config.fetch_hwid_headers())
        if _is_classic_sub_url(url):
            # ecobuy/shuka ломаются на Happ UA
            headers["User-Agent"] = "v2rayN/6.45"
            headers.pop("x-hwid", None)
            headers.pop("x-device-os", None)
            headers.pop("x-ver-os", None)
            headers.pop("x-device-model", None)
            headers.pop("x-device-locale", None)
        return headers

    configured = (config.SUB_FETCH_UA or "").strip()
    return {
        "User-Agent": configured or "v2rayN/6.45",
        "Accept": "*/*",
        "Accept-Encoding": "gzip",
    }


async def close_session() -> None:
    global _session, _upstream_session
    for session in (_session, _upstream_session):
        if session and not session.closed:
            await session.close()
    _session = None
    _upstream_session = None


async def _fetch_cidr_list() -> None:
    global _cidr_last_fetch_at
    url = config.WHITELIST_CIDR_URL.strip()
    if not url:
        return
    now = time.time()
    if _cidr_last_fetch_at and now - _cidr_last_fetch_at < config.CIDR_REFRESH_INTERVAL:
        return
    session = await _get_session()
    try:
        async with session.get(url, ssl=False) as resp:
            resp.raise_for_status()
            text = await resp.text()
        set_whitelist_cidrs(text.splitlines())
        _cidr_last_fetch_at = now
        logger.info("Loaded whitelist CIDR list from %s", url.rsplit("/", 1)[-1])
    except Exception as exc:
        logger.warning("Whitelist CIDR fetch failed: %s", exc)


async def _rank_by_tcp_latency(uris: list[str], concurrency: int = 40) -> list[str]:
    """Живые узлы, отсортированные по TCP RTT (как ping в Happ)."""
    if not config.LTE_TCP_CHECK or not uris:
        return uris
    sem = asyncio.Semaphore(concurrency)

    async def probe(uri: str) -> tuple[str, float | None]:
        hp = extract_host_port(uri)
        if not hp:
            return uri, None
        async with sem:
            started = time.perf_counter()
            try:
                _reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(hp[0], hp[1]),
                    timeout=4.0,
                )
                writer.close()
                await writer.wait_closed()
                return uri, (time.perf_counter() - started) * 1000
            except Exception:
                return uri, None

    results = await asyncio.gather(*[probe(u) for u in uris])
    alive = [(ms, uri) for uri, ms in results if ms is not None]
    alive.sort(key=lambda item: item[0])
    ranked = [uri for _, uri in alive]
    if ranked:
        logger.info(
            "LTE TCP rank: %s alive, best=%.0fms, worst=%.0fms",
            len(ranked),
            alive[0][0],
            alive[-1][0],
        )
        return ranked
    logger.warning("LTE TCP rank: none alive, keeping top %s by score", min(10, len(uris)))
    return uris[:10]


def _lte_profiles_from_pool(uris: list[str]) -> list[str]:
    """Whitelist IP + RU SNI + :443 для выдачи на LTE (Билайн/МТС/Мегафон)."""
    strict: list[str] = []
    for uri in uris:
        hp = extract_host_port(uri)
        sni = get_sni(uri)
        if not hp or not sni:
            continue
        port = hp[1]
        if port != 443 and not (
            port in (5443, 8443) and "flow=xtls-rprx-vision" in uri.lower()
        ):
            continue
        if not is_whitelist_host_ip(hp[0]):
            continue
        if not is_ru_whitelist_sni(sni):
            continue
        strict.append(uri)

    strict.sort(key=lte_speed_score, reverse=True)
    # Один конфиг на IP — меньше дубликатов
    deduped: list[str] = []
    seen_ip: set[str] = set()
    for uri in strict:
        hp = extract_host_port(uri)
        if not hp:
            continue
        ip = hp[0].lower()
        if ip in seen_ip:
            continue
        seen_ip.add(ip)
        deduped.append(uri)

    if len(deduped) >= 3:
        logger.info("LTE strict pool: %s configs (IP+SNI+443, %s IPs)", len(deduped), len(seen_ip))
        return deduped

    if config.LTE_REQUIRE_WHITELIST_IP:
        wl = [
            u
            for u in uris
            if (hp := extract_host_port(u)) and is_whitelist_host_ip(hp[0])
        ]
        if len(wl) >= 3:
            logger.warning(
                "LTE strict pool small (%s), fallback whitelist IP only (%s)",
                len(strict),
                len(wl),
            )
            return wl

    logger.warning("LTE strict pool tiny (%s), using ranked pool %s", len(strict), len(uris))
    return uris[: max(3, min(15, len(uris)))]


def _sort_lte_whitelist_first(uris: list[str]) -> list[str]:
    wl: list[str] = []
    rest: list[str] = []
    for uri in uris:
        hp = extract_host_port(uri)
        if hp and is_whitelist_host_ip(hp[0]):
            wl.append(uri)
        else:
            rest.append(uri)
    wl.sort(key=lte_speed_score, reverse=True)
    rest.sort(key=lte_speed_score, reverse=True)
    return wl + rest


def _real_uris(uris: list[str]) -> list[str]:
    return [uri for uri in uris if not is_placeholder_config(uri)]


def _hwid_blocked(headers: aiohttp.typedefs.LooseHeaders) -> bool:
    keys = (
        "x-hwid-limit",
        "x-hwid-max-devices-reached",
        "x-hwid-not-supported",
    )
    for key in keys:
        val = headers.get(key) or headers.get(key.title()) or headers.get(key.upper())
        if str(val or "").lower() in ("1", "true", "yes"):
            return True
    return False


async def _fetch_url(
    url: str,
    *,
    role: str = "",
) -> tuple[str, str | None, list[str], str | None, int | None]:
    label = f"{role}:{_source_label(url)}" if role else _source_label(url)
    # ecobuy/shuka — без прокси (часто блокируется или ломается через DC-proxy)
    use_direct = role == "bypass" and _is_classic_sub_url(url)
    session = await _get_session() if use_direct else await _get_upstream_session()
    headers = _fetch_headers_for_url(url)
    status: int | None = None
    try:
        async with session.get(url, ssl=False, headers=headers) as resp:
            status = resp.status
            text = await resp.text()
            if _hwid_blocked(resp.headers):
                logger.warning("Source %s HWID blocked (headers)", label)
                return label, None, [], "hwid_limit", status
            hwid_limit = resp.headers.get("X-Hwid-Limit") or resp.headers.get("x-hwid-limit")
            hwid_nosup = resp.headers.get("X-Hwid-Not-Supported") or resp.headers.get(
                "x-hwid-not-supported"
            )
            if hwid_limit or hwid_nosup:
                logger.warning(
                    "Source %s HWID flags: limit=%s not_supported=%s",
                    label,
                    hwid_limit,
                    hwid_nosup,
                )
            resp.raise_for_status()
    except ClientResponseError as exc:
        detail = f"http_{exc.status}"
        logger.warning("Fetch failed %s: %s", label, exc)
        return label, None, [], detail, exc.status
    except Exception as exc:
        logger.warning("Fetch failed %s: %s", label, exc)
        return label, None, [], "network_error", status

    parsed = parse_subscription_lines(text)
    uris = _real_uris([uri for uri in parsed if extract_host_port(uri)])
    logger.info(
        "Loaded %s configs from %s (%s real, status=%s)",
        len(parsed),
        label,
        len(uris),
        status,
    )
    return label, text, uris, None, status


def _prepare_pool(
    ranked_by_source: list[tuple[str, list[str]]],
    limit: int,
) -> tuple[list[str], dict[str, int]]:
    """WIFI pool: ranked, host-deduped, convertible, capped."""
    result: list[str] = []
    seen: set[str] = set()
    owner: dict[str, str] = {}

    for label, uris in ranked_by_source:
        for uri in uris:
            if len(result) >= limit:
                break
            if not uri_to_outbound(uri, "probe"):
                continue
            key = _config_identity(uri)
            if key in seen:
                continue
            seen.add(key)
            result.append(uri)
            owner[key] = label
        if len(result) >= limit:
            break

    result.sort(key=speed_score, reverse=True)

    counts: dict[str, int] = {label: 0 for label, _ in ranked_by_source}
    for uri in result:
        label = owner.get(_config_identity(uri))
        if label:
            counts[label] += 1
    return result, counts


def _prepare_lte_pool(
    raw_by_source: list[tuple[str, list[str]]],
    limit: int,
    min_score: int,
) -> tuple[list[str], dict[str, int]]:
    """
    LTE: source priority, rank_lte_configs per source (host:port dedup + quality filter),
    cap at limit. Best nodes first for balancer fallback.
    """
    result: list[str] = []
    seen: set[str] = set()
    counts: dict[str, int] = {label: 0 for label, _ in raw_by_source}

    for label, uris in raw_by_source:
        ranked = rank_lte_configs(uris, min_score=min_score)
        for uri in ranked:
            if len(result) >= limit:
                break
            if not uri_to_outbound(uri, "probe"):
                continue
            key = _config_identity(uri)
            if key in seen:
                continue
            seen.add(key)
            result.append(uri)
            counts[label] += 1
        if len(result) >= limit:
            break

    result.sort(key=lte_speed_score, reverse=True)
    return result, counts


async def refresh_pool(force: bool = False) -> PoolState:
    global _cached_wifi_lines, _cached_lte_lines, _cached_json_profiles

    if _pool.is_refreshing and not force:
        return _pool

    if (
        not force
        and _pool.consecutive_fetch_failures > 0
        and _cached_json_profiles
        and _pool.last_refresh_at
    ):
        backoff = min(
            86400,
            config.SOURCE_FETCH_BACKOFF_SEC * _pool.consecutive_fetch_failures,
        )
        if time.time() - _pool.last_refresh_at < backoff:
            logger.info(
                "Skipping upstream fetch (backoff %ss, failures=%s)",
                int(backoff),
                _pool.consecutive_fetch_failures,
            )
            return _pool

    async with _refresh_lock:
        if _pool.is_refreshing and not force:
            return _pool

        _pool.is_refreshing = True
        started = time.perf_counter()
        fetch_plan = config.upstream_fetch_plan()

        bypass_label = config.bypass_source_label()
        logger.info(
            "pool_engine_v3: main=%s bypass=%s (happ_hwid=%s, proxy=%s)",
            config.source_label(),
            bypass_label or "—",
            requires_happ_hwid(config.resolved_source_url() or ""),
            config.upstream_proxy_label() if config.upstream_proxy_configured() else "direct",
        )

        try:
            await _fetch_cidr_list()
            results = await asyncio.gather(
                *[_fetch_url(url, role=role) for role, url in fetch_plan]
            )
            by_label: dict[str, tuple[str | None, list[str], str | None, int | None]] = {}
            fetch_errors: list[str] = []
            last_status: int | None = None
            main_result: tuple[str | None, list[str], str | None, int | None] | None = None
            bypass_result: tuple[str | None, list[str], str | None, int | None] | None = None

            for (role, url), (label, text, uris, err, status) in zip(fetch_plan, results):
                by_label[label] = (text, uris, err, status)
                if role == "main":
                    main_result = (text, uris, err, status)
                    if err:
                        fetch_errors.append(err)
                elif role == "bypass":
                    bypass_result = (text, uris, err, status)
                    if text is None:
                        logger.warning(
                            "Bypass source %s unavailable: %s",
                            config.bypass_source_label() or label,
                            err or "unknown",
                        )
                    else:
                        extra_profiles = select_extra_bypass_profiles(text or "")
                        extra_uris = select_extra_bypass_uris(uris or [])
                        logger.info(
                            "Bypass source %s: %s raw uris, %s json profiles, %s uris selected",
                            config.bypass_source_label() or label,
                            len(uris or []),
                            len(extra_profiles),
                            len(extra_uris),
                        )
                if status is not None and role == "main":
                    last_status = status

            main_text, main_uris_raw, main_err, _main_status = main_result or (
                None,
                [],
                "missing_main",
                None,
            )

            if main_text is None:
                _pool.consecutive_fetch_failures += 1
                _pool.last_fetch_status = last_status
                err_hint = main_err or (fetch_errors[0] if fetch_errors else "unknown")
                if err_hint == "http_404":
                    _pool.last_error = "VPN key revoked or not found (HTTP 404)"
                    _pool.source_status = "degraded" if _cached_json_profiles else "failed"
                    await notify_admins_source_alert(
                        "http_404",
                        "Ключ <b>удалён или сброшен</b> (HTTP 404).\n"
                        "Пользователи получают закэшированные конфиги, пока кэш не протухнет.",
                    )
                elif err_hint == "hwid_limit":
                    _pool.last_error = "HWID device limit reached on upstream panel"
                    _pool.source_status = "degraded" if _cached_json_profiles else "failed"
                    await notify_admins_source_alert(
                        "hwid_limit",
                        "Панель подписки вернула <b>лимит HWID</b>.\n"
                        "Отвяжите лишние устройства в панели или смените ключ.",
                    )
                elif err_hint == "http_502":
                    _pool.last_error = "Upstream panel blocked or down (HTTP 502)"
                    _pool.source_status = "degraded" if _cached_json_profiles else "failed"
                    await notify_admins_source_alert(
                        "http_502",
                        "Панель вернула <b>502 Bad Gateway</b> — часто это <b>бан аккаунта</b> "
                        "за реселл/серверные запросы.\n"
                        "Нужен <b>новый аккаунт</b> и ключ; включите <code>UPSTREAM_PROXY_URL</code> "
                        "и увеличьте <code>POOL_REFRESH_INTERVAL</code>.",
                    )
                else:
                    _pool.last_error = f"Failed to fetch source ({err_hint})"
                    _pool.source_status = "degraded" if _cached_json_profiles else "failed"
                    await notify_admins_source_alert(
                        f"fetch_{err_hint}",
                        f"Не удалось загрузить конфиги: <code>{err_hint}</code>.",
                    )
                return _pool

            bypass_text = ""
            bypass_uris_raw: list[str] = []
            if bypass_result and bypass_result[0]:
                bypass_text, bypass_uris_raw, _, _ = bypass_result

            wifi_raw, bypass_from_main = split_uris_by_bypass(main_uris_raw)
            bypass_from_main = dedupe_uris(bypass_from_main)
            extra_bypass_profiles = tag_extra_bypass_profiles(
                select_extra_bypass_profiles(bypass_text)
            )
            extra_bypass = select_extra_bypass_uris(bypass_uris_raw)
            extra_bypass = dedupe_uris(extra_bypass)
            wifi_uris = dedupe_uris(wifi_raw)

            branded_wifi = brand_main_uris(wifi_uris)
            branded_main_bypass = brand_bypass_uris(bypass_from_main, start_index=1, extra=False)
            extra_bypass_count = len(extra_bypass_profiles) or len(extra_bypass)
            branded_extra_bypass = (
                []
                if extra_bypass_profiles
                else brand_bypass_uris(
                    extra_bypass,
                    start_index=len(bypass_from_main) + 1,
                    extra=True,
                )
            )
            branded_bypass = branded_main_bypass + branded_extra_bypass
            merged_bypass = bypass_from_main + extra_bypass

            branded = branded_wifi + branded_bypass

            texts = [main_text or ""]
            if bypass_text:
                texts.append(bypass_text)

            total_raw = len(main_uris_raw) + len(bypass_uris_raw)
            source_counts: dict[str, int] = {
                config.source_label(): len(main_uris_raw),
            }
            if bypass_label:
                source_counts[bypass_label] = extra_bypass_count

            _pool.source_real_count = (
                len(wifi_uris) + len(bypass_from_main) + extra_bypass_count
            )
            _pool.last_fetch_status = last_status

            if _pool.source_real_count < config.SOURCE_MIN_REAL_CONFIGS:
                _pool.consecutive_fetch_failures += 1
                _pool.last_error = (
                    f"Source returned only {_pool.source_real_count} real configs "
                    f"(min {config.SOURCE_MIN_REAL_CONFIGS})"
                )
                _pool.source_status = "degraded" if _cached_json_profiles else "failed"
                if _cached_json_profiles:
                    logger.warning(
                        "Keeping %s cached profiles — upstream returned %s real configs",
                        len(_cached_json_profiles),
                        _pool.source_real_count,
                    )
                    await notify_admins_source_alert(
                        "empty_real_cached",
                        "Источник отдал заглушки или мало серверов — "
                        f"работаем на кэше ({len(_cached_json_profiles)} профилей).",
                    )
                else:
                    await notify_admins_source_alert(
                        "empty_real",
                        "Источник отдал только заглушки HWID — рабочих серверов нет.",
                    )
                return _pool

            limit = config.SUBSCRIPTION_CONFIG_LIMIT
            main_url = config.resolved_source_url()
            private_only = bool(main_url) and _is_private_source_url(main_url)

            source_json_profiles: list[dict] = []
            seen_json: set[str] = set()
            for profile in extract_happ_json_profiles(main_text or ""):
                key = str(profile.get("remarks") or "").lower()
                if key in seen_json:
                    continue
                seen_json.add(key)
                source_json_profiles.append(profile)
                if len(source_json_profiles) >= limit:
                    break

            if private_only:
                json_profiles = build_happ_profiles(
                    branded_wifi,
                    bypass_uris=branded_main_bypass,
                    extra_bypass_uris=branded_extra_bypass,
                    extra_bypass_profiles=extra_bypass_profiles,
                    existing=source_json_profiles or None,
                    limit=limit,
                )
            else:
                ranked_wifi = rank_universal_configs(wifi_uris, limit=limit)
                branded_wifi = brand_main_uris(ranked_wifi)
                branded_bypass = branded_main_bypass + branded_extra_bypass
                branded = branded_wifi + branded_bypass
                json_profiles = build_happ_profiles(
                    branded_wifi,
                    bypass_uris=branded_main_bypass,
                    extra_bypass_uris=branded_extra_bypass,
                    extra_bypass_profiles=extra_bypass_profiles,
                    existing=source_json_profiles or None,
                    limit=limit,
                )

            picked = merged_bypass + wifi_uris

            fingerprint = _content_fingerprint(texts, picked, json_profiles)

            if (
                fingerprint == _pool.content_fingerprint
                and _cached_json_profiles
                and not force
            ):
                logger.info(
                    "Source unchanged (%s in key from %s raw unique-ranked)",
                    len(_cached_json_profiles),
                    total_raw,
                )
                _pool.last_refresh_at = time.time()
                _pool.last_error = None
                _pool.source_status = "ok"
                _pool.consecutive_fetch_failures = 0
                return _pool

            if not json_profiles and _cached_json_profiles:
                _pool.last_error = "Rebuild produced empty profile list — keeping cache"
                _pool.source_status = "degraded"
                logger.warning(
                    "Rejecting empty rebuild, keeping %s cached profiles",
                    len(_cached_json_profiles),
                )
                return _pool

            wifi_pool = list(wifi_uris)
            lte_pool = list(merged_bypass) or list(wifi_uris)
            _cached_wifi_lines = branded_wifi
            _cached_lte_lines = branded_bypass or branded_wifi
            _cached_json_profiles = json_profiles

            _pool.wifi_uris = wifi_pool
            _pool.lte_uris = lte_pool
            _pool.wifi_count = len(wifi_pool)
            _pool.lte_count = len(json_profiles)
            _pool.wifi_source_counts = {config.source_label(): len(wifi_uris)}
            if bypass_label:
                _pool.lte_source_counts = {
                    config.source_label(): len(bypass_from_main),
                    bypass_label: extra_bypass_count,
                }
            else:
                _pool.lte_source_counts = source_counts
            _pool.configs = picked
            _pool.source_total = total_raw
            _pool.primary_count = len(json_profiles)
            _pool.fill_count = len(merged_bypass)
            _pool.source_counts = source_counts
            _pool.subscription_count = len(json_profiles)
            _pool.content_fingerprint = fingerprint
            _pool.last_refresh_at = time.time()
            _pool.last_refresh_duration = time.perf_counter() - started
            _pool.last_error = None
            _pool.source_status = "ok"
            _pool.consecutive_fetch_failures = 0

            logger.info(
                "Pool updated: %s json profiles (wifi=%s bypass=%s extra=%s, limit=%s) from %s raw (%s) in %.1fs",
                len(json_profiles),
                len(wifi_uris),
                len(bypass_from_main),
                extra_bypass_count,
                limit,
                total_raw,
                ", ".join(f"{k}={v}" for k, v in source_counts.items() if v),
                _pool.last_refresh_duration,
            )
            if not json_profiles:
                logger.warning(
                    "Subscription pool empty — check VPN_SOURCE_URL / HWID (key=%s)",
                    config.source_label(),
                )
            elif private_only and len(json_profiles) < min(3, limit):
                logger.warning(
                    "Private source returned only %s json profiles (raw=%s)",
                    len(json_profiles),
                    total_raw,
                )
            elif len(json_profiles) < limit and not private_only:
                logger.warning(
                    "Fewer than %s unique configs after rank: %s",
                    limit,
                    len(json_profiles),
                )
        except Exception as exc:
            _pool.last_error = str(exc)
            logger.exception("Pool refresh failed: %s", exc)
        finally:
            _pool.is_refreshing = False

        return _pool


async def start_refresh_loop() -> None:
    startup_delay = random.randint(30, max(30, config.POOL_STARTUP_DELAY_SEC))
    logger.info("First upstream fetch in %ss (anti-ban startup delay)", startup_delay)
    await asyncio.sleep(startup_delay)
    await refresh_pool(force=True)
    while True:
        jitter = random.randint(0, max(0, config.POOL_REFRESH_JITTER_SEC))
        await asyncio.sleep(config.POOL_REFRESH_INTERVAL + jitter)
        try:
            await refresh_pool(force=False)
        except Exception as exc:
            logger.error("Background refresh error: %s", exc)
