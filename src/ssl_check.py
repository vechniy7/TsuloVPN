"""Проверка HTTPS-сертификата SUBSCRIPTION_PUBLIC_URL (Happ отклоняет невалидный SSL)."""
from __future__ import annotations

import logging
import socket
import ssl
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def verify_public_url_ssl(public_url: str) -> tuple[bool, str]:
    parsed = urlparse((public_url or "").strip())
    host = parsed.hostname
    if not host:
        return False, "SUBSCRIPTION_PUBLIC_URL не задан или без hostname"
    if parsed.scheme.lower() != "https":
        return False, f"Нужен HTTPS, сейчас: {parsed.scheme or 'нет схемы'}"

    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=12) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
    except ssl.SSLCertVerificationError as exc:
        return False, (
            f"SSL для {host} не проходит проверку: {exc}. "
            "Happ покажет «Сертификат недействителен». "
            "В Amvera: Настройки → Доменные имена → добавить бесплатный домен с HTTPS "
            "и дождаться Let's Encrypt (2–5 мин)."
        )
    except OSError as exc:
        return False, f"Не удалось подключиться к {host}:443 — {exc}"

    sans = [value for kind, value in cert.get("subjectAltName", []) if kind == "DNS"]
    if host not in sans and not _wildcard_covers(sans, host):
        return False, (
            f"Сертификат не содержит {host} (SAN: {', '.join(sans) or 'пусто'}). "
            "Привяжите домен в Amvera с типом HTTPS."
        )
    return True, f"SSL OK for {host}"


def _wildcard_covers(sans: list[str], host: str) -> bool:
    labels = host.split(".")
    if len(labels) < 2:
        return False
    for san in sans:
        if not san.startswith("*."):
            continue
        suffix = san[1:]  # .amvera.io
        if host.endswith(suffix) and host.count(".") == suffix.count("."):
            return True
    return False


def log_public_url_ssl(public_url: str) -> None:
    ok, detail = verify_public_url_ssl(public_url)
    if ok:
        logger.info(detail)
        return
    logger.error("SUBSCRIPTION_PUBLIC_URL SSL check failed: %s", detail)
