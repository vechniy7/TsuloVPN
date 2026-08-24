"""Fail Amvera build if pool engine or entrypoints are from a bad merge."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "src" / "pool_engine_v3.py"
APP = ROOT / "src" / "app.py"
LEGACY = ROOT / "src" / "config_pool.py"

engine = ENGINE.read_text(encoding="utf-8")
app = APP.read_text(encoding="utf-8")
legacy = LEGACY.read_text(encoding="utf-8")

errors: list[str] = []
if "POOL_ENGINE_VERSION = 4" not in engine:
    errors.append("pool_engine_v3 missing POOL_ENGINE_VERSION = 4")
if "LTE(bypass)" in engine:
    errors.append("stale merge marker LTE(bypass) in pool_engine_v3")
if "async def refresh_pool" not in engine:
    errors.append("refresh_pool missing in pool_engine_v3")
if "pool_engine_v3: main=" not in engine:
    errors.append("pool_engine_v3 log marker missing")
if "from pool_engine_v3 import" not in app:
    errors.append("app.py must import pool_engine_v3 directly")
if len(legacy.splitlines()) > 5:
    errors.append("config_pool.py must stay a short shim")

if errors:
    raise SystemExit("Broken deploy:\n- " + "\n- ".join(errors))

print("deploy verify ok: pool_engine_v3")
