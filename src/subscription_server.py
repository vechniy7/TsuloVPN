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
from parser import brand_config
from payments import is_subscription_active

logger = logging.getLogger(__name__)

app = FastAPI(title="TsuloVPN Subscription Server", docs_url=None, redoc_url=None)
app.include_router(miniapp_router)
app.include_router(cardlink_router)

HAPP_BODY_DIRECTIVES = (
    "#hide-settings: 1",
    "#subscription-autoconnect: 1",
    "#subscription-autoconnect-type: lowestdelay",
    "#subscription-ping-onopen-enabled: 1",
    "#ping-type: tcp",
    "#subscriptions-sort-type: ping",
    "#check-url-via-proxy: https://www.gstatic.com/generate_204",
    "#fragmentation-enable: 0",
)


def _build_subscription_plain(lines: list[str]) -> str:
    """45 working servers + leading АВТО-ВЫБОР (copy of first URI)."""
    out_lines = list(HAPP_BODY_DIRECTIVES)
    if lines:
        auto_uri = brand_config(lines[0], f"⚡ {config.BOT_NAME} · АВТО-ВЫБОР")
        out_lines.append(auto_uri)
    out_lines.extend(lines)
    return "\n".join(out_lines)


@app.get("/health")
async def health():
    pool = get_pool_state()
    return {
        "status": "ok",
        "source_total": pool.source_total,
        "primary_count": pool.primary_count,
        "fill_count": pool.fill_count,
        "subscription_count": pool.subscription_count,
        "limit": config.SUBSCRIPTION_CONFIG_LIMIT,
        "last_refresh_at": pool.last_refresh_at,
        "is_refreshing": pool.is_refreshing,
        "source": config.CONFIG_SOURCE_URL.split("/")[-1],
        "fill_source": config.CONFIG_FILL_SOURCE_URL.split("/")[-1],
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
    plain = _build_subscription_plain(lines)
    body = base64.b64encode(plain.encode("utf-8")).decode("ascii")
    profile_title = f"🔐 {config.BOT_NAME}"
    served = len(lines) + 1  # + АВТО-ВЫБОР

    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "Profile-Update-Interval": "1",
        "Profile-Title": f"base64:{base64.b64encode(profile_title.encode()).decode()}",
        "Subscription-Userinfo": (
            f"upload=0; download=0; total=0; expire={int(time.time()) + 31536000}"
        ),
        "Content-Disposition": f'inline; filename="{config.BOT_NAME}.txt"',
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "hide-settings": "1",
        "subscription-autoconnect": "1",
        "subscription-autoconnect-type": "lowestdelay",
        "subscription-ping-onopen-enabled": "1",
        "ping-type": "tcp",
        "subscriptions-sort-type": "ping",
        "check-url-via-proxy": "https://www.gstatic.com/generate_204",
        "fragmentation-enable": "0",
        "X-TsuloVPN-Configs": str(served),
        "X-TsuloVPN-Source-Total": str(pool.source_total),
        "X-TsuloVPN-Updated": datetime.fromtimestamp(
            pool.last_refresh_at or time.time(),
            tz=timezone.utc,
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    logger.info(
        "Subscription for user %s: %s configs (+auto)",
        user.telegram_id,
        len(lines),
    )
    return Response(content=body, media_type="text/plain", headers=headers)
