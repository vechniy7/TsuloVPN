"""LTE-подписка в классическом формате Happ: base64(vless://...) без JSON-конвертации."""

from __future__ import annotations

import base64

from config import config
from parser import brand_config, extract_host_port, get_sni


def lte_profile_label(uri: str, rank: int, *, auto: bool = False) -> str:
    sni = get_sni(uri) or "?"
    hp = extract_host_port(uri)
    host = hp[0] if hp else "?"
    sni_short = sni.split(".")[0] if sni else "?"
    if auto:
        return f"📱 {config.BOT_NAME} · АВТО LTE ★ · {host} · {sni_short}"
    return f"📱 LTE #{rank:02d} · {host} · {sni_short}"


def build_lte_classic_lines(lte_uris: list[str]) -> list[str]:
    """Сырые vless:// с подписью — Happ импортирует как при ручном добавлении."""
    limit = max(1, config.LTE_BALANCER_NODES)
    seen_hosts: set[str] = set()
    lines: list[str] = []

    for uri in lte_uris:
        if len(lines) >= limit:
            break
        hp = extract_host_port(uri)
        if not hp:
            continue
        host_key = hp[0].lower()
        if host_key in seen_hosts:
            continue
        seen_hosts.add(host_key)
        rank = len(lines) + 1
        label = lte_profile_label(uri, rank, auto=(rank == 1))
        lines.append(brand_config(uri, label))

    return lines


def lte_classic_subscription_bytes(lte_uris: list[str]) -> bytes:
    lines = build_lte_classic_lines(lte_uris)
    if not lines:
        return b""
    # Happ classic: base64 от списка vless:// (по одному на строку)
    payload = "\n".join(lines)
    return base64.b64encode(payload.encode("utf-8"))
