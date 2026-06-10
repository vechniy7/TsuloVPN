import asyncio
import base64
import gc
import logging
import time
from dataclasses import dataclass, field

import aiohttp

from config import config
from parser import brand_config, build_server_label, extract_host_port, parse_subscription_lines

logger = logging.getLogger(__name__)

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@dataclass
class PoolState:
    regular_count: int = 0
    whitelist_count: int = 0
    last_refresh_at: float = 0.0
    last_refresh_duration: float = 0.0
    last_error: str | None = None
    is_refreshing: bool = False
    sources_fingerprint: str = ""

    @property
    def is_ready(self) -> bool:
        return _subscription_body is not None


_pool = PoolState()
_refresh_lock = asyncio.Lock()
_session: aiohttp.ClientSession | None = None
_subscription_body: str | None = None


def get_pool_state() -> PoolState:
    return _pool


def get_subscription_body() -> str | None:
    return _subscription_body


def _build_subscription_body(regular: list[str], whitelist: list[str]) -> str:
    lines: list[str] = []
    for idx, uri in enumerate(regular, start=1):
        label = build_server_label("regular", uri, idx)
        lines.append(brand_config(uri, label))
    for idx, uri in enumerate(whitelist, start=1):
        label = build_server_label("whitelist", uri, idx)
        lines.append(brand_config(uri, label))
    plain = "\n".join(lines)
    return base64.b64encode(plain.encode("utf-8")).decode("ascii")


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        timeout = aiohttp.ClientTimeout(total=config.FETCH_TIMEOUT)
        connector = aiohttp.TCPConnector(limit=2, ttl_dns_cache=300)
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


async def _fetch_url(url: str) -> str | None:
    session = await _get_session()
    try:
        async with session.get(url, ssl=False) as resp:
            resp.raise_for_status()
            return await resp.text()
    except Exception as exc:
        logger.warning("Fetch failed %s: %s", url, exc)
        return None


async def _collect_uris(urls: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        if len(result) >= limit:
            break
        text = await _fetch_url(url)
        if not text:
            continue
        parsed = parse_subscription_lines(text)
        logger.info("Loaded %s configs from %s", len(parsed), url.split("/")[-1])
        del text
        for uri in parsed:
            if uri in seen:
                continue
            if not extract_host_port(uri):
                continue
            seen.add(uri)
            result.append(uri)
            if len(result) >= limit:
                break
        del parsed
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
            whitelist = await _collect_uris(
                config.WHITELIST_SOURCE_URLS,
                config.TARGET_WHITELIST_COUNT,
            )
            regular = await _collect_uris(
                config.REGULAR_SOURCE_URLS,
                config.TARGET_REGULAR_COUNT,
            )

            regular_count = len(regular)
            whitelist_count = len(whitelist)
            fingerprint = (
                f"{regular_count}:{whitelist_count}:"
                f"{hash(tuple(regular[:5] + whitelist[:5]))}"
            )

            global _subscription_body
            _subscription_body = _build_subscription_body(regular, whitelist)
            del regular, whitelist

            _pool.regular_count = regular_count
            _pool.whitelist_count = whitelist_count
            _pool.last_refresh_at = time.time()
            _pool.last_refresh_duration = time.perf_counter() - started
            _pool.sources_fingerprint = fingerprint
            _pool.last_error = None

            logger.info(
                "Pool ready: %s total (%s VPN + %s whitelist) in %.1fs",
                regular_count + whitelist_count,
                regular_count,
                whitelist_count,
                _pool.last_refresh_duration,
            )
            gc.collect()
        except Exception as exc:
            _pool.last_error = str(exc)
            logger.exception("Pool refresh failed: %s", exc)
        finally:
            _pool.is_refreshing = False

        return _pool


async def start_refresh_loop() -> None:
    await asyncio.sleep(3)
    await refresh_pool(force=True)
    while True:
        await asyncio.sleep(config.POOL_REFRESH_INTERVAL)
        try:
            await refresh_pool(force=True)
        except Exception as exc:
            logger.error("Background refresh error: %s", exc)
