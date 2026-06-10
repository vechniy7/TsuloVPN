import base64
import logging
import time
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Response

from config import config
from config_pool import get_pool_state, get_subscription_body
from database import get_user_by_token
from miniapp_routes import router as miniapp_router

logger = logging.getLogger(__name__)

app = FastAPI(title="TsuloVPN Subscription Server", docs_url=None, redoc_url=None)
app.include_router(miniapp_router)


@app.get("/health")
async def health():
    pool = get_pool_state()
    return {
        "status": "ok",
        "configs": pool.regular_count + pool.whitelist_count,
        "regular": pool.regular_count,
        "whitelist": pool.whitelist_count,
        "last_refresh_at": pool.last_refresh_at,
        "is_refreshing": pool.is_refreshing,
    }


@app.get("/sub/{token}")
async def subscription(token: str):
    user = await get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=404, detail="Subscription not found")

    body = get_subscription_body()
    if not body:
        raise HTTPException(status_code=503, detail="Configs loading, try again in a minute")

    pool = get_pool_state()
    config_count = pool.regular_count + pool.whitelist_count
    profile_title = f"🔐 {config.BOT_NAME}"

    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "Profile-Update-Interval": "1",
        "Profile-Title": f"base64:{base64.b64encode(profile_title.encode()).decode()}",
        "Subscription-Userinfo": (
            f"upload=0; download=0; total=0; expire={int(time.time()) + 31536000}"
        ),
        "Content-Disposition": f'inline; filename="{config.BOT_NAME}.txt"',
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "X-TsuloVPN-Configs": str(config_count),
        "X-TsuloVPN-Regular": str(pool.regular_count),
        "X-TsuloVPN-Whitelist": str(pool.whitelist_count),
        "X-TsuloVPN-Updated": datetime.fromtimestamp(
            pool.last_refresh_at or time.time(),
            tz=timezone.utc,
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    logger.info("Subscription for user %s: %s configs", user.telegram_id, config_count)
    return Response(content=body, media_type="text/plain", headers=headers)
