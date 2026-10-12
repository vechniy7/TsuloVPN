#!/usr/bin/env python3
"""Выставить кнопку «Меню» и команды бота (Amvera не ходит в api.telegram.org).

Пример:
  set BOT_TOKEN=123:ABC
  python scripts/set_bot_menu.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request


def main() -> int:
    token = (os.getenv("BOT_TOKEN") or "").strip()
    if not token:
        print("BOT_TOKEN is required", file=sys.stderr)
        return 1

    commands = [
        {"command": "start", "description": "Меню бота"},
        {"command": "access", "description": "Мой ключ"},
        {"command": "help", "description": "Инструкция"},
        {"command": "tariffs", "description": "Тарифы"},
        {"command": "docs", "description": "Документы"},
    ]

    # setMyCommands
    payload = urllib.parse.urlencode(
        {"commands": json.dumps(commands, ensure_ascii=False)}
    ).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/setMyCommands",
        data=payload,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode())
    print("setMyCommands:", json.dumps(body, ensure_ascii=False, indent=2))

    # MenuButtonCommands — убирает WebApp «Начать»
    payload = urllib.parse.urlencode(
        {"menu_button": json.dumps({"type": "commands"}, ensure_ascii=False)}
    ).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/setChatMenuButton",
        data=payload,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode())
    print("setChatMenuButton:", json.dumps(body, ensure_ascii=False, indent=2))

    with urllib.request.urlopen(
        f"https://api.telegram.org/bot{token}/getChatMenuButton", timeout=30
    ) as resp:
        info = json.loads(resp.read().decode())
    print("getChatMenuButton:", json.dumps(info, ensure_ascii=False, indent=2))

    with urllib.request.urlopen(
        f"https://api.telegram.org/bot{token}/getMyCommands", timeout=30
    ) as resp:
        cmds = json.loads(resp.read().decode())
    print("getMyCommands:", json.dumps(cmds, ensure_ascii=False, indent=2))
    return 0 if body.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
