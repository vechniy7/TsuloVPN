import base64
import json
import logging
import time

from fastapi import FastAPI, HTTPException, Response

from config import config
from pool_engine_v3 import get_happ_json_profiles, get_pool_state
from database import get_user_by_token
from miniapp_routes import router as miniapp_router
from cardlink_routes import router as cardlink_router
from payments import is_subscription_active

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
    overall = pool.source_status if pool.subscription_count else "failed"
    if pool.source_status == "degraded" and pool.subscription_count:
        overall = "degraded"
    payload = {
        "status": overall,
        "source_status": pool.source_status,
        "source_real_configs": pool.source_real_count,
        "visible_configs": pool.subscription_count,
        "last_refresh_at": pool.last_refresh_at,
        "is_refreshing": pool.is_refreshing,
        "last_error": pool.last_error,
        "format": "happ-xray-json",
    }
    if config.HEALTH_PUBLIC_DETAILS:
        payload.update(
            {
                "source_key": config.source_label(),
                "last_fetch_status": pool.last_fetch_status,
                "consecutive_fetch_failures": pool.consecutive_fetch_failures,
                "wifi_count": pool.wifi_count,
                "lte_count": pool.lte_count,
                "wifi_sources": pool.wifi_source_counts,
                "lte_sources": pool.lte_source_counts,
                "limit_per_profile": config.SUBSCRIPTION_CONFIG_LIMIT,
                "wifi_urls": [_source_name(u) for u in config.wifi_source_urls()],
                "lte_urls": [_source_name(u) for u in config.lte_source_urls()],
                "subscription_count": pool.subscription_count,
                "source_counts": pool.source_counts,
            }
        )
    return payload


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

    profiles = get_happ_json_profiles()
    if not profiles:
        raise HTTPException(status_code=503, detail="Configs loading, try again in a minute")

    body = json.dumps(profiles, ensure_ascii=False, separators=(",", ":"))
    profile_title = f"🔮 {config.BOT_NAME}"

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Profile-Update-Interval": "12",
        "Profile-Title": f"base64:{base64.b64encode(profile_title.encode()).decode()}",
        "Subscription-Userinfo": (
            f"upload=0; download=0; total=0; expire={int(time.time()) + 31536000}"
        ),
        "Content-Disposition": f'inline; filename="{config.BOT_NAME}.json"',
        "Cache-Control": "private, max-age=600",
        **HAPP_HEADERS,
    }

    logger.info(
        "JSON subscription user=%s configs=%s",
        user.telegram_id,
        len(profiles),
    )
    return Response(content=body, media_type="application/json; charset=utf-8", headers=headers)
