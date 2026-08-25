import base64
import json
import logging
import time

from fastapi import FastAPI, HTTPException, Response

from config import config
from pool_engine_v3 import get_happ_json_profiles, get_pool_state
from database import get_user_by_token
from legal_docs import BANK_MARKER, privacy_html, tariffs_html, terms_html
from miniapp_routes import router as miniapp_router
from cardlink_routes import router as cardlink_router
from payments import is_subscription_active

logger = logging.getLogger(__name__)

app = FastAPI(title="TsuloVPN Subscription Server", docs_url=None, redoc_url=None)
app.include_router(miniapp_router)
app.include_router(cardlink_router)


@app.get("/privacy")
async def privacy_page():
    return Response(content=privacy_html(), media_type="text/html; charset=utf-8")


@app.get("/terms")
async def terms_page():
    return Response(content=terms_html(), media_type="text/html; charset=utf-8")


@app.get("/tariffs")
async def tariffs_page():
    return Response(content=tariffs_html(), media_type="text/html; charset=utf-8")


@app.get("/")
async def root_docs_index():
    """Витрина документов для проверки банком / менеджером."""
    name = config.BOT_NAME or "TsuloVPN"
    from legal_docs import _shell

    body = f"""
<section class="hero">
  <p class="meta">цифровой сервис доступа</p>
  <h1>{name}</h1>
  <p class="meta">Telegram-бот · тарифы, документы и поддержка в одном месте</p>
</section>
<section class="card">
  <h2>Документы сервиса</h2>
  <ul>
    <li><a href="/tariffs">Тарифы и цены</a></li>
    <li><a href="/privacy">Политика конфиденциальности</a></li>
    <li><a href="/terms">Пользовательское соглашение</a></li>
    <li><a href="{config.SUPPORT_URL}">Поддержка</a></li>
  </ul>
  <p style="margin-top:14px">Код согласования: <span class="marker">{BANK_MARKER}</span></p>
</section>
"""
    return Response(content=_shell(name, body), media_type="text/html; charset=utf-8")


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
                "bypass_source_key": config.bypass_source_label() or None,
                "bypass_source_key_2": config.bypass_source_label_2() or None,
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


def _ikev2_token_allowed(token: str) -> bool:
    """App catalog token or any valid user subscription token."""
    app_token = (config.IKEV2_APP_TOKEN or "").strip()
    if app_token and token.strip() == app_token:
        return True
    return False


@app.get("/ikev2/{token}")
async def ikev2_catalog(token: str):
    """
    IKEv2 gateway catalog for the Tsulo iOS app (Personal VPN).
    Amvera only serves this JSON — the actual VPN daemon runs on a separate VPS.
    """
    if not _ikev2_token_allowed(token):
        # Fall back to normal user token check (same as /sub/)
        await _subscription_user(token)

    gateways = config.ikev2_gateways()
    if not gateways:
        raise HTTPException(
            status_code=503,
            detail=(
                "IKEv2 gateways not configured. "
                "Set IKEV2_SERVER + IKEV2_PASSWORD (or IKEV2_GATEWAYS_JSON) in Amvera env."
            ),
        )

    body = json.dumps(gateways, ensure_ascii=False, separators=(",", ":"))
    logger.info("IKEv2 catalog token=%s… gateways=%s", token[:8], len(gateways))
    return Response(
        content=body,
        media_type="application/json; charset=utf-8",
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": 'inline; filename="tsulo-ikev2.json"',
        },
    )
