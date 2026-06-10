import asyncio
import logging
import time
from dataclasses import dataclass, field

import aiohttp

from config import config
from parser import brand_config, build_server_label, extract_host_port, get_sni, parse_subscription_lines

logger = logging.getLogger(__name__)

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@dataclass
class PoolConfig:
    uri: str
    category: str
    sni: str = ""


@dataclass
class PoolState:
    configs: list[PoolConfig] = field(default_factory=list)
    regular_count: int = 0
    whitelist_count: int = 0
    last_refresh_at: float = 0.0
    last_refresh_duration: float = 0.0
    last_error: str | None = None
    is_refreshing: bool = False
    sources_fingerprint: str = ""


_pool = PoolState()
_refresh_lock = asyncio.Lock()
_session: aiohttp.ClientSession | None = None
_cached_lines: list[str] = []
_lines_fingerprint: str = ""


def get_pool_state() -> PoolState:
    return _pool


def _config_to_line(item: PoolConfig, regular_idx: int, whitelist_idx: int) -> str:
    if item.category == "whitelist":
        label = build_server_label("whitelist", item.uri, whitelist_idx)
    else:
        label = build_server_label("regular", item.uri, regular_idx)
    return brand_config(item.uri, label)


def _build_lines(configs: list[PoolConfig]) -> list[str]:
    lines: list[str] = []
    regular_idx = 0
    whitelist_idx = 0
    for item in configs:
        if item.category == "whitelist":
            whitelist_idx += 1
            lines.append(_config_to_line(item, regular_idx, whitelist_idx))
        else:
            regular_idx += 1
            lines.append(_config_to_line(item, regular_idx, whitelist_idx))
    return lines


def get_subscription_lines() -> list[str]:
    return _cached_lines


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        timeout = aiohttp.ClientTimeout(total=config.FETCH_TIMEOUT)
        connector = aiohttp.TCPConnector(limit=config.FETCH_CONCURRENCY, ttl_dns_cache=300)
        _session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers={"User-Agent": CHROME_UA},
        )
    return _session


async def close_session() -> None:
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None


async def _fetch_url(url: str) -> tuple[str, str | None]:
    session = await _get_session()
    try:
        async with session.get(url, ssl=False) as resp:
            resp.raise_for_status()
            return url, await resp.text()
    except Exception as exc:
        logger.warning("Fetch failed %s: %s", url, exc)
        return url, None


async def _collect_uris(urls: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        if len(result) >= limit:
            break
        _, text = await _fetch_url(url)
        if not text:
            continue
        parsed = parse_subscription_lines(text)
        logger.info("Loaded %s configs from %s", len(parsed), url.split("/")[-1])
        for uri in parsed:
            if uri in seen:
                continue
            if not extract_host_port(uri):
                continue
            seen.add(uri)
            result.append(uri)
            if len(result) >= limit:
                break
    return result


def _to_pool_configs(uris: list[str], category: str) -> list[PoolConfig]:
    return [
        PoolConfig(uri=uri, category=category, sni=get_sni(uri) or "")
        for uri in uris
    ]


async def refresh_pool(force: bool = False) -> PoolState:
    if _pool.is_refreshing and not force:
        return _pool

    async with _refresh_lock:
        if _pool.is_refreshing and not force:
            return _pool

        _pool.is_refreshing = True
        started = time.perf_counter()
        logger.info("Refreshing config pool...")

        try:
            regular_uris, whitelist_uris = await asyncio.gather(
                _collect_uris(config.REGULAR_SOURCE_URLS, config.TARGET_REGULAR_COUNT),
                _collect_uris(config.WHITELIST_SOURCE_URLS, config.TARGET_WHITELIST_COUNT),
            )

            regular = _to_pool_configs(regular_uris, "regular")
            whitelist = _to_pool_configs(whitelist_uris, "whitelist")
            combined = regular + whitelist

            fingerprint = f"{len(regular)}:{len(whitelist)}:{hash(tuple(c.uri for c in combined[:20]))}"

            global _cached_lines, _lines_fingerprint
            _cached_lines = _build_lines(combined)
            _lines_fingerprint = fingerprint

            _pool.configs = combined
            _pool.regular_count = len(regular)
            _pool.whitelist_count = len(whitelist)
            _pool.last_refresh_at = time.time()
            _pool.last_refresh_duration = time.perf_counter() - started
            _pool.sources_fingerprint = fingerprint
            _pool.last_error = None

            logger.info(
                "Pool ready: %s total (%s VPN + %s whitelist) in %.1fs",
                len(combined),
                len(regular),
                len(whitelist),
                _pool.last_refresh_duration,
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
