import asyncio
import logging
import random
import time
from dataclasses import dataclass, field

import aiohttp

from config import config
from parser import brand_config, extract_host_port, parse_configs

logger = logging.getLogger(__name__)


@dataclass
class WorkingConfig:
    uri: str
    host: str
    port: int
    latency_ms: int
    category: str  # regular | whitelist


@dataclass
class PoolState:
    configs: list[WorkingConfig] = field(default_factory=list)
    last_refresh_at: float = 0.0
    last_refresh_duration: float = 0.0
    candidates_checked: int = 0
    candidates_alive: int = 0
    last_error: str | None = None
    is_refreshing: bool = False


_pool = PoolState()
_refresh_lock = asyncio.Lock()
_session: aiohttp.ClientSession | None = None

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def get_pool_state() -> PoolState:
    return _pool


def get_working_subscription_lines() -> list[str]:
    lines: list[str] = []
    regular_idx = 0
    whitelist_idx = 0

    for item in _pool.configs:
        if item.category == "whitelist":
            whitelist_idx += 1
            label = f"{config.BOT_NAME} | Белый список #{whitelist_idx} | {item.latency_ms}ms"
        else:
            regular_idx += 1
            label = f"{config.BOT_NAME} | VPN #{regular_idx} | {item.latency_ms}ms"
        lines.append(brand_config(item.uri, label))
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


async def _fetch_source(source_id: int) -> list[str]:
    url = f"{config.GOIDA_RAW_BASE}/{source_id}.txt"
    session = await _get_session()
    try:
        async with session.get(url, ssl=False) as resp:
            resp.raise_for_status()
            text = await resp.text()
            return parse_configs(text)
    except Exception as exc:
        logger.warning("Failed to fetch source %s: %s", source_id, exc)
        return []


def _dedupe_configs(configs: list[str]) -> list[str]:
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


async def _tcp_latency(host: str, port: int) -> int | None:
    started = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=config.HEALTH_CHECK_TIMEOUT,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        elapsed = int((time.perf_counter() - started) * 1000)
        return max(elapsed, 1)
    except Exception:
        return None


async def _health_check_batch(
    uris: list[str],
    category: str,
    limit: int,
) -> list[WorkingConfig]:
    semaphore = asyncio.Semaphore(config.HEALTH_CHECK_CONCURRENCY)
    alive: list[WorkingConfig] = []

    async def check_one(uri: str) -> WorkingConfig | None:
        hostport = extract_host_port(uri)
        if not hostport:
            return None
        host, port = hostport
        async with semaphore:
            latency = await _tcp_latency(host, port)
        if latency is None:
            return None
        return WorkingConfig(uri=uri, host=host, port=port, latency_ms=latency, category=category)

    tasks = [asyncio.create_task(check_one(uri)) for uri in uris]
    for task in asyncio.as_completed(tasks):
        result = await task
        if result:
            alive.append(result)
        if len(alive) >= limit * 3:
            for pending in tasks:
                if not pending.done():
                    pending.cancel()
            break

    alive.sort(key=lambda item: item.latency_ms)
    return alive[:limit]


async def refresh_pool(force: bool = False) -> PoolState:
    if _pool.is_refreshing and not force:
        return _pool

    async with _refresh_lock:
        if _pool.is_refreshing and not force:
            return _pool

        _pool.is_refreshing = True
        started = time.perf_counter()
        logger.info("Refreshing TsuloVPN config pool...")

        try:
            regular_raw: list[str] = []
            for source_id in config.REGULAR_SOURCE_IDS:
                regular_raw.extend(await _fetch_source(source_id))

            whitelist_raw = await _fetch_source(config.WHITELIST_SOURCE_ID)
            regular_unique = _dedupe_configs(regular_raw)
            whitelist_unique = _dedupe_configs(whitelist_raw)

            random.shuffle(regular_unique)
            random.shuffle(whitelist_unique)

            regular_candidates = regular_unique[: config.MAX_HEALTH_CHECK_CANDIDATES]
            whitelist_candidates = whitelist_unique[: config.MAX_HEALTH_CHECK_CANDIDATES]

            regular_alive, whitelist_alive = await asyncio.gather(
                _health_check_batch(
                    regular_candidates,
                    "regular",
                    config.TARGET_REGULAR_COUNT,
                ),
                _health_check_batch(
                    whitelist_candidates,
                    "whitelist",
                    config.TARGET_WHITELIST_COUNT,
                ),
            )

            if len(regular_alive) < config.TARGET_REGULAR_COUNT:
                extra_needed = config.TARGET_REGULAR_COUNT - len(regular_alive)
                extra_pool = [u for u in regular_candidates if u not in {c.uri for c in regular_alive}]
                extra_alive = await _health_check_batch(extra_pool, "regular", extra_needed)
                regular_alive.extend(extra_alive)

            if len(whitelist_alive) < config.TARGET_WHITELIST_COUNT:
                extra_needed = config.TARGET_WHITELIST_COUNT - len(whitelist_alive)
                extra_pool = [u for u in whitelist_candidates if u not in {c.uri for c in whitelist_alive}]
                extra_alive = await _health_check_batch(extra_pool, "whitelist", extra_needed)
                whitelist_alive.extend(extra_alive)

            combined = regular_alive[: config.TARGET_REGULAR_COUNT]
            combined.extend(whitelist_alive[: config.TARGET_WHITELIST_COUNT])
            combined.sort(key=lambda item: (item.category != "regular", item.latency_ms))

            _pool.configs = combined
            _pool.last_refresh_at = time.time()
            _pool.last_refresh_duration = time.perf_counter() - started
            _pool.candidates_checked = len(regular_candidates) + len(whitelist_candidates)
            _pool.candidates_alive = len(regular_alive) + len(whitelist_alive)
            _pool.last_error = None

            logger.info(
                "Pool refreshed: %s working (%s regular, %s whitelist) in %.1fs",
                len(combined),
                min(len(regular_alive), config.TARGET_REGULAR_COUNT),
                min(len(whitelist_alive), config.TARGET_WHITELIST_COUNT),
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
