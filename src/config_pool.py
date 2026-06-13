import asyncio
import hashlib
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
    configs: list[str] = field(default_factory=list)
    source_total: int = 0
    subscription_count: int = 0
    last_refresh_at: float = 0.0
    last_refresh_duration: float = 0.0
    last_error: str | None = None
    is_refreshing: bool = False
    content_fingerprint: str = ""


_pool = PoolState()
_refresh_lock = asyncio.Lock()
_session: aiohttp.ClientSession | None = None
_cached_lines: list[str] = []


def get_pool_state() -> PoolState:
    return _pool


def get_subscription_lines() -> list[str]:
    return _cached_lines


def _build_lines(uris: list[str]) -> list[str]:
    lines: list[str] = []
    for idx, uri in enumerate(uris, start=1):
        label = build_server_label("whitelist", uri, idx)
        lines.append(brand_config(uri, label))
    return lines


def _content_fingerprint(text: str, uris: list[str]) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{len(uris)}:{digest[:16]}"


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


async def _fetch_source() -> tuple[str | None, list[str]]:
    session = await _get_session()
    try:
        async with session.get(config.CONFIG_SOURCE_URL, ssl=False) as resp:
            resp.raise_for_status()
            text = await resp.text()
    except Exception as exc:
        logger.warning("Fetch failed %s: %s", config.CONFIG_SOURCE_URL, exc)
        return None, []

    parsed = parse_subscription_lines(text)
    uris: list[str] = []
    for uri in parsed:
        if extract_host_port(uri):
            uris.append(uri)

    logger.info(
        "Loaded %s configs from %s (%s valid)",
        len(parsed),
        config.CONFIG_SOURCE_URL.split("/")[-1],
        len(uris),
    )
    return text, uris


async def refresh_pool(force: bool = False) -> PoolState:
    if _pool.is_refreshing and not force:
        return _pool

    async with _refresh_lock:
        if _pool.is_refreshing and not force:
            return _pool

        _pool.is_refreshing = True
        started = time.perf_counter()
        logger.info("Checking config source: %s", config.CONFIG_SOURCE_URL)

        try:
            text, uris = await _fetch_source()
            if text is None:
                _pool.last_error = "Failed to fetch config source"
                return _pool

            fingerprint = _content_fingerprint(text, uris)
            global _cached_lines

            if fingerprint == _pool.content_fingerprint and _cached_lines and not force:
                logger.info("Config source unchanged (%s configs)", len(uris))
                _pool.last_refresh_at = time.time()
                _pool.last_error = None
                return _pool

            limit = min(config.SUBSCRIPTION_CONFIG_LIMIT, len(uris))
            subscription_uris = uris[:limit]

            _pool.configs = uris
            _pool.source_total = len(uris)
            _pool.subscription_count = limit
            _pool.content_fingerprint = fingerprint
            _cached_lines = _build_lines(subscription_uris)
            _pool.last_refresh_at = time.time()
            _pool.last_refresh_duration = time.perf_counter() - started
            _pool.last_error = None

            logger.info(
                "Pool updated: %s in source, %s in user subscriptions (%.1fs)",
                len(uris),
                limit,
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
            await refresh_pool(force=False)
        except Exception as exc:
            logger.error("Background refresh error: %s", exc)
