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
    lte_speed_score,
    parse_subscription_lines,
    rank_configs_for_speed,
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
) -> tuple[list[str], dict[str, int]]:
    """
    LTE: source priority order (Mobile → CIDR → …), cap at limit.
    Keep ALL unique convertible URIs from earlier sources (fp/query variants),
    no host:port collapse — so Mobile list is fully probed first.
    """
    result: list[str] = []
    seen: set[str] = set()
    counts: dict[str, int] = {label: 0 for label, _ in raw_by_source}

    for label, uris in raw_by_source:
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
            counts[label] += 1
        if len(result) >= limit:
            break

    # Best heuristic first = fallback while YouTube probes warm up
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
            results = await asyncio.gather(*[_fetch_url(url) for url in all_urls])
            by_label: dict[str, tuple[str | None, list[str]]] = {}
            for label, text, uris in results:
                by_label[label] = (text, uris)

            if all(text is None for text, _ in by_label.values()):
                _pool.last_error = "Failed to fetch all config sources"
                return _pool

            texts: list[str] = []
            wifi_ranked: list[tuple[str, list[str]]] = []
            lte_raw: list[tuple[str, list[str]]] = []
            total_raw = 0

            for url in wifi_urls:
                label = _source_label(url)
                text, uris = by_label.get(label, (None, []))
                texts.append(text or "")
                ranked = rank_configs_for_speed(uris or [])
                wifi_ranked.append((label, ranked))
                total_raw += len(ranked)

            for url in lte_urls:
                label = _source_label(url)
                text, uris = by_label.get(label, (None, []))
                if url not in wifi_urls:
                    texts.append(text or "")
                # Raw list — no host collapse; Mobile variants must all be probeable
                raw = list(uris or [])
                lte_raw.append((label, raw))
                total_raw += len(raw)

            limit = config.SUBSCRIPTION_CONFIG_LIMIT
            lte_limit = config.LTE_CONFIG_LIMIT
            wifi_uris, wifi_counts = _prepare_pool(wifi_ranked, limit)
            lte_uris, lte_counts = _prepare_lte_pool(lte_raw, lte_limit)

            fingerprint = _content_fingerprint(texts, wifi_uris, lte_uris)
            global _cached_wifi_lines, _cached_lte_lines

            if (
                fingerprint == _pool.content_fingerprint
                and _cached_wifi_lines
                and _cached_lte_lines
                and not force
            ):
                logger.info(
                    "Sources unchanged (WIFI=%s LTE=%s from %s ranked)",
                    len(wifi_uris),
                    len(lte_uris),
                    total_raw,
                )
                _pool.last_refresh_at = time.time()
                _pool.last_error = None
                return _pool

            _cached_wifi_lines = _build_lines(wifi_uris, "wifi")
            _cached_lte_lines = _build_lines(lte_uris, "lte")

            _pool.wifi_uris = wifi_uris
            _pool.lte_uris = lte_uris
            _pool.wifi_count = len(wifi_uris)
            _pool.lte_count = len(lte_uris)
            _pool.wifi_source_counts = wifi_counts
            _pool.lte_source_counts = lte_counts
            _pool.configs = wifi_uris + lte_uris
            _pool.source_total = total_raw
            _pool.primary_count = len(wifi_uris)
            _pool.fill_count = len(lte_uris)
            _pool.source_counts = {**wifi_counts, **lte_counts}
            _pool.subscription_count = len(wifi_uris) + len(lte_uris)
            _pool.content_fingerprint = fingerprint
            _pool.last_refresh_at = time.time()
            _pool.last_refresh_duration = time.perf_counter() - started
            _pool.last_error = None

            logger.info(
                "Pools updated: WIFI=%s (%s) LTE=%s (%s) in %.1fs",
                len(wifi_uris),
                ", ".join(f"{k}={v}" for k, v in wifi_counts.items() if v),
                len(lte_uris),
                ", ".join(f"{k}={v}" for k, v in lte_counts.items() if v),
                _pool.last_refresh_duration,
            )
            if len(wifi_uris) < 2:
                logger.warning("WIFI auto pool too small: %s (need ≥2 for leastPing)", len(wifi_uris))
            if len(lte_uris) < 2:
                logger.warning("LTE auto pool too small: %s (need ≥2 for leastPing)", len(lte_uris))
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
