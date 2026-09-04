"""Deep-link импорт подписки в Happ / INCY / Happ Plus через HTTPS-редирект.

Telegram url-кнопки принимают только http(s)/tg://, поэтому открываем
https://…/open/{app}?u=… → HTML → deep link в приложение.
"""

from __future__ import annotations

from urllib.parse import quote, unquote

from config import config

# app_id → (scheme builder, human title)
APP_DEEPLINKS = {
    "happ": ("happ", "Happ"),
    "incy": ("incy", "INCY"),
    "happplus": ("happ", "Happ Plus"),  # тот же scheme, что у Happ
}


def plain_subscription_url(token_or_url: str) -> str:
    """Всегда https-ключ (не happ://crypt) — универсален для клиентов."""
    value = (token_or_url or "").strip()
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return config.subscription_url_for_token(value)


def deeplink_for_app(app_id: str, subscription_url: str) -> str | None:
    meta = APP_DEEPLINKS.get(app_id)
    if not meta:
        return None
    scheme, _title = meta
    url = plain_subscription_url(subscription_url)
    # Happ/INCY: URL как есть, без encodeURIComponent (иначе «URL not valid»).
    if scheme == "incy":
        return f"incy://add/{url}"
    return f"happ://add/{url}"


def open_app_https_url(app_id: str, subscription_url: str) -> str | None:
    if app_id not in APP_DEEPLINKS:
        return None
    base = (config.SUBSCRIPTION_PUBLIC_URL or "").rstrip("/")
    if not base.startswith("https://"):
        return None
    url = plain_subscription_url(subscription_url)
    return f"{base}/open/{app_id}?u={quote(url, safe='')}"


def decode_open_query(raw: str | None) -> str:
    return unquote((raw or "").strip())


def open_app_html(*, app_id: str, subscription_url: str) -> str:
    import html as html_lib
    import json

    meta = APP_DEEPLINKS.get(app_id) or ("happ", "приложение")
    _scheme, title = meta
    deep = deeplink_for_app(app_id, subscription_url) or "#"
    safe_title = html_lib.escape(title)
    deep_attr = html_lib.escape(deep, quote=True)
    deep_js = json.dumps(deep)
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Открыть {safe_title}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; background:#0f1117; color:#e8eaed;
           display:flex; min-height:100vh; align-items:center; justify-content:center; margin:0; }}
    .box {{ background:#1a1d26; border-radius:16px; padding:28px; max-width:420px; text-align:center; }}
    a {{ display:inline-block; margin-top:16px; padding:12px 18px; border-radius:12px;
         background:#7c5cff; color:#fff; text-decoration:none; font-weight:600; }}
    p {{ color:#9aa0a6; line-height:1.5; }}
  </style>
  <script>location.replace({deep_js});</script>
</head>
<body>
  <div class="box">
    <h1>Открываем {safe_title}…</h1>
    <p>Если приложение не открылось — установите его и нажмите кнопку ниже.</p>
    <a href="{deep_attr}">Открыть {safe_title}</a>
  </div>
</body>
</html>
"""
