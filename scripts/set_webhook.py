#!/usr/bin/env python3
"""Зарегистрировать Telegram webhook с машины, где доступен api.telegram.org.

Пример:
  set BOT_TOKEN=123:ABC
  set SUBSCRIPTION_PUBLIC_URL=https://tsulovpn-culoebali.amvera.io
  python scripts/set_webhook.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request


def main() -> int:
    token = (os.getenv("BOT_TOKEN") or "").strip()
    base = (os.getenv("SUBSCRIPTION_PUBLIC_URL") or "https://tsulovpn-culoebali.amvera.io").rstrip(
        "/"
    )
    path = (os.getenv("TELEGRAM_WEBHOOK_PATH") or "/telegram/webhook").strip()
    if not path.startswith("/"):
        path = f"/{path}"
    webhook_url = f"{base}{path}"
    secret = (os.getenv("TELEGRAM_WEBHOOK_SECRET") or "").strip()

    if not token:
        print("BOT_TOKEN is required", file=sys.stderr)
        return 1

    payload = {
        "url": webhook_url,
        "drop_pending_updates": "true",
        "allowed_updates": json.dumps(["message", "callback_query"]),
    }
    if secret:
        payload["secret_token"] = secret

    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/setWebhook",
        data=data,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode())
    print("setWebhook:", json.dumps(body, ensure_ascii=False, indent=2))

    with urllib.request.urlopen(
        f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=30
    ) as resp:
        info = json.loads(resp.read().decode())
    print("getWebhookInfo:", json.dumps(info, ensure_ascii=False, indent=2))
    return 0 if body.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
