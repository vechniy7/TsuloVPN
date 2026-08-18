"""Проверка источника конфигов без Redis и Telegram."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from config import config, requires_happ_hwid  # noqa: E402
from pool_engine_v3 import _fetch_headers_for_url, _fetch_url  # noqa: E402


async def main() -> int:
    source = config.resolved_source_url()
    if not source:
        print("FAIL: VPN_SOURCE_URL is not set")
        return 1

    print(f"source={source}")
    print(f"happ_hwid={requires_happ_hwid(source)}")
    print(f"device={config.SUB_DEVICE_OS} {config.SUB_DEVICE_OS_VER} / {config.SUB_DEVICE_MODEL}")
    print(f"headers={_fetch_headers_for_url(source)}")

    label, text, uris = await _fetch_url(source)
    if text is None:
        print(f"FAIL: fetch failed for {label}")
        return 1

    if not uris:
        print("FAIL: source returned zero configs (check HWID slot / key validity)")
        return 1

    stub_hosts = ("127.0.0.1", "0.0.0.0", "localhost")
    real = [u for u in uris if not any(h in u for h in stub_hosts)]
    if not real:
        print("FAIL: only HWID placeholder stubs — register device in panel or free HWID slot")
        return 1

    print(f"real_configs={len(real)}")

    print("OK: source is reachable and returns configs")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
