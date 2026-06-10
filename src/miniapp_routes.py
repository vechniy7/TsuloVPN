import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter()
_STATIC_DIR = Path(__file__).parent / "miniapp" / "static"


@router.get("/miniapp/", include_in_schema=False)
@router.get("/miniapp", include_in_schema=False)
async def miniapp_index():
    index = _STATIC_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Mini app not found")
    return FileResponse(index, media_type="text/html")


@router.get("/miniapp/static/{filename}", include_in_schema=False)
async def miniapp_static(filename: str):
    path = _STATIC_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404)
    media = "text/css" if filename.endswith(".css") else "application/javascript"
    return FileResponse(path, media_type=media)
