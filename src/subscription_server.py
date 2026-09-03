import base64
import json
import logging
import time

from fastapi import FastAPI, HTTPException, Response

from config import config
from pool_engine_v3 import get_happ_json_profiles, get_pool_state
from database import get_user_by_token, touch_subscription_fetch
from legal_docs import privacy_html, tariffs_html, terms_html
from miniapp_routes import router as miniapp_router
from cardlink_routes import router as cardlink_router
from platega_routes import router as platega_router
from panel_routes import router as panel_router
from payments import is_subscription_active

logger = logging.getLogger(__name__)

app = FastAPI(title="TsuloVPN Subscription Server", docs_url=None, redoc_url=None)
app.include_router(miniapp_router)
app.include_router(cardlink_router)
app.include_router(platega_router)
app.include_router(panel_router)


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
  <p class="meta">VPN-доступ</p>
  <h1>{name}</h1>
  <p class="meta">Telegram-бот · тарифы, ключ для Happ и поддержка</p>
</section>
<section class="card">
  <h2>Документы сервиса</h2>
  <ul>
    <li><a href="/tariffs">Тарифы и цены</a></li>
    <li><a href="/privacy">Политика конфиденциальности</a></li>
    <li><a href="/terms">Пользовательское соглашение</a></li>
    <li><a href="{config.SUPPORT_URL}">Поддержка</a></li>
  </ul>
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


def _pay_channel() -> str:
    ch = (config.required_channel_id or config.BOT_NAME or "TsuloVPN").lstrip("@").strip()
    return ch or "TsuloVPN"


def _payment_notice_profiles(*, reason: str) -> list[dict]:
    """
    Заглушка вместо серверов: Happ ОБЯЗАН получить HTTP 200 и заменить список.
    При 403/404 клиент часто оставляет старые рабочие конфиги в кэше.
    """
    channel = _pay_channel()
    if reason == "disabled":
        title = f"⛔ Доступ закрыт · @{channel}"
        desc = f"Ключ отключён. Напишите в поддержку или откройте бота @{channel}"
    elif reason == "not_found":
        title = f"🔑 Ключ недействителен · @{channel}"
        desc = f"Ключ удалён или заменён. Получите новый в боте @{channel}"
    else:
        title = f"⚠️ Оплатите @{channel}"
        desc = f"Подписка неактивна. Оформите оплату в боте / канале @{channel}"

    # Нерабочий outbound: в списке Happ виден только текст, подключиться нельзя.
    return [
        {
            "remarks": title,
            "meta": {
                "serverDescription": base64.b64encode(desc.encode("utf-8")).decode("ascii"),
            },
            "log": {"loglevel": "warning"},
            "inbounds": [],
            "outbounds": [
                {
                    "tag": "proxy",
                    "protocol": "blackhole",
                    "settings": {"response": {"type": "none"}},
                },
                {"tag": "direct", "protocol": "freedom", "settings": {}},
                {"tag": "block", "protocol": "blackhole", "settings": {}},
            ],
            "routing": {
                "domainStrategy": "AsIs",
                "rules": [
                    {"type": "field", "network": "tcp,udp", "outboundTag": "block"},
                ],
            },
        }
    ]


def _subscription_response(
    profiles: list[dict],
    *,
    profile_title: str,
    expire_ts: int,
    cache_max_age: int,
    update_interval: str,
) -> Response:
    body = json.dumps(profiles, ensure_ascii=False, separators=(",", ":"))
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Profile-Update-Interval": update_interval,
        "Profile-Title": f"base64:{base64.b64encode(profile_title.encode()).decode()}",
        "Subscription-Userinfo": f"upload=0; download=0; total=0; expire={expire_ts}",
        "Content-Disposition": f'inline; filename="{config.BOT_NAME}.json"',
        "Cache-Control": f"private, max-age={cache_max_age}",
        **HAPP_HEADERS,
    }
    return Response(content=body, media_type="application/json; charset=utf-8", headers=headers)


def _parse_expire_ts(user) -> int:
    if user and user.expires_at:
        try:
            from datetime import datetime, timezone

            exp = datetime.fromisoformat(user.expires_at)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            return int(exp.timestamp())
        except ValueError:
            pass
    return int(time.time()) + 31536000


async def _subscription_access(token: str) -> tuple[object | None, str | None]:
    """Возвращает (user, reason). reason=None — доступ разрешён."""
    user = await get_user_by_token(token)
    if not user:
        return None, "not_found"
    if getattr(user, "disabled", False):
        return user, "disabled"
    if user.is_admin:
        return user, None
    if config.payments_active and not is_subscription_active(user):
        return user, "expired"
    return user, None


@app.get("/sub/{token}")
async def subscription(token: str):
    user, reason = await _subscription_access(token)

    if reason:
        # Важно: HTTP 200 + одна «оплата»-запись, иначе Happ оставит старые сервера.
        channel = _pay_channel()
        profiles = _payment_notice_profiles(reason=reason)
        if user is not None:
            try:
                await touch_subscription_fetch(user.telegram_id)
            except Exception as exc:
                logger.warning("touch_subscription_fetch failed: %s", exc)
        logger.info(
            "JSON subscription blocked token=%s… reason=%s user=%s",
            (token or "")[:8],
            reason,
            getattr(user, "telegram_id", None),
        )
        return _subscription_response(
            profiles,
            profile_title=f"⚠️ Оплатите @{channel}",
            expire_ts=int(time.time()) - 60,
            cache_max_age=60,
            update_interval="1",
        )

    profiles = get_happ_json_profiles()
    if not profiles:
        raise HTTPException(status_code=503, detail="Configs loading, try again in a minute")

    try:
        await touch_subscription_fetch(user.telegram_id)
    except Exception as exc:
        logger.warning("touch_subscription_fetch failed: %s", exc)

    logger.info(
        "JSON subscription user=%s configs=%s",
        user.telegram_id,
        len(profiles),
    )
    return _subscription_response(
        profiles,
        profile_title=f"🔮 {config.BOT_NAME}",
        expire_ts=_parse_expire_ts(user),
        cache_max_age=300,
        update_interval="12",
    )


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
        user, reason = await _subscription_access(token)
        if reason:
            raise HTTPException(status_code=403, detail=f"Subscription {reason}")
        if not user:
            raise HTTPException(status_code=404, detail="Subscription not found")

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
