import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from config import config


class TelegramAuthError(Exception):
    pass


def validate_webapp_init_data(init_data: str, max_age_sec: int = 86400) -> dict:
    """Проверяет подпись Telegram WebApp initData."""
    if not init_data or not config.BOT_TOKEN:
        raise TelegramAuthError("Missing init data or bot token")

    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise TelegramAuthError("Missing hash")

    auth_date = int(parsed.get("auth_date", "0") or "0")
    if auth_date and time.time() - auth_date > max_age_sec:
        raise TelegramAuthError("Init data expired")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(
        b"WebAppData",
        config.BOT_TOKEN.encode(),
        hashlib.sha256,
    ).digest()
    calculated = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calculated, received_hash):
        raise TelegramAuthError("Invalid signature")

    user_raw = parsed.get("user")
    if not user_raw:
        raise TelegramAuthError("Missing user")
    user = json.loads(user_raw)
    if "id" not in user:
        raise TelegramAuthError("Invalid user payload")

    return user
