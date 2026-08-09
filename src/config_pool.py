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
    parse_subscription_lines,
    rank_configs_for_speed,
)

logger = logging.getLogger(__name__)

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@dataclass
class PoolState:
    configs: list[str] = field(default_factory=list)
    source_total: int = 0
    primary_count: int = 0
    fill_count: int = 0
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


def _content_fingerprint(primary_text: str, fill_text: str, uris: list[str]) -> str:
    digest = hashlib.sha256((primary_text + "\n" + fill_text).encode("utf-8")).hexdigest()
    return f"{len(uris)}:{digest[:16]}"


def _config_identity(uri: str) -> str:
    """Identity for dedup: host:port + protocol + uuid/user without fragment."""
    base = uri.split("#", 1)[0].strip().lower()
    return base


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


async def _fetch_url(url: str) -> tuple[str | None, list[str]]:
    session = await _get_session()
    try:
        async with session.get(url, ssl=False) as resp:
            resp.raise_for_status()
            text = await resp.text()
    except Exception as exc:
        logger.warning("Fetch failed %s: %s", url, exc)
        return None, []

    parsed = parse_subscription_lines(text)
    uris: list[str] = []
    for uri in parsed:
        if extract_host_port(uri):
            uris.append(uri)

    logger.info(
        "Loaded %s configs from %s (%s valid)",
        len(parsed),
        url.split("/")[-1],
        len(uris),
    )
    return text, uris


def _merge_up_to_limit(primary: list[str], fill: list[str], limit: int) -> tuple[list[str], int, int]:
    """Primary first, then fill from secondary without duplicates. Cap at limit."""
    result: list[str] = []
    seen: set[str] = set()

    for uri in primary:
        if len(result) >= limit:
            break
        key = _config_identity(uri)
        if key in seen:
            continue
        seen.add(key)
        result.append(uri)

    primary_used = len(result)

    for uri in fill:
        if len(result) >= limit:
            break
        key = _config_identity(uri)
        if key in seen:
            continue
        seen.add(key)
        result.append(uri)

    fill_used = len(result) - primary_used
    return result, primary_used, fill_used


async def refresh_pool(force: bool = False) -> PoolState:
    if _pool.is_refreshing and not force:
        return _pool

    async with _refresh_lock:
        if _pool.is_refreshing and not force:
            return _pool

        _pool.is_refreshing = True
        started = time.perf_counter()
        logger.info(
            "Checking sources: primary=%s fill=%s",
            config.CONFIG_SOURCE_URL.split("/")[-1],
            config.CONFIG_FILL_SOURCE_URL.split("/")[-1],
        )

        try:
            primary_text, primary_uris = await _fetch_url(config.CONFIG_SOURCE_URL)
            fill_text, fill_uris = await _fetch_url(config.CONFIG_FILL_SOURCE_URL)

            if primary_text is None and fill_text is None:
                _pool.last_error = "Failed to fetch both config sources"
                return _pool

            primary_text = primary_text or ""
            fill_text = fill_text or ""
            primary_uris = rank_configs_for_speed(primary_uris or [])
            fill_uris = rank_configs_for_speed(fill_uris or [])

            limit = config.SUBSCRIPTION_CONFIG_LIMIT
            subscription_uris, primary_used, fill_used = _merge_up_to_limit(
                primary_uris, fill_uris, limit
            )

            fingerprint = _content_fingerprint(primary_text, fill_text, subscription_uris)
            global _cached_lines

            if fingerprint == _pool.content_fingerprint and _cached_lines and not force:
                logger.info(
                    "Config sources unchanged (%s in key: %s primary + %s fill)",
                    len(subscription_uris),
                    primary_used,
                    fill_used,
                )
                _pool.last_refresh_at = time.time()
                _pool.last_error = None
                return _pool

            _pool.configs = subscription_uris
            _pool.source_total = len(primary_uris) + len(fill_uris)
            _pool.primary_count = primary_used
            _pool.fill_count = fill_used
            _pool.subscription_count = len(subscription_uris)
            _pool.content_fingerprint = fingerprint
            _cached_lines = _build_lines(subscription_uris)
            _pool.last_refresh_at = time.time()
            _pool.last_refresh_duration = time.perf_counter() - started
            _pool.last_error = None

            logger.info(
                "Pool updated: %s in key (%s from primary, %s from fill), "
                "sources %s+%s (%.1fs)",
                len(subscription_uris),
                primary_used,
                fill_used,
                len(primary_uris),
                len(fill_uris),
                _pool.last_refresh_duration,
            )
            if len(subscription_uris) < limit:
                logger.warning(
                    "Subscription has only %s configs (wanted %s)",
                    len(subscription_uris),
                    limit,
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
