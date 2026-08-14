"""Проверка Telegram Mini App initData."""

from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from config import config


def parse_webapp_user(init_data: str) -> dict | None:
    if not init_data or not config.BOT_TOKEN:
        return None

    pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    received = pairs.pop("hash", "")
    if not received:
        return None

    data_check = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received):
        return None

    try:
        user = json.loads(pairs.get("user") or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(user, dict) or "id" not in user:
        return None
    return user
