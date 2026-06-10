import logging
import urllib.parse

import aiohttp

from config import config
from parser import (
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


def build_personal_subscription_lines(uris: list[str]) -> list[str]:
    from parser import brand_config, build_server_label

    lines: list[str] = []
    for idx, uri in enumerate(uris, start=1):
        label = build_server_label("whitelist", uri, idx)
        lines.append(brand_config(uri, label))
    return lines
