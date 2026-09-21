# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

RDB = Path(r"c:\Users\admin\Desktop\Evelion-2.1.0\TsuloVPN\c03eacef-21d8-47b6-904f-3bc76b4edbe6.rdb")
OUT = Path(r"c:\Users\admin\Desktop\Evelion-2.1.0\TsuloVPN\src\data_migrate\from_rdb.json")


def extract_json_objects(data: bytes, needle: bytes) -> list[dict]:
    results: list[dict] = []
    seen: set[int] = set()
    for m in re.finditer(re.escape(needle), data):
        # walk back to opening brace
        i = m.start()
        while i > 0 and data[i] != 0x7B:
            i -= 1
        if data[i] != 0x7B:
            continue
        if i in seen:
            continue
        depth = 0
        j = i
        in_str = False
        esc = False
        while j < len(data):
            c = data[j]
            if in_str:
                if esc:
                    esc = False
                elif c == 0x5C:  # \
                    esc = True
                elif c == 0x22:  # "
                    in_str = False
            else:
                if c == 0x22:
                    in_str = True
                elif c == 0x7B:
                    depth += 1
                elif c == 0x7D:
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
            j += 1
        raw = data[i:j].decode("utf-8", "replace")
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        seen.add(i)
        results.append(obj)
    return results


def main() -> None:
    data = RDB.read_bytes()
    users = extract_json_objects(data, b'"telegram_id"')
    # users also have subscription_token; orders have order_id + plan_id
    user_objs = []
    order_objs = []
    for obj in users:
        if "subscription_token" in obj and "telegram_id" in obj:
            user_objs.append(obj)
        elif "order_id" in obj and "plan_id" in obj and "telegram_id" in obj:
            order_objs.append(obj)

    # dedupe users by telegram_id
    by_tid: dict[int, dict] = {}
    for u in user_objs:
        try:
            tid = int(u["telegram_id"])
        except (TypeError, ValueError, KeyError):
            continue
        by_tid[tid] = u
    users_final = list(by_tid.values())

    by_oid: dict[str, dict] = {}
    for o in order_objs:
        oid = str(o.get("order_id") or "")
        if oid:
            by_oid[oid] = o
    orders_final = list(by_oid.values())

    print("users", len(users_final), "orders", len(orders_final))
    if users_final:
        u = users_final[0]
        print("sample user", u.get("telegram_id"), u.get("username"), str(u.get("subscription_token"))[:8])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"users": users_final, "orders": orders_final}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("wrote", OUT)


if __name__ == "__main__":
    main()
