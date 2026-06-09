import asyncio
import logging
import ssl
import time
from dataclasses import dataclass, field

import aiohttp

from config import config
from parser import (
    brand_config,
    bypass_whitelist_score,
    extract_host_port,
    get_security,
    get_sni,
    get_transport,
    parse_bypass_subscription,
    parse_vpn_configs,
    parse_whitelist_configs,
)

logger = logging.getLogger(__name__)


@dataclass
class WorkingConfig:
    uri: str
    host: str
    port: int
    latency_ms: int
    category: str
    source: str = ""
    sni: str = ""


@dataclass
class PoolState:
    configs: list[WorkingConfig] = field(default_factory=list)
    last_refresh_at: float = 0.0
    last_refresh_duration: float = 0.0
    candidates_checked: int = 0
    candidates_alive: int = 0
    last_error: str | None = None
    is_refreshing: bool = False
    source_info: str = ""
    last_verify_at: float = 0.0
    last_verify_alive: int = 0


_pool = PoolState()
_refresh_lock = asyncio.Lock()
_verify_lock = asyncio.Lock()
_verify_cache: dict[str, tuple[float, int | None]] = {}
_session: aiohttp.ClientSession | None = None

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def get_pool_state() -> PoolState:
    return _pool


def _config_to_line(item: WorkingConfig, regular_idx: int, whitelist_idx: int) -> str:
    if item.category == "whitelist":
        sni_short = (item.sni or "BS").split(".")[0]
        transport = get_transport(item.uri)
        if transport in ("grpc", "ws"):
            label = f"{config.BOT_NAME} | БС {sni_short} {transport} #{whitelist_idx}"
        else:
            label = f"{config.BOT_NAME} | БС {sni_short} #{whitelist_idx}"
    else:
        label = f"{config.BOT_NAME} | VPN #{regular_idx}"
    return brand_config(item.uri, label)


async def get_working_subscription_lines() -> list[str]:
    verified = await verify_pool_for_subscription()
    lines: list[str] = []
    regular_idx = 0
    whitelist_idx = 0

    for item in verified:
        if item.category == "whitelist":
            whitelist_idx += 1
            lines.append(_config_to_line(item, regular_idx, whitelist_idx))
        else:
            regular_idx += 1
            lines.append(_config_to_line(item, regular_idx, whitelist_idx))
    return lines


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        timeout = aiohttp.ClientTimeout(total=config.FETCH_TIMEOUT)
        _session = aiohttp.ClientSession(
            timeout=timeout,
            headers={"User-Agent": CHROME_UA},
        )
    return _session


async def close_session() -> None:
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None


async def _fetch_text(url: str) -> str | None:
    session = await _get_session()
    try:
        async with session.get(url, ssl=False) as resp:
            resp.raise_for_status()
            return await resp.text()
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None


async def _fetch_regular_file(filename: str) -> list[str]:
    url = f"{config.CONFIG_RAW_BASE}/{filename}"
    text = await _fetch_text(url)
    if not text:
        return []
    configs = parse_vpn_configs(text)
    logger.info("Regular: %s configs from %s", len(configs), filename)
    return configs


async def _fetch_whitelist_file(filename: str) -> list[str]:
    url = f"{config.CONFIG_RAW_BASE}/{filename}"
    text = await _fetch_text(url)
    if not text:
        return []
    configs = parse_whitelist_configs(text)
    logger.info("Whitelist fallback: %s configs from %s", len(configs), filename)
    return configs


async def _fetch_bypass_subscription() -> list[str]:
    text = await _fetch_text(config.BYPASS_SOURCE_URL)
    if not text:
        return []
    configs = parse_bypass_subscription(text)
    logger.info("Bypass subscription: %s whitelist candidates", len(configs))
    return configs


def _dedupe_by_uri(configs: list[str]) -> list[str]:
    seen_uri: set[str] = set()
    unique: list[str] = []
    for uri in configs:
        if uri in seen_uri:
            continue
        seen_uri.add(uri)
        unique.append(uri)
    return unique


def _dedupe_regular(configs: list[str]) -> list[str]:
    """Обычный VPN: один сервер (host:port) — один конфиг."""
    seen_uri: set[str] = set()
    seen_hostport: set[str] = set()
    unique: list[str] = []

    for uri in configs:
        if uri in seen_uri:
            continue
        seen_uri.add(uri)

        hostport = extract_host_port(uri)
        if hostport:
            key = f"{hostport[0].lower()}:{hostport[1]}"
            if key in seen_hostport:
                continue
            seen_hostport.add(key)

        unique.append(uri)
    return unique


def _matches_priority_sni(sni: str, priority_sni: str) -> bool:
    sni_l = sni.lower()
    psni_l = priority_sni.lower()
    return sni_l == psni_l or psni_l in sni_l


def _prioritize_whitelist_configs(configs: list[str]) -> list[str]:
    """Сначала проверенные SNI (urent, x5, vk, mwscdn), потом остальные."""
    buckets: dict[str, list[str]] = {sni: [] for sni in config.WHITELIST_PRIORITY_SNIS}
    rest: list[str] = []
    seen: set[str] = set()

    for uri in configs:
        if uri in seen:
            continue
        seen.add(uri)
        sni = get_sni(uri) or ""
        placed = False
        for priority_sni in config.WHITELIST_PRIORITY_SNIS:
            if _matches_priority_sni(sni, priority_sni):
                buckets[priority_sni].append(uri)
                placed = True
                break
        if not placed:
            rest.append(uri)

    ordered: list[str] = []
    for priority_sni in config.WHITELIST_PRIORITY_SNIS:
        bucket = sorted(buckets[priority_sni], key=bypass_whitelist_score, reverse=True)
        for uri in bucket[: config.WHITELIST_PER_PRIORITY_SNI]:
            ordered.append(uri)

    rest.sort(key=bypass_whitelist_score, reverse=True)
    for uri in rest:
        if uri not in ordered:
            ordered.append(uri)
    return ordered


def _whitelist_needs_tcp_only(uri: str) -> bool:
    if not config.WHITELIST_TCP_ONLY_CHECK:
        return False
    security = get_security(uri)
    transport = get_transport(uri)
    if security == "reality":
        return True
    if transport in ("grpc", "ws", "xhttp"):
        return True
    return False


def _uris_to_working(configs: list[str], category: str, source: str = "") -> list[WorkingConfig]:
    result: list[WorkingConfig] = []
    for uri in configs:
        hostport = extract_host_port(uri)
        if not hostport:
            continue
        host, port = hostport
        result.append(
            WorkingConfig(
                uri=uri,
                host=host,
                port=port,
                latency_ms=0,
                category=category,
                source=source,
                sni=get_sni(uri) or "",
            )
        )
    return result


async def _probe_latency(host: str, port: int, uri: str, *, tcp_only: bool = False) -> int | None:
    started = time.perf_counter()
    security = get_security(uri)
    sni = get_sni(uri) or host

    try:
        if tcp_only:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=config.HEALTH_CHECK_TIMEOUT,
            )
        elif security in ("tls", "reality") or uri.lower().startswith("trojan://"):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port, ssl=ctx, server_hostname=sni),
                timeout=config.HEALTH_CHECK_TIMEOUT,
            )
        else:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=config.HEALTH_CHECK_TIMEOUT,
            )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return max(int((time.perf_counter() - started) * 1000), 1)
    except Exception:
        return None


async def _health_check_batch(
    items: list[WorkingConfig],
    target: int,
    max_candidates: int | None = None,
) -> tuple[list[WorkingConfig], int]:
    if not items:
        return [], 0

    if config.SKIP_HEALTH_CHECK:
        return items[:target], len(items)

    limit = max_candidates or config.MAX_HEALTH_CHECK_CANDIDATES
    candidates = items[:limit]
    sem = asyncio.Semaphore(config.HEALTH_CHECK_CONCURRENCY)

    async def probe(item: WorkingConfig) -> WorkingConfig | None:
        async with sem:
            tcp_only = item.category == "whitelist" and _whitelist_needs_tcp_only(item.uri)
            latency = await _probe_latency(
                item.host, item.port, item.uri, tcp_only=tcp_only,
            )
            if latency is None:
                return None
            return WorkingConfig(
                uri=item.uri,
                host=item.host,
                port=item.port,
                latency_ms=latency,
                category=item.category,
                source=item.source,
                sni=item.sni,
            )

    results = await asyncio.gather(*(probe(item) for item in candidates))
    alive = [item for item in results if item is not None]
    alive.sort(key=lambda x: x.latency_ms)
    return alive[:target], len(candidates)


async def _collect_regular(limit: int) -> list[WorkingConfig]:
    raw: list[str] = []
    for filename in config.REGULAR_SOURCES:
        raw.extend(await _fetch_regular_file(filename))
        if len(_dedupe_regular(raw)) >= limit * 3:
            break

    unique = _dedupe_regular(raw)
    items = _uris_to_working(unique, "regular")
    alive, checked = await _health_check_batch(items, limit, limit * 3)
    logger.info("Regular health check: %s alive / %s checked", len(alive), checked)
    return alive


async def _collect_whitelist(limit: int) -> list[WorkingConfig]:
    raw: list[str] = []

    bypass_configs = await _fetch_bypass_subscription()
    raw.extend(bypass_configs)

    if len(_dedupe_by_uri(raw)) < limit:
        for filename in config.WHITELIST_SOURCES:
            raw.extend(await _fetch_whitelist_file(filename))
            if len(_dedupe_by_uri(raw)) >= limit * 4:
                break

    unique = _prioritize_whitelist_configs(_dedupe_by_uri(raw))

    logger.info(
        "Whitelist candidates: %s (top SNI: %s)",
        len(unique),
        get_sni(unique[0]) if unique else "none",
    )

    items = _uris_to_working(unique, "whitelist", source="bypass")
    alive, checked = await _health_check_batch(
        items,
        limit,
        config.MAX_HEALTH_CHECK_CANDIDATES,
    )
    logger.info("Whitelist health check: %s alive / %s checked", len(alive), checked)

    if len(alive) < limit // 2 and not config.SKIP_HEALTH_CHECK:
        logger.warning(
            "Only %s whitelist servers passed check (wanted %s)",
            len(alive),
            limit,
        )

    return alive


async def verify_pool_for_subscription() -> list[WorkingConfig]:
    if not _pool.configs:
        return []

    if not config.VERIFY_ON_SUBSCRIBE or config.SKIP_HEALTH_CHECK:
        return _pool.configs

    async with _verify_lock:
        now = time.time()
        sem = asyncio.Semaphore(config.HEALTH_CHECK_CONCURRENCY)

        async def verify_item(item: WorkingConfig) -> WorkingConfig | None:
            if item.category == "whitelist" and config.WHITELIST_SKIP_VERIFY_ON_SUBSCRIBE:
                return item

            cached = _verify_cache.get(item.uri)
            if cached and now - cached[0] < config.VERIFY_CACHE_TTL:
                if cached[1] is None:
                    return None
                return WorkingConfig(
                    uri=item.uri,
                    host=item.host,
                    port=item.port,
                    latency_ms=cached[1],
                    category=item.category,
                    source=item.source,
                    sni=item.sni,
                )

            async with sem:
                tcp_only = item.category == "whitelist" and _whitelist_needs_tcp_only(item.uri)
                latency = await _probe_latency(
                    item.host, item.port, item.uri, tcp_only=tcp_only,
                )

            _verify_cache[item.uri] = (now, latency)
            if latency is None:
                return None
            return WorkingConfig(
                uri=item.uri,
                host=item.host,
                port=item.port,
                latency_ms=latency,
                category=item.category,
                source=item.source,
                sni=item.sni,
            )

        results = await asyncio.gather(*(verify_item(item) for item in _pool.configs))
        alive = [item for item in results if item is not None]

        regular = sorted(
            [c for c in alive if c.category == "regular"],
            key=lambda x: x.latency_ms,
        )
        whitelist = sorted(
            [c for c in alive if c.category == "whitelist"],
            key=lambda x: x.latency_ms,
        )

        _pool.last_verify_at = now
        _pool.last_verify_alive = len(alive)

        logger.info(
            "Subscription verify: %s alive (%s VPN + %s БС) from %s total",
            len(alive),
            len(regular),
            len(whitelist),
            len(_pool.configs),
        )
        return regular + whitelist


async def refresh_pool(force: bool = False) -> PoolState:
    if _pool.is_refreshing and not force:
        return _pool

    async with _refresh_lock:
        if _pool.is_refreshing and not force:
            return _pool

        _pool.is_refreshing = True
        started = time.perf_counter()
        _verify_cache.clear()
        logger.info("Refreshing TsuloVPN config pool...")

        try:
            regular_alive, whitelist_alive = await asyncio.gather(
                _collect_regular(config.TARGET_REGULAR_COUNT),
                _collect_whitelist(config.TARGET_WHITELIST_COUNT),
            )

            combined = regular_alive[: config.TARGET_REGULAR_COUNT]
            combined.extend(whitelist_alive[: config.TARGET_WHITELIST_COUNT])

            _pool.configs = combined
            _pool.last_refresh_at = time.time()
            _pool.last_refresh_duration = time.perf_counter() - started
            _pool.candidates_checked = len(regular_alive) + len(whitelist_alive)
            _pool.candidates_alive = len(combined)
            _pool.source_info = "TsuloVPN"
            _pool.last_error = None

            wl_snis = [c.sni for c in whitelist_alive[:5]]
            logger.info(
                "Pool ready: %s (%s VPN + %s whitelist) in %.1fs | top WL SNI: %s",
                len(combined),
                len(regular_alive),
                len(whitelist_alive),
                _pool.last_refresh_duration,
                ", ".join(wl_snis) if wl_snis else "none",
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
            await refresh_pool(force=True)
        except Exception as exc:
            logger.error("Background refresh error: %s", exc)
