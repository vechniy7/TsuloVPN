"""Fail Amvera build if config_pool.py is from a bad merge."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POOL = ROOT / "src" / "config_pool.py"
text = POOL.read_text(encoding="utf-8")

errors: list[str] = []
if "POOL_ENGINE_VERSION = 3" not in text:
    errors.append("missing POOL_ENGINE_VERSION = 3")
if "LTE(bypass)" in text:
    errors.append("stale Amvera merge marker LTE(bypass)")
if "all_urls = list(dict.fromkeys(wifi_urls + lte_urls))" not in text:
    errors.append("all_urls must be defined in refresh_pool")
if "private_only = bool(all_urls)" not in text:
    errors.append("private JSON passthrough block missing")

if errors:
    raise SystemExit("Broken config_pool.py:\n- " + "\n- ".join(errors))

print("deploy verify ok: config_pool v3")
