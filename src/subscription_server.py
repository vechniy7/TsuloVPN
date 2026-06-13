import base64
import logging
import time
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Response

from config import config
from config_pool import get_pool_state, get_subscription_lines
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
        "source_total": pool.source_total,
        "subscription_count": pool.subscription_count,
        "last_refresh_at": pool.last_refresh_at,
        "is_refreshing": pool.is_refreshing,
        "source": config.CONFIG_SOURCE_URL.split("/")[-1],
    }


@app.get("/sub/{token}")
async def subscription(token: str):
    user = await get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=404, detail="Subscription not found")

    lines = get_subscription_lines()
    if not lines:
        raise HTTPException(status_code=503, detail="Configs loading, try again in a minute")

    pool = get_pool_state()
    plain = "\n".join(lines)
    body = base64.b64encode(plain.encode("utf-8")).decode("ascii")
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
        "X-TsuloVPN-Configs": str(len(lines)),
        "X-TsuloVPN-Source-Total": str(pool.source_total),
        "X-TsuloVPN-Updated": datetime.fromtimestamp(
            pool.last_refresh_at or time.time(),
            tz=timezone.utc,
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    logger.info("Subscription for user %s: %s configs", user.telegram_id, len(lines))
    return Response(content=body, media_type="text/plain", headers=headers)
