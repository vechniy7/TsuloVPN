import asyncio
import logging
import ssl
import time
from dataclasses import dataclass, field

import aiohttp

from config import config
from parser import (
    brand_config,
    extract_host_port,
    get_security,
    get_sni,
    parse_vpn_configs,
    parse_whitelist_configs,
    whitelist_score,
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
            sni_short = (item.sni or "BS").split(".")[0]
            label = f"{config.BOT_NAME} | БС {sni_short} #{whitelist_idx}"
        else:
            regular_idx += 1
            label = f"{config.BOT_NAME} | VPN #{regular_idx}"
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


async def _fetch_regular_file(filename: str) -> list[str]:
    url = f"{config.CONFIG_RAW_BASE}/{filename}"
    session = await _get_session()
    try:
        async with session.get(url, ssl=False) as resp:
            resp.raise_for_status()
            text = await resp.text()
            configs = parse_vpn_configs(text)
            logger.info("Regular: %s configs from %s", len(configs), filename)
            return configs
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", filename, exc)
        return []


async def _fetch_whitelist_file(filename: str) -> list[str]:
    url = f"{config.CONFIG_RAW_BASE}/{filename}"
    session = await _get_session()
    try:
        async with session.get(url, ssl=False) as resp:
            resp.raise_for_status()
            text = await resp.text()
            configs = parse_whitelist_configs(text)
            logger.info("Whitelist: %s RU-SNI configs from %s", len(configs), filename)
            return configs
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", filename, exc)
        return []


def _dedupe_preserve_order(configs: list[str]) -> list[str]:
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


async def _probe_latency(host: str, port: int, uri: str) -> int | None:
    started = time.perf_counter()
    security = get_security(uri)
    sni = get_sni(uri) or host

    try:
        if security in ("tls", "reality"):
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


async def _collect_regular(limit: int) -> list[WorkingConfig]:
    raw: list[str] = []
    for filename in config.REGULAR_SOURCES:
        raw.extend(await _fetch_regular_file(filename))
        if len(_dedupe_preserve_order(raw)) >= limit:
            break

    unique = _dedupe_preserve_order(raw)[:limit]
    result = []
    for uri in unique:
        hostport = extract_host_port(uri)
        if not hostport:
            continue
        host, port = hostport
        result.append(
            WorkingConfig(
                uri=uri, host=host, port=port, latency_ms=0,
                category="regular", sni=get_sni(uri) or "",
            )
        )
    return result


async def _collect_whitelist(limit: int) -> list[WorkingConfig]:
    """Собирает конфиги для обхода белых списков — только Reality + российский SNI."""
    raw: list[str] = []

    for filename in config.WHITELIST_SOURCES:
        configs = await _fetch_whitelist_file(filename)
        raw.extend(configs)
        if len(_dedupe_preserve_order(raw)) >= limit * 2:
            break

    # Сортируем по качеству для мобильного интернета (Мегафон и др.)
    unique = _dedupe_preserve_order(raw)
    unique.sort(key=whitelist_score, reverse=True)

    logger.info(
        "Whitelist candidates with RU SNI: %s (top SNI: %s)",
        len(unique),
        get_sni(unique[0]) if unique else "none",
    )

    result = []
    for uri in unique[:limit]:
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
                category="whitelist",
                sni=get_sni(uri) or "",
            )
        )
    return result


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
