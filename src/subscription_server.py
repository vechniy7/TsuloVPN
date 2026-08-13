import base64
import logging
import time
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Response

from config import config
from config_pool import get_lte_uris, get_pool_state, get_wifi_lines
from database import get_user_by_token
from lte_subscription import build_lte_classic_lines, lte_classic_subscription_bytes
from miniapp_routes import router as miniapp_router
from cardlink_routes import router as cardlink_router
from payments import is_subscription_active
from xray_builder import build_subscription_json, subscription_json_bytes

logger = logging.getLogger(__name__)

app = FastAPI(title="TsuloVPN Subscription Server", docs_url=None, redoc_url=None)
app.include_router(miniapp_router)
app.include_router(cardlink_router)

HAPP_HEADERS = {
    "hide-settings": "1",
    "subscription-autoconnect": "0",
    "subscription-ping-onopen-enabled": "1",
    "ping-type": "proxy",
    "check-url-via-proxy": "https://www.gstatic.com/generate_204",
    "fragmentation-enable": "1",
}


def _source_name(url: str) -> str:
    return url.rstrip("/").split("/")[-1] or url


@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    pool = get_pool_state()
    return {
        "status": "ok",
        "wifi_count": pool.wifi_count,
        "lte_count": pool.lte_count,
        "wifi_sources": pool.wifi_source_counts,
        "lte_sources": pool.lte_source_counts,
        "limit_per_profile": config.SUBSCRIPTION_CONFIG_LIMIT,
        "lte_limit": config.LTE_CONFIG_LIMIT,
        "lte_max_rtt_ms": config.LTE_MAX_RTT_MS,
        "lte_min_bypass_score": config.LTE_MIN_BYPASS_SCORE,
        "lte_balancer_nodes": config.LTE_BALANCER_NODES,
        "lte_endpoint": "/sub/{token}/lte",
        "lte_format": "classic-vless-base64",
        "lte_require_whitelist_ip": config.LTE_REQUIRE_WHITELIST_IP,
        "lte_tcp_check": config.LTE_TCP_CHECK,
        "wifi_probe": config.WIFI_PROBE_URL,
        "lte_probe": config.LTE_PROBE_URL,
        "probe_interval_sec": config.AUTO_PROBE_INTERVAL_SEC,
        "lte_probe_interval_sec": config.LTE_PROBE_INTERVAL_SEC,
        "last_refresh_at": pool.last_refresh_at,
        "is_refreshing": pool.is_refreshing,
        "last_error": pool.last_error,
        "wifi_urls": [_source_name(u) for u in config.wifi_source_urls()],
        "lte_urls": [_source_name(u) for u in config.lte_source_urls()],
        "auto_select": "WIFI-json + LTE-json-profiles",
        "visible_profiles": f"1 wifi + up to {config.LTE_BALANCER_NODES} lte",
        # legacy fields
        "subscription_count": pool.subscription_count,
        "source_counts": pool.source_counts,
    }


async def _subscription_user(token: str):
    user = await get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if config.payments_active and not user.is_admin and not is_subscription_active(user):
        raise HTTPException(status_code=403, detail="Subscription expired")
    return user


@app.get("/sub/{token}")
async def subscription(token: str):
    user = await _subscription_user(token)

    wifi = get_wifi_lines()
    lte = get_lte_uris()
    if not wifi and not lte:
        raise HTTPException(status_code=503, detail="Configs loading, try again in a minute")

    pool = get_pool_state()
    entries = build_subscription_json(wifi, lte, show_individual=False)
    if not entries:
        raise HTTPException(status_code=503, detail="No valid configs for subscription")

    body = subscription_json_bytes(wifi, lte, show_individual=False)
    profile_title = f"🔐 {config.BOT_NAME}"

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Profile-Update-Interval": "6",
        "Profile-Title": f"base64:{base64.b64encode(profile_title.encode()).decode()}",
        "Subscription-Userinfo": (
            f"upload=0; download=0; total=0; expire={int(time.time()) + 31536000}"
        ),
        "Content-Disposition": f'inline; filename="{config.BOT_NAME}.json"',
        "Cache-Control": "private, max-age=300",
        **HAPP_HEADERS,
        "X-TsuloVPN-Configs": str(len(entries)),
        "X-TsuloVPN-Wifi-Nodes": str(len(wifi)),
        "X-TsuloVPN-Lte-Nodes": str(len(lte)),
        "X-TsuloVPN-Updated": datetime.fromtimestamp(
            pool.last_refresh_at or time.time(),
            tz=timezone.utc,
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    logger.info(
        "JSON subscription user=%s visible=%s WIFI=%s LTE=%s profiles=%s",
        user.telegram_id,
        len(entries),
        len(wifi),
        len(lte),
        [e.get("remarks") for e in entries],
    )
    return Response(content=body, media_type="application/json", headers=headers)


@app.get("/sub/{token}/lte")
async def subscription_lte(token: str):
    user = await _subscription_user(token)

    lte = get_lte_uris()
    if not lte:
        raise HTTPException(status_code=503, detail="LTE configs loading, try again in a minute")

    classic_lines = build_lte_classic_lines(lte)
    body = lte_classic_subscription_bytes(lte)
    if not body:
        raise HTTPException(status_code=503, detail="No valid LTE configs")

    pool = get_pool_state()
    profile_title = f"📱 {config.BOT_NAME} · LTE"

    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "Profile-Update-Interval": "6",
        "Profile-Title": f"base64:{base64.b64encode(profile_title.encode()).decode()}",
        "Subscription-Userinfo": (
            f"upload=0; download=0; total=0; expire={int(time.time()) + 31536000}"
        ),
        "Content-Disposition": f'inline; filename="{config.BOT_NAME}-LTE.txt"',
        "Cache-Control": "private, max-age=300",
        **HAPP_HEADERS,
        "X-TsuloVPN-Lte-Lines": str(len(classic_lines)),
        "X-TsuloVPN-Updated": datetime.fromtimestamp(
            pool.last_refresh_at or time.time(),
            tz=timezone.utc,
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    logger.info(
        "LTE classic subscription user=%s lines=%s hosts=%s",
        user.telegram_id,
        len(classic_lines),
        [line.split("#", 1)[0][-40:] for line in classic_lines[:5]],
    )
    return Response(content=body, media_type="text/plain", headers=headers)
