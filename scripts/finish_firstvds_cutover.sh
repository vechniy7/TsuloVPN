#!/bin/bash
# Finish Amvera → FirstVDS cutover on the VPS.
set -euo pipefail

ROOT=/opt/tsulovpn
DB_DIR=/var/lib/tsulovpn

echo "==> git pull"
cd "$ROOT"
git fetch origin
git reset --hard origin/main

echo "==> venv / deps"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -r requirements.txt

echo "==> ensure .env (PORT 8080, public=sub.tsulo-vpn.ru, no Amvera fallback)"
# Patch critical keys in place if .env exists
if [[ -f .env ]]; then
  python3 - <<'PY'
from pathlib import Path
p = Path("/opt/tsulovpn/.env")
text = p.read_text(encoding="utf-8")
lines = text.splitlines()
want = {
    "PORT": "8080",
    "SUBSCRIPTION_PUBLIC_URL": "https://sub.tsulo-vpn.ru",
    "SUBSCRIPTION_KEY_URL": "https://sub.tsulo-vpn.ru",
    "SUBSCRIPTION_FALLBACK_URL": "",
    "FORCE_LEGACY_SUB_MIGRATE": "false",
    "TSULO_DB_PATH": "/var/lib/tsulovpn/tsulovpn.db",
    "TELEGRAM_WEBHOOK_ENABLED": "true",
    "TELEGRAM_WEBHOOK_PATH": "/telegram/webhook",
}
out = []
seen = set()
for line in lines:
    if not line.strip() or line.strip().startswith("#") or "=" not in line:
        out.append(line)
        continue
    k, _, v = line.partition("=")
    k = k.strip()
    if k in want:
        out.append(f"{k}={want[k]}")
        seen.add(k)
    else:
        out.append(line)
for k, v in want.items():
    if k not in seen:
        out.append(f"{k}={v}")
p.write_text("\n".join(out) + "\n", encoding="utf-8")
print("env patched")
PY
else
  echo "ERROR: /opt/tsulovpn/.env missing" >&2
  exit 1
fi

mkdir -p "$DB_DIR"
chmod 700 "$DB_DIR"

echo "==> systemd unit"
cp -f "$ROOT/deploy/tsulovpn.service" /etc/systemd/system/tsulovpn.service
systemctl daemon-reload
systemctl enable tsulovpn

echo "==> Caddy → localhost:8080"
cp -f "$ROOT/deploy/Caddyfile" /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy

echo "==> start tsulovpn"
systemctl restart tsulovpn
sleep 4
systemctl --no-pager --full status tsulovpn | head -35

echo "==> local health"
curl -sS -o /dev/null -w "local:%{http_code}\n" http://127.0.0.1:8080/ || true
curl -sS -o /dev/null -w "public:%{http_code}\n" https://sub.tsulo-vpn.ru/ || true

echo "==> DB counts"
.venv/bin/python - <<'PY'
import sqlite3
from pathlib import Path
path = Path("/var/lib/tsulovpn/tsulovpn.db")
print("db_exists", path.is_file(), "size", path.stat().st_size if path.is_file() else 0)
if path.is_file():
    con = sqlite3.connect(path)
    for table in ("users", "orders"):
        try:
            n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(table, n)
        except Exception as e:
            print(table, "err", e)
PY

echo "DONE_CUTOVER"
