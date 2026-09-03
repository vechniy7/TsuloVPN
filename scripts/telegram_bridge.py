#!/usr/bin/env python3
"""Мост Telegram <-> Amvera.

Amvera не принимает webhook от Telegram (Connection timed out),
и сама не ходит в api.telegram.org. Этот скрипт на ПК/VPS:

1) long polling getUpdates (есть доступ к Telegram)
2) шлёт апдейт на Amvera /telegram/webhook
3) выполняет method из ответа (sendMessage и т.п.) через Telegram API

Запуск:
  set BOT_TOKEN=...
  set AMVERA_WEBHOOK=https://tsulovpn-culoebali.amvera.io/telegram/webhook
  python scripts/telegram_bridge.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
AMVERA_WEBHOOK = (
    os.getenv("AMVERA_WEBHOOK")
    or "https://tsulovpn-culoebali.amvera.io/telegram/webhook"
).rstrip("/")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def http_json(url: str, payload: dict | None = None, timeout: int = 60) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_form(url: str, fields: dict, timeout: int = 60) -> dict:
    data = urllib.parse.urlencode({k: v for k, v in fields.items() if v is not None}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def delete_webhook() -> None:
    r = http_form(f"{API}/deleteWebhook", {"drop_pending_updates": "false"})
    print("deleteWebhook:", r.get("description") or r, flush=True)


def get_updates(offset: int | None) -> list[dict]:
    fields: dict = {"timeout": "25", "allowed_updates": json.dumps(["message", "callback_query"])}
    if offset is not None:
        fields["offset"] = str(offset)
    try:
        r = http_form(f"{API}/getUpdates", fields, timeout=35)
    except Exception as exc:
        print("getUpdates error:", exc, flush=True)
        time.sleep(2)
        return []
    if not r.get("ok"):
        print("getUpdates not ok:", r, flush=True)
        time.sleep(2)
        return []
    return list(r.get("result") or [])


def forward_to_amvera(update: dict) -> dict | None:
    try:
        return http_json(AMVERA_WEBHOOK, update, timeout=20)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        print(f"Amvera HTTP {exc.code}: {body}", flush=True)
        return None
    except Exception as exc:
        print("Amvera error:", exc, flush=True)
        return None


def execute_method(body: dict) -> None:
    method = body.get("method")
    if not method:
        print("no method in Amvera response:", list(body.keys())[:8], flush=True)
        return
    payload = {k: v for k, v in body.items() if k != "method"}
    # reply_markup и др. сложные поля — JSON-строкой для form API
    for key in ("reply_markup", "entities", "caption_entities", "link_preview_options"):
        if key in payload and not isinstance(payload[key], str):
            payload[key] = json.dumps(payload[key], ensure_ascii=False)
    try:
        r = http_json(f"{API}/{method}", payload, timeout=30)
        if r.get("ok"):
            print(f"OK {method}", flush=True)
        else:
            print(f"FAIL {method}:", r, flush=True)
    except Exception as exc:
        print(f"execute {method} error:", exc, flush=True)


def main() -> int:
    if not BOT_TOKEN:
        print("BOT_TOKEN required", file=sys.stderr)
        return 1
    print("Bridge start ->", AMVERA_WEBHOOK, flush=True)
    delete_webhook()
    offset: int | None = None
    while True:
        updates = get_updates(offset)
        for upd in updates:
            uid = int(upd["update_id"])
            offset = uid + 1
            kind = "callback" if upd.get("callback_query") else "message"
            text = ""
            if upd.get("message"):
                text = (upd["message"].get("text") or "")[:40]
            elif upd.get("callback_query"):
                text = (upd["callback_query"].get("data") or "")[:40]
            print(f"update {uid} {kind}:{text}", flush=True)
            reply = forward_to_amvera(upd)
            if reply:
                execute_method(reply)
        if not updates:
            # long poll already waited; tiny pause to avoid tight loop on errors
            time.sleep(0.2)


if __name__ == "__main__":
    raise SystemExit(main())
