import logging
import urllib.parse

import aiohttp

from config import config
from parser import (
    bypass_whitelist_score,
    extract_host_port,
    get_security,
    get_sni,
    get_transport,
    parse_bypass_subscription_all,
)

logger = logging.getLogger(__name__)

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_bypass_cache: list[str] = []
_bypass_cache_at: float = 0.0
_CACHE_TTL = 300


async def fetch_bypass_config_uris(force: bool = False) -> list[str]:
    global _bypass_cache, _bypass_cache_at
    import time

    now = time.time()
    if not force and _bypass_cache and now - _bypass_cache_at < _CACHE_TTL:
        return list(_bypass_cache)

    timeout = aiohttp.ClientTimeout(total=config.FETCH_TIMEOUT)
    async with aiohttp.ClientSession(
        timeout=timeout,
        headers={"User-Agent": CHROME_UA},
    ) as session:
        async with session.get(config.BYPASS_SOURCE_URL, ssl=False) as resp:
            resp.raise_for_status()
            text = await resp.text()

    uris = parse_bypass_subscription_all(text)
    _bypass_cache = uris
    _bypass_cache_at = now
    logger.info("Loaded %s bypass configs for mini app", len(uris))
    return list(uris)


def uri_to_probe_target(index: int, uri: str) -> dict | None:
    hostport = extract_host_port(uri)
    if not hostport:
        return None
    host, port = hostport
    params = {}
    if "?" in uri:
        query = uri.split("?", 1)[1].split("#", 1)[0]
        params = {k.lower(): v for k, v in urllib.parse.parse_qsl(query, keep_blank_values=True)}

    path = params.get("path") or "/"
    if path and not path.startswith("/"):
        path = "/" + path

    return {
        "id": index,
        "uri": uri,
        "host": host,
        "port": port,
        "transport": get_transport(uri),
        "security": get_security(uri),
        "sni": get_sni(uri) or host,
        "path": path,
    }


async def get_probe_targets(force: bool = False) -> list[dict]:
    uris = await fetch_bypass_config_uris(force=force)
    targets: list[dict] = []
    for idx, uri in enumerate(uris):
        target = uri_to_probe_target(idx, uri)
        if target:
            targets.append(target)
    return targets


def _matches_priority_sni(sni: str, priority_sni: str) -> bool:
    sni_l = sni.lower()
    psni_l = priority_sni.lower()
    return sni_l == psni_l or psni_l in sni_l


def _dedupe_by_uri(uris: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for uri in uris:
        if uri in seen:
            continue
        seen.add(uri)
        unique.append(uri)
    return unique


def _prioritize_bootstrap_uris(uris: list[str], limit: int) -> list[str]:
    """Топ обходов для стартового ключа — приоритет urent, x5, vk, mwscdn."""
    buckets: dict[str, list[str]] = {sni: [] for sni in config.WHITELIST_PRIORITY_SNIS}
    rest: list[str] = []
    seen: set[str] = set()

    for uri in uris:
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
            if uri not in ordered:
                ordered.append(uri)

    rest.sort(key=bypass_whitelist_score, reverse=True)
    for uri in rest:
        if uri not in ordered:
            ordered.append(uri)
        if len(ordered) >= limit:
            break

    return ordered[:limit]


async def get_bootstrap_bypass_uris(limit: int | None = None) -> list[str]:
    """Стартовые обходы без проверки с телефона — для первого подключения."""
    target = limit or config.PERSONAL_BYPASS_TARGET
    all_uris = await fetch_bypass_config_uris()
    candidates = [u for u in all_uris if bypass_whitelist_score(u) >= 40]
    if not candidates:
        candidates = all_uris
    return _prioritize_bootstrap_uris(_dedupe_by_uri(candidates), target)


async def assign_bootstrap_bypass(telegram_id: int) -> list[str]:
    from database import save_personal_bypass

    uris = await get_bootstrap_bypass_uris()
    if not uris:
        return []
    await save_personal_bypass(telegram_id, uris, [0] * len(uris))
    logger.info("Bootstrap bypass assigned to user %s (%s configs)", telegram_id, len(uris))
    return uris


def is_probed_bypass(user) -> bool:
    import json

    if not user.personal_bypass_latencies:
        return False
    try:
        lats = json.loads(user.personal_bypass_latencies)
        return any(isinstance(x, int) and x > 0 for x in lats)
    except json.JSONDecodeError:
        return False


def build_personal_subscription_lines(uris: list[str]) -> list[str]:
    from parser import brand_config, build_server_label

    lines: list[str] = []
    for idx, uri in enumerate(uris, start=1):
        label = build_server_label("whitelist", uri, idx)
        lines.append(brand_config(uri, label))
    return lines
