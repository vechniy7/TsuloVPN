import base64
import logging
import time
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Response

from bypass_source import build_personal_subscription_lines
from config import config
from config_pool import get_pool_state, get_working_subscription_lines
from database import get_personal_bypass_uris, get_user_by_token, has_personal_bypass
from miniapp_routes import router as miniapp_router

logger = logging.getLogger(__name__)

app = FastAPI(title="TsuloVPN Subscription Server", docs_url=None, redoc_url=None)
app.include_router(miniapp_router)


def _subscription_response(plain: str, profile_title: str, user_id: int, count: int) -> Response:
    pool = get_pool_state()
    body = base64.b64encode(plain.encode("utf-8")).decode("ascii")
    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "Profile-Update-Interval": "24",
        "Profile-Title": f"base64:{base64.b64encode(profile_title.encode()).decode()}",
        "Subscription-Userinfo": (
            f"upload=0; download=0; total=0; expire={int(time.time()) + 31536000}"
        ),
        "Content-Disposition": f'inline; filename="{config.BOT_NAME}.txt"',
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "X-TsuloVPN-Configs": str(count),
        "X-TsuloVPN-Verified-At": datetime.fromtimestamp(
            pool.last_verify_at or pool.last_refresh_at or time.time(),
            tz=timezone.utc,
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "X-TsuloVPN-Updated": datetime.fromtimestamp(
            pool.last_refresh_at or time.time(),
            tz=timezone.utc,
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    logger.info("Served subscription for user %s (%s configs)", user_id, count)
    return Response(content=body, media_type="text/plain", headers=headers)


@app.get("/health")
async def health():
    pool = get_pool_state()
    return {
        "status": "ok",
        "working_configs": len(pool.configs),
        "last_refresh_at": pool.last_refresh_at,
        "is_refreshing": pool.is_refreshing,
    }


@app.get("/sub/{token}/personal")
async def personal_subscription(token: str):
    user = await get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=404, detail="Subscription not found")

    uris = get_personal_bypass_uris(user)
    if not uris:
        raise HTTPException(
            status_code=404,
            detail="Personal bypass not configured. Use Mini App in bot.",
        )

    lines = build_personal_subscription_lines(uris)
    plain = "\n".join(lines)
    profile_title = f"🔐 {config.BOT_NAME} · Мой обход"
    return _subscription_response(plain, profile_title, user.telegram_id, len(lines))


@app.get("/sub/{token}")
async def subscription(token: str):
    user = await get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=404, detail="Subscription not found")

    if has_personal_bypass(user):
        uris = get_personal_bypass_uris(user)
        lines = build_personal_subscription_lines(uris)
        profile_title = f"🔐 {config.BOT_NAME} · Мой обход"
        plain = "\n".join(lines)
        return _subscription_response(plain, profile_title, user.telegram_id, len(lines))

    lines = await get_working_subscription_lines()
    if not lines:
        raise HTTPException(status_code=503, detail="No working configs available yet")

    plain = "\n".join(lines)
    profile_title = f"🔐 {config.BOT_NAME}"
    return _subscription_response(plain, profile_title, user.telegram_id, len(lines))
