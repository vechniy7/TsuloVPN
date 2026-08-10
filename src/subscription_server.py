import base64
import logging
import time
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Response

from config import config
from config_pool import get_pool_state, get_subscription_lines
from database import get_user_by_token
from miniapp_routes import router as miniapp_router
from cardlink_routes import router as cardlink_router
from payments import is_subscription_active
from xray_builder import build_subscription_json, subscription_json_bytes

logger = logging.getLogger(__name__)

app = FastAPI(title="TsuloVPN Subscription Server", docs_url=None, redoc_url=None)
app.include_router(miniapp_router)
app.include_router(cardlink_router)

# Happ app-management headers (JSON subscriptions use headers, not # body comments)
HAPP_HEADERS = {
    "hide-settings": "1",
    "subscription-autoconnect": "1",
    "subscription-autoconnect-type": "lowestdelay",
    "subscription-ping-onopen-enabled": "1",
    "ping-type": "tcp",
    "subscriptions-sort-type": "ping",
    "check-url-via-proxy": "https://www.gstatic.com/generate_204",
    "fragmentation-enable": "0",
}


def _source_name(url: str) -> str:
    return url.rstrip("/").split("/")[-1] or url


@app.get("/health")
async def health():
    pool = get_pool_state()
    sources = config.config_source_urls()
    return {
        "status": "ok",
        "source_total": pool.source_total,
        "primary_count": pool.primary_count,
        "fill_count": pool.fill_count,
        "source_counts": pool.source_counts,
        "subscription_count": pool.subscription_count,
        "limit": config.SUBSCRIPTION_CONFIG_LIMIT,
        "show_individual": False,
        "last_refresh_at": pool.last_refresh_at,
        "is_refreshing": pool.is_refreshing,
        "sources": [_source_name(u) for u in sources],
        "auto_select": "xray-leastPing",
        "visible_profiles": 1,
    }


@app.get("/sub/{token}")
async def subscription(token: str):
    user = await get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=404, detail="Subscription not found")

    if config.payments_active and not user.is_admin and not is_subscription_active(user):
        raise HTTPException(status_code=403, detail="Subscription expired")

    lines = get_subscription_lines()
    if not lines:
        raise HTTPException(status_code=503, detail="Configs loading, try again in a minute")

    pool = get_pool_state()
    # Always hide individual servers for clients — only АВТО-ВЫБОР
    entries = build_subscription_json(lines, show_individual=False)
    if not entries:
        raise HTTPException(status_code=503, detail="No valid configs for subscription")

    body = subscription_json_bytes(lines, show_individual=False)
    profile_title = f"🔐 {config.BOT_NAME}"

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Profile-Update-Interval": "1",
        "Profile-Title": f"base64:{base64.b64encode(profile_title.encode()).decode()}",
        "Subscription-Userinfo": (
            f"upload=0; download=0; total=0; expire={int(time.time()) + 31536000}"
        ),
        "Content-Disposition": f'inline; filename="{config.BOT_NAME}.json"',
        "Cache-Control": "no-cache, no-store, must-revalidate",
        **HAPP_HEADERS,
        "X-TsuloVPN-Configs": str(len(entries)),
        "X-TsuloVPN-Nodes": str(len(lines)),
        "X-TsuloVPN-Source-Total": str(pool.source_total),
        "X-TsuloVPN-Updated": datetime.fromtimestamp(
            pool.last_refresh_at or time.time(),
            tz=timezone.utc,
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    logger.info(
        "JSON subscription for user %s: %s visible, %s nodes in АВТО (%s)",
        user.telegram_id,
        len(entries),
        len(lines),
        entries[0].get("remarks") if entries else None,
    )
    return Response(content=body, media_type="application/json", headers=headers)
