"""Проверка схлопывания вложенных str(dict) HWID."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from devices import (  # noqa: E402
    extract_raw_hwid,
    format_device_label,
    friendly_device_name,
    normalize_device_records,
)


def main() -> None:
    junk = [
        {
            "hwid": "e9c0f89528ba159d",
            "last_seen": "2026-10-14T07:41:49.176627+00:00",
            "name": "2407FPN8EG",
            "os": "Android",
        },
        {
            "hwid": (
                "{'hwid': 'e9c0f89528ba159d', "
                "'last_seen': '2026-10-14T06:49:30.661477+00:00', "
                "'name': '2407FPN8EG', 'os': 'Android'}"
            )
        },
        {"hwid": "{'hwid': \"{'hwid': 'e9c0f89528ba159d'}\"}"},
        "{'hwid': 'e9c0f89528ba159d', 'name': '2407FPN8EG', 'os': 'Android'}",
        {
            "hwid": (
                "{'hwid': \"{'hwid': 'e097584350c4fc78', "
                "'last_seen': '2026-10-13T20:03:25.088077+00:00', "
                "'name': 'iPhone 16 Pro Max', 'os': 'iOS'}\"}"
            )
        },
    ]
    # Старый баг: hwids = [str(x) for x in dict_list]
    as_strs = [
        str(
            {
                "hwid": "e9c0f89528ba159d",
                "name": "2407FPN8EG",
                "os": "Android",
            }
        ),
        str(
            {
                "hwid": str({"hwid": "e9c0f89528ba159d", "name": "2407FPN8EG"}),
                "last_seen": "x",
            }
        ),
    ]

    r1 = normalize_device_records(junk)
    r2 = normalize_device_records(as_strs)
    print("junk ->", len(r1), r1)
    print("as_strs ->", len(r2), r2)
    print("labels:", [format_device_label(r, i) for i, r in enumerate(r1)])
    print("friendly:", friendly_device_name("2407FPN8EG", "Android"))
    print("extract:", extract_raw_hwid("{'hwid': 'e9c0f89528ba159d'}"))

    assert len(r1) == 2, r1
    assert {r["hwid"] for r in r1} == {"e9c0f89528ba159d", "e097584350c4fc78"}
    assert format_device_label(r1[0], 0) == "Xiaomi 14T Pro"
    assert any(format_device_label(r, i) == "iPhone 16 Pro Max" for i, r in enumerate(r1))
    assert len(r2) == 1
    assert r2[0]["hwid"] == "e9c0f89528ba159d"
    print("OK")


if __name__ == "__main__":
    main()
