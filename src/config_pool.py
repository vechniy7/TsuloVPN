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
from xray_builder import uri_to_outbound

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


def _content_fingerprint(texts: list[str], uris: list[str]) -> str:
    digest = hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()
    return f"{len(uris)}:{digest[:16]}"


def _config_identity(uri: str) -> str:
    """Identity for dedup: host:port + protocol + uuid/user without fragment."""
    base = uri.split("#", 1)[0].strip().lower()
    return base


def _source_label(url: str) -> str:
    return url.rstrip("/").split("/")[-1] or url


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


async def _fetch_url(url: str) -> tuple[str, str | None, list[str]]:
    """Returns (label, text_or_None, uris)."""
    label = _source_label(url)
    session = await _get_session()
    try:
        async with session.get(url, ssl=False) as resp:
            resp.raise_for_status()
            text = await resp.text()
    except Exception as exc:
        logger.warning("Fetch failed %s: %s", label, exc)
        return label, None, []

    parsed = parse_subscription_lines(text)
    uris: list[str] = []
    for uri in parsed:
        if extract_host_port(uri):
            uris.append(uri)

    logger.info(
        "Loaded %s configs from %s (%s valid)",
        len(parsed),
        label,
        len(uris),
    )
    return label, text, uris


def _merge_sources(
    ranked_by_source: list[tuple[str, list[str]]],
    limit: int,
) -> tuple[list[str], dict[str, int]]:
    """
    Priority fill up to limit:
      1) WHITE-CIDR-RU-checked
      2) Mobile
      3) extras (all / SNI / verified …)
    Keep source order — do NOT globally re-rank (that drowned whitelist in aggregators).
    Only Xray-convertible URIs (vless/trojan) enter АВТО-ВЫБОР.
    """
    result: list[str] = []
    seen: set[str] = set()
    final_counts: dict[str, int] = {label: 0 for label, _ in ranked_by_source}

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
            final_counts[label] += 1
        if len(result) >= limit:
            break

    return result, final_counts


async def refresh_pool(force: bool = False) -> PoolState:
    if _pool.is_refreshing and not force:
        return _pool

    async with _refresh_lock:
        if _pool.is_refreshing and not force:
            return _pool

        _pool.is_refreshing = True
        started = time.perf_counter()
        urls = config.config_source_urls()
        labels = [_source_label(u) for u in urls]
        logger.info("Checking %s sources: %s", len(urls), ", ".join(labels))

        try:
            results = await asyncio.gather(*[_fetch_url(url) for url in urls])

            if all(text is None for _, text, _ in results):
                _pool.last_error = "Failed to fetch all config sources"
                return _pool

            ranked_by_source: list[tuple[str, list[str]]] = []
            texts: list[str] = []
            total_raw = 0
            for label, text, uris in results:
                texts.append(text or "")
                ranked = rank_configs_for_speed(uris or [])
                ranked_by_source.append((label, ranked))
                total_raw += len(ranked)

            limit = config.SUBSCRIPTION_CONFIG_LIMIT
            subscription_uris, source_counts = _merge_sources(ranked_by_source, limit)

            fingerprint = _content_fingerprint(texts, subscription_uris)
            global _cached_lines

            if fingerprint == _pool.content_fingerprint and _cached_lines and not force:
                logger.info(
                    "Config sources unchanged (%s nodes in АВТО from %s unique)",
                    len(subscription_uris),
                    total_raw,
                )
                _pool.last_refresh_at = time.time()
                _pool.last_error = None
                return _pool

            counts_list = list(source_counts.values())
            primary_used = counts_list[0] if counts_list else 0
            fill_used = sum(counts_list[1:]) if len(counts_list) > 1 else 0

            _pool.configs = subscription_uris
            _pool.source_total = total_raw
            _pool.primary_count = primary_used
            _pool.fill_count = fill_used
            _pool.source_counts = source_counts
            _pool.subscription_count = len(subscription_uris)
            _pool.content_fingerprint = fingerprint
            _cached_lines = _build_lines(subscription_uris)
            _pool.last_refresh_at = time.time()
            _pool.last_refresh_duration = time.perf_counter() - started
            _pool.last_error = None

            breakdown = ", ".join(f"{k}={v}" for k, v in source_counts.items())
            logger.info(
                "Pool updated: %s nodes in АВТО (%s), unique from sources %s (%.1fs)",
                len(subscription_uris),
                breakdown or "empty",
                total_raw,
                _pool.last_refresh_duration,
            )
            if len(subscription_uris) < limit:
                logger.warning(
                    "Auto pool has only %s configs (wanted %s)",
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
