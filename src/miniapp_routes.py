import logging
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from bypass_source import fetch_bypass_config_uris, get_probe_targets
from config import config
from database import get_user, save_personal_bypass
from telegram_auth import TelegramAuthError, validate_webapp_init_data

logger = logging.getLogger(__name__)

router = APIRouter()

_STATIC_DIR = Path(__file__).parent / "miniapp" / "static"


class SaveConfigItem(BaseModel):
    id: int
    uri: str
    ms: int = Field(ge=0, le=60000)


class SaveRequest(BaseModel):
    configs: list[SaveConfigItem]


async def _auth_user(init_data: str | None):
    if not init_data:
        raise HTTPException(status_code=401, detail="Требуется авторизация Telegram")
    try:
        tg_user = validate_webapp_init_data(init_data)
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user = await get_user(int(tg_user["id"]))
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден. Нажмите /start в боте")
    return user, tg_user


@router.get("/miniapp/", response_class=HTMLResponse)
@router.get("/miniapp", response_class=HTMLResponse)
async def miniapp_index():
    index = _STATIC_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Mini app not found")
    return FileResponse(index, media_type="text/html")


@router.get("/miniapp/static/{filename}")
async def miniapp_static(filename: str):
    path = _STATIC_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404)
    media = "text/css" if filename.endswith(".css") else "application/javascript"
    return FileResponse(path, media_type=media)


@router.get("/miniapp/api/configs")
async def miniapp_configs(
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
):
    user, _tg = await _auth_user(x_telegram_init_data)
    targets = await get_probe_targets()
    return {
        "target": config.PERSONAL_BYPASS_TARGET,
        "total": len(targets),
        "timeout_ms": config.MINIAPP_PROBE_TIMEOUT_MS,
        "concurrency": config.MINIAPP_PROBE_CONCURRENCY,
        "targets": targets,
        "user_id": user.telegram_id,
    }


@router.post("/miniapp/api/save")
async def miniapp_save(
    body: SaveRequest,
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
):
    user, _tg = await _auth_user(x_telegram_init_data)

    if not body.configs:
        raise HTTPException(status_code=400, detail="Нет рабочих конфигов")

    allowed_uris = await fetch_bypass_config_uris()
    allowed_set = set(allowed_uris)

    uris: list[str] = []
    latencies: list[int] = []
    seen: set[str] = set()

    for item in body.configs[: config.PERSONAL_BYPASS_TARGET]:
        if item.uri not in allowed_set:
            logger.warning("Rejected unknown URI from user %s", user.telegram_id)
            continue
        if item.uri in seen:
            continue
        seen.add(item.uri)
        uris.append(item.uri)
        latencies.append(item.ms)

    if not uris:
        raise HTTPException(status_code=400, detail="Ни один конфиг не прошёл проверку")

    await save_personal_bypass(user.telegram_id, uris, latencies)

    return {
        "ok": True,
        "count": len(uris),
        "subscription_url": config.personal_subscription_url_for_token(user.subscription_token),
    }
