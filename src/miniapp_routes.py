import logging
import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from config import config
from database import get_user
from happ_crypto import bot_subscription_import_url
from webapp_auth import parse_webapp_user

logger = logging.getLogger(__name__)

router = APIRouter()
_STATIC_DIR = Path(__file__).parent / "miniapp" / "static"
_PHOTO_DIR = Path(__file__).parent / "photo"
_NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
}


def _safe_file(root: Path, filename: str) -> Path | None:
    if not filename or "/" in filename or "\\" in filename:
        return None
    path = (root / filename).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None
    return path if path.is_file() else None


class AccessRequest(BaseModel):
    initData: str = ""


@router.get("/miniapp/", include_in_schema=False)
@router.get("/miniapp", include_in_schema=False)
async def miniapp_index():
    index = _STATIC_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Mini app not found")
    return FileResponse(
        index,
        media_type="text/html; charset=utf-8",
        headers=_NO_CACHE,
    )


@router.get("/miniapp/static/{filename}", include_in_schema=False)
async def miniapp_static(filename: str):
    path = _safe_file(_STATIC_DIR, filename)
    if not path:
        raise HTTPException(status_code=404)
    media, _ = mimetypes.guess_type(path.name.lower())
    return FileResponse(
        path,
        media_type=media or "application/octet-stream",
        headers=_NO_CACHE,
    )


@router.get("/miniapp/media/{filename}", include_in_schema=False)
async def miniapp_media(filename: str):
    # Баннеры отключены — не отдаём старые изображения из photo/
    raise HTTPException(status_code=404, detail="Media disabled")


@router.post("/miniapp/api/access", include_in_schema=False)
async def miniapp_access(body: AccessRequest):
    tg_user = parse_webapp_user(body.initData)
    if not tg_user:
        return JSONResponse({"ok": False, "error": "open_in_telegram"}, status_code=401)

    user = await get_user(int(tg_user["id"]))
    if not user:
        return JSONResponse({"ok": False, "error": "start_bot"}, status_code=404)

    sub_url = config.subscription_url_for_token(user.subscription_token)
    import_url = await bot_subscription_import_url(sub_url)
    return JSONResponse(
        {
            "ok": True,
            "url": import_url,
            "name": config.BOT_NAME,
            "support": config.SUPPORT_URL,
        },
        headers=_NO_CACHE,
    )


@router.get("/miniapp/api/meta", include_in_schema=False)
async def miniapp_meta():
    return JSONResponse(
        {
            "name": config.BOT_NAME,
            "support": config.SUPPORT_URL,
        },
        headers=_NO_CACHE,
    )
