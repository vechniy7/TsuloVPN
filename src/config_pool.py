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


def _dedupe_uris(uris: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for uri in uris:
        if uri in seen:
            continue
        seen.add(uri)
        out.append(uri)
    return out


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


async def _fetch_sources(urls: list[str]) -> list[str]:
    sem = asyncio.Semaphore(config.FETCH_CONCURRENCY)

    async def limited(url: str) -> tuple[str, str | None]:
        async with sem:
            return await _fetch_url(url)

    results = await asyncio.gather(*(limited(u) for u in urls))
    merged: list[str] = []
    for url, text in results:
        if not text:
            continue
        parsed = parse_subscription_lines(text)
        logger.info("Loaded %s configs from %s", len(parsed), url.split("/")[-1])
        merged.extend(parsed)
    return merged


def _to_pool_configs(uris: list[str], category: str, limit: int) -> list[PoolConfig]:
    unique = _dedupe_uris(uris)[:limit]
    result: list[PoolConfig] = []
    for uri in unique:
        if not extract_host_port(uri):
            continue
        result.append(PoolConfig(uri=uri, category=category, sni=get_sni(uri) or ""))
    return result


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
            regular_raw, whitelist_raw = await asyncio.gather(
                _fetch_sources(config.REGULAR_SOURCE_URLS),
                _fetch_sources(config.WHITELIST_SOURCE_URLS),
            )

            regular = _to_pool_configs(regular_raw, "regular", config.TARGET_REGULAR_COUNT)
            whitelist = _to_pool_configs(whitelist_raw, "whitelist", config.TARGET_WHITELIST_COUNT)
            combined = regular + whitelist

            fingerprint = f"{len(regular)}:{len(whitelist)}:{hash(tuple(c.uri for c in combined[:20]))}"

            global _cached_lines, _lines_fingerprint
            if fingerprint != _lines_fingerprint or not _cached_lines:
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
