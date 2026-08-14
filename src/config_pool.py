import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field

import aiohttp

from config import config
from parser import (
    brand_config,
    build_server_label,
    extract_host_port,
    get_sni,
    is_ru_whitelist_sni,
    is_whitelist_host_ip,
    lte_speed_score,
    parse_subscription_lines,
    rank_configs_for_speed,
    rank_lte_configs,
    rank_universal_configs,
    set_whitelist_cidrs,
    speed_score,
)
from xray_builder import uri_to_outbound

logger = logging.getLogger(__name__)

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


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


_pool = PoolState()
_refresh_lock = asyncio.Lock()
_session: aiohttp.ClientSession | None = None
_cached_wifi_lines: list[str] = []
_cached_lte_lines: list[str] = []


def get_pool_state() -> PoolState:
    return _pool


def get_wifi_lines() -> list[str]:
    return _cached_wifi_lines


def get_lte_uris() -> list[str]:
    return list(_pool.lte_uris)


def get_lte_lines() -> list[str]:
    return _cached_lte_lines


def get_subscription_lines() -> list[str]:
    """Legacy: combined list (prefer get_wifi_lines / get_lte_lines)."""
    return _cached_wifi_lines + _cached_lte_lines


def _build_lines(uris: list[str], kind: str) -> list[str]:
    lines: list[str] = []
    for idx, uri in enumerate(uris, start=1):
        label = build_server_label(kind, uri, idx)
        lines.append(brand_config(uri, label))
    return lines


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


def _fetch_headers_for_url(url: str) -> dict[str, str]:
    """Remnawave / LiderVPN требуют x-hwid, иначе отдают заглушку."""
    headers = {"User-Agent": CHROME_UA, "Accept": "*/*"}
    host = url.lower()
    is_remnawave = any(
        token in host for token in ("lidervpn.com", "remnawave", "remna.st", "pnl.")
    )
    if is_remnawave:
        headers["User-Agent"] = config.SUB_FETCH_UA or "Happ/3.5.0"
        if config.SUB_HWID:
            headers["x-hwid"] = config.SUB_HWID
            headers["x-device-os"] = config.SUB_DEVICE_OS
            headers["x-ver-os"] = config.SUB_DEVICE_OS_VER
            headers["x-device-model"] = config.SUB_DEVICE_MODEL
    return headers


async def close_session() -> None:
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None


async def _fetch_cidr_list() -> None:
    url = config.WHITELIST_CIDR_URL.strip()
    if not url:
        return
    session = await _get_session()
    try:
        async with session.get(url, ssl=False) as resp:
            resp.raise_for_status()
            text = await resp.text()
        set_whitelist_cidrs(text.splitlines())
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


async def _fetch_url(url: str) -> tuple[str, str | None, list[str]]:
    label = _source_label(url)
    session = await _get_session()
    headers = _fetch_headers_for_url(url)
    try:
        async with session.get(url, ssl=False, headers=headers) as resp:
            resp.raise_for_status()
            text = await resp.text()
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
    except Exception as exc:
        logger.warning("Fetch failed %s: %s", label, exc)
        return label, None, []

    parsed = parse_subscription_lines(text)
    uris = [uri for uri in parsed if extract_host_port(uri)]
    logger.info(
        "Loaded %s configs from %s (%s valid)",
        len(parsed),
        label,
        len(uris),
    )
    return label, text, uris


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
    if _pool.is_refreshing and not force:
        return _pool

    async with _refresh_lock:
        if _pool.is_refreshing and not force:
            return _pool

        _pool.is_refreshing = True
        started = time.perf_counter()
        wifi_urls = config.wifi_source_urls()
        lte_urls = config.lte_source_urls()
        all_urls = list(dict.fromkeys(wifi_urls + lte_urls))

        logger.info(
            "Checking sources WIFI=%s LTE=%s",
            ", ".join(_source_label(u) for u in wifi_urls) or "none",
            ", ".join(_source_label(u) for u in lte_urls) or "none",
        )

        try:
            await _fetch_cidr_list()
            results = await asyncio.gather(*[_fetch_url(url) for url in all_urls])
            by_label: dict[str, tuple[str | None, list[str]]] = {}
            for label, text, uris in results:
                by_label[label] = (text, uris)

            if all(text is None for text, _ in by_label.values()):
                _pool.last_error = "Failed to fetch all config sources"
                return _pool

            texts: list[str] = []
            all_uris: list[str] = []
            total_raw = 0
            source_counts: dict[str, int] = {}

            for url in all_urls:
                label = _source_label(url)
                text, uris = by_label.get(label, (None, []))
                texts.append(text or "")
                raw = list(uris or [])
                all_uris.extend(raw)
                source_counts[label] = len(raw)
                total_raw += len(raw)

            limit = config.SUBSCRIPTION_CONFIG_LIMIT
            picked = rank_universal_configs(all_uris, limit=limit)

            fingerprint = _content_fingerprint(texts, picked, [])
            global _cached_wifi_lines, _cached_lte_lines

            if (
                fingerprint == _pool.content_fingerprint
                and _cached_lte_lines
                and not force
            ):
                logger.info(
                    "Source unchanged (%s in key from %s raw unique-ranked)",
                    len(picked),
                    total_raw,
                )
                _pool.last_refresh_at = time.time()
                _pool.last_error = None
                return _pool

            branded = _build_lines(picked, "vpn")
            _cached_wifi_lines = []
            _cached_lte_lines = branded

            _pool.wifi_uris = []
            _pool.lte_uris = picked
            _pool.wifi_count = 0
            _pool.lte_count = len(picked)
            _pool.wifi_source_counts = {}
            _pool.lte_source_counts = source_counts
            _pool.configs = picked
            _pool.source_total = total_raw
            _pool.primary_count = len(picked)
            _pool.fill_count = 0
            _pool.source_counts = source_counts
            _pool.subscription_count = len(picked)
            _pool.content_fingerprint = fingerprint
            _pool.last_refresh_at = time.time()
            _pool.last_refresh_duration = time.perf_counter() - started
            _pool.last_error = None

            logger.info(
                "Pool updated: %s in key (limit=%s) from %s raw (%s) in %.1fs",
                len(picked),
                limit,
                total_raw,
                ", ".join(f"{k}={v}" for k, v in source_counts.items() if v),
                _pool.last_refresh_duration,
            )
            if len(picked) < limit:
                logger.warning(
                    "Fewer than %s unique configs after rank: %s",
                    limit,
                    len(picked),
                )
        except Exception as exc:
            _pool.last_error = str(exc)
            logger.exception("Pool refresh failed: %s", exc)
        finally:
            _pool.is_refreshing = False

        return _pool


async def start_refresh_loop() -> None:
    await refresh_pool(force=True)
    while True:
        await asyncio.sleep(config.POOL_REFRESH_INTERVAL)
        try:
            await refresh_pool(force=False)
        except Exception as exc:
            logger.error("Background refresh error: %s", exc)
