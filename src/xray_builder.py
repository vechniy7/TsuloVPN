"""Build Happ-compatible Xray JSON: АВТО WIFI + АВТО LTE (simple profiles + TCP ping)."""

from __future__ import annotations

import base64
import json
import logging
import urllib.parse

from config import config
from parser import extract_country_flag, extract_host_port, get_sni

logger = logging.getLogger(__name__)

PROBE_URL = "https://www.gstatic.com/generate_204"


def _q(uri: str) -> dict[str, str]:
    if "?" not in uri:
        return {}
    query = uri.split("?", 1)[1].split("#", 1)[0]
    return {k.lower(): v for k, v in urllib.parse.parse_qsl(query, keep_blank_values=True)}


def _remark_from_branded(uri: str, fallback: str) -> str:
    if "#" not in uri:
        return fallback
    return urllib.parse.unquote(uri.split("#", 1)[1]) or fallback


def _parse_userinfo_host(uri: str) -> tuple[str, str, int] | None:
    hostport = extract_host_port(uri)
    if not hostport:
        return None
    host, port = hostport
    try:
        scheme_sep = uri.index("://") + 3
        rest = uri[scheme_sep:].split("#", 1)[0].split("?", 1)[0]
        if "@" not in rest:
            return None
        user = rest.rsplit("@", 1)[0]
        return urllib.parse.unquote(user), host, port
    except Exception:
        return None


def _stream_settings(uri: str) -> dict:
    params = _q(uri)
    network = (params.get("type") or "tcp").lower()
    if network == "raw":
        network = "tcp"
    security = (params.get("security") or "").lower()
    stream: dict = {"network": network}

    fp = (params.get("fp") or "chrome").strip() or "chrome"
    if fp in ("random", "randomized", ""):
        fp = "chrome"

    if security == "reality":
        reality: dict = {
            "fingerprint": fp,
            "serverName": params.get("sni") or params.get("host") or "",
            "publicKey": params.get("pbk") or "",
            "shortId": params.get("sid") or "",
        }
        if params.get("spx"):
            reality["spiderX"] = params["spx"]
        stream["security"] = "reality"
        stream["realitySettings"] = reality
    elif security == "tls":
        tls: dict = {
            "serverName": params.get("sni") or params.get("host") or "",
            "fingerprint": fp,
            "allowInsecure": False,
        }
        alpn = params.get("alpn")
        if alpn:
            tls["alpn"] = [p.strip() for p in alpn.split(",") if p.strip()]
        stream["security"] = "tls"
        stream["tlsSettings"] = tls
    else:
        stream["security"] = "none"

    if network == "grpc":
        stream["grpcSettings"] = {
            "serviceName": params.get("servicename") or params.get("serviceName") or "",
            "multiMode": (params.get("mode") or "").lower() == "multi",
        }
    elif network == "ws":
        stream["wsSettings"] = {
            "path": params.get("path") or "/",
            "headers": {"Host": params.get("host") or params.get("sni") or ""},
        }
    elif network == "tcp":
        header_type = (params.get("headertype") or "none").lower()
        if header_type and header_type != "none":
            stream["tcpSettings"] = {"header": {"type": header_type}}

    return stream


def vless_to_outbound(uri: str, tag: str) -> dict | None:
    if not uri.lower().startswith("vless://"):
        return None
    parsed = _parse_userinfo_host(uri)
    if not parsed:
        return None
    uuid, host, port = parsed
    params = _q(uri)
    user: dict = {
        "id": uuid,
        "encryption": params.get("encryption") or "none",
    }
    flow = params.get("flow")
    if flow:
        user["flow"] = flow

    return {
        "tag": tag,
        "protocol": "vless",
        "settings": {
            "vnext": [
                {
                    "address": host,
                    "port": port,
                    "users": [user],
                }
            ]
        },
        "streamSettings": _stream_settings(uri),
        "mux": {"enabled": False, "concurrency": -1},
    }


def trojan_to_outbound(uri: str, tag: str) -> dict | None:
    if not uri.lower().startswith("trojan://"):
        return None
    parsed = _parse_userinfo_host(uri)
    if not parsed:
        return None
    password, host, port = parsed
    return {
        "tag": tag,
        "protocol": "trojan",
        "settings": {
            "servers": [
                {
                    "address": host,
                    "port": port,
                    "password": password,
                }
            ]
        },
        "streamSettings": _stream_settings(uri),
        "mux": {"enabled": False, "concurrency": -1},
    }


def uri_to_outbound(uri: str, tag: str) -> dict | None:
    try:
        params = _q(uri)
        network = (params.get("type") or "tcp").lower()
        if network == "xhttp":
            return None
        if uri.lower().startswith("vless://"):
            return vless_to_outbound(uri, tag)
        if uri.lower().startswith("trojan://"):
            return trojan_to_outbound(uri, tag)
    except Exception as exc:
        logger.warning("Failed to convert URI to outbound: %s", exc)
    return None


def _client_inbounds() -> list[dict]:
    return [
        {
            "tag": "socks",
            "port": 10808,
            "listen": "127.0.0.1",
            "protocol": "socks",
            "settings": {"udp": True},
            "sniffing": {
                "enabled": True,
                "destOverride": ["http", "tls", "quic"],
            },
        },
        {
            "tag": "http",
            "port": 10809,
            "listen": "127.0.0.1",
            "protocol": "http",
            "sniffing": {
                "enabled": True,
                "destOverride": ["http", "tls", "quic"],
            },
        },
    ]


def _dns_block(*, lte: bool = False) -> dict:
    if lte:
        return {
            "servers": [
                "fakedns",
                "77.88.8.8",
                "8.8.8.8",
            ],
            "queryStrategy": "UseIPv4",
            "disableFallback": False,
        }
    return {
        "servers": ["1.1.1.1", "8.8.8.8"],
        "queryStrategy": "UseIP",
    }


def _fakedns_block() -> list[dict]:
    return [{"ipPool": "198.18.0.0/15", "poolSize": 65535}]


def _lte_routing_rules(balancer_tag: str) -> list[dict]:
    """Весь трафик (включая DNS) через balancer — иначе на LTE whitelist уходит в direct."""
    return [
        _private_direct_rule(),
        {
            "type": "field",
            "network": "udp",
            "port": "53",
            "balancerTag": balancer_tag,
        },
        {
            "type": "field",
            "network": "tcp,udp",
            "balancerTag": balancer_tag,
        },
    ]


def _private_direct_rule() -> dict:
    return {
        "type": "field",
        "ip": [
            "0.0.0.0/8",
            "10.0.0.0/8",
            "127.0.0.0/8",
            "169.254.0.0/16",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "::1/128",
            "fc00::/7",
            "fe80::/10",
        ],
        "outboundTag": "direct",
    }


def build_auto_select_config(
    uris: list[str],
    *,
    remarks: str,
    node_prefix: str,
    description: str,
    probe_url: str | None = None,
    probe_interval_sec: int | None = None,
    max_rtt_ms: int | None = None,
    lte_dns: bool = False,
) -> dict | None:
    """
    One Happ profile: Xray observatory + balancer over all nodes.
    probe_url is fetched BY THE CLIENT through each outbound (real RTT path).
    If max_rtt_ms is set (LTE), use leastLoad+maxRTT to skip dead 1–2.5s nodes.
    """
    outbounds: list[dict] = []
    for idx, uri in enumerate(uris):
        outbound = uri_to_outbound(uri, f"{node_prefix}{idx}")
        if outbound:
            outbounds.append(outbound)

    if not outbounds:
        return None

    probe = (probe_url or PROBE_URL).strip() or PROBE_URL
    probe_sec = max(8, int(probe_interval_sec or config.AUTO_PROBE_INTERVAL_SEC))

    # Single node: still a valid profile (no balancer needed)
    if len(outbounds) == 1:
        only = outbounds[0]
        only["tag"] = "proxy"
        outbounds = [
            only,
            {"tag": "direct", "protocol": "freedom", "settings": {}},
            {"tag": "block", "protocol": "blackhole", "settings": {}},
        ]
        return {
            "remarks": remarks,
            "meta": {"serverDescription": base64.b64encode(description.encode()).decode()},
            "log": {"loglevel": "warning"},
            **({"fakedns": _fakedns_block()} if lte_dns else {}),
            "dns": _dns_block(lte=lte_dns),
            "inbounds": _client_inbounds(),
            "outbounds": outbounds,
            "routing": {
                "domainStrategy": "IPIfNonMatch" if lte_dns else "AsIs",
                "rules": [
                    _private_direct_rule(),
                    {
                        "type": "field",
                        "network": "tcp,udp",
                        "outboundTag": "proxy",
                    },
                ],
            },
        }

    outbounds.append({"tag": "direct", "protocol": "freedom", "settings": {}})
    outbounds.append({"tag": "block", "protocol": "blackhole", "settings": {}})

    node_count = sum(1 for o in outbounds if str(o.get("tag", "")).startswith(node_prefix))
    first_node = f"{node_prefix}0"
    balancer_tag = f"bal-{node_prefix.rstrip('-')}"
    host_hint = probe.replace("https://", "").replace("http://", "").split("/", 1)[0]

    if max_rtt_ms and max_rtt_ms > 0:
        # Exclude alive-but-unusable high-latency nodes (typical 1000–2500ms fails)
        strategy: dict = {
            "type": "leastLoad",
            "settings": {
                # Only nodes with YouTube RTT under this threshold; pick the best one
                "maxRTT": f"{int(max_rtt_ms)}ms",
                "expected": 1,
                "tolerance": 0.1,
            },
        }
        strategy_label = f"leastLoad≤{int(max_rtt_ms)}ms→{host_hint}"
    else:
        strategy = {"type": "leastPing"}
        strategy_label = f"leastPing→{host_hint}"

    return {
        "remarks": remarks,
        "meta": {
            "serverDescription": base64.b64encode(
                f"{description} · {strategy_label} · {node_count} · {probe_sec}с".encode()
            ).decode()
        },
        "log": {"loglevel": "warning"},
        **({"fakedns": _fakedns_block()} if lte_dns else {}),
        "dns": _dns_block(lte=lte_dns),
        "inbounds": _client_inbounds(),
        "outbounds": outbounds,
        "routing": {
            "domainStrategy": "IPIfNonMatch" if lte_dns else "AsIs",
            "balancers": [
                {
                    "tag": balancer_tag,
                    "selector": [node_prefix],
                    "fallbackTag": first_node,
                    "strategy": strategy,
                }
            ],
            "rules": _lte_routing_rules(balancer_tag)
            if lte_dns
            else [
                _private_direct_rule(),
                {
                    "type": "field",
                    "network": "tcp,udp",
                    "balancerTag": balancer_tag,
                },
            ],
        },
        "observatory": {
            "subjectSelector": [node_prefix],
            "probeUrl": probe,
            "probeInterval": f"{probe_sec}s",
            "enableConcurrency": True,
        },
    }


def build_lte_simple_config(uri: str, remarks: str) -> dict | None:
    """
    Минимальный LTE-профиль как при ручном импорте vless:// в Happ.
    Без FakeDNS/DNS — иначе на LTE whitelist DNS уходит мимо туннеля.
    """
    outbound = uri_to_outbound(uri, "proxy")
    if not outbound:
        return None
    return {
        "remarks": remarks,
        "log": {"loglevel": "warning"},
        "inbounds": _client_inbounds(),
        "outbounds": [
            outbound,
            {"tag": "direct", "protocol": "freedom", "settings": {"domainStrategy": "UseIPv4"}},
            {"tag": "block", "protocol": "blackhole", "settings": {}},
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [
                _private_direct_rule(),
                {"type": "field", "ip": ["::/0"], "outboundTag": "block"},
                {
                    "type": "field",
                    "network": "tcp,udp",
                    "outboundTag": "proxy",
                },
            ],
        },
    }


def _lte_profile_remark(uri: str, rank: int, *, auto: bool = False) -> str:
    sni = get_sni(uri) or "?"
    hp = extract_host_port(uri)
    host = hp[0] if hp else "?"
    sni_short = sni.split(".")[0] if sni else "?"
    if auto:
        return f"📱 {config.BOT_NAME} · АВТО LTE ★ · {host} · {sni_short}"
    return f"📱 LTE #{rank:02d} · {host} · {sni_short}"


def build_lte_happ_ping_profiles(lte_uris: list[str]) -> list[dict]:
    """До LTE_BALANCER_NODES отдельных профилей, #1 = лучший по TCP с сервера."""
    entries: list[dict] = []
    pool = lte_uris[: max(1, config.LTE_BALANCER_NODES)]
    for idx, uri in enumerate(pool):
        remarks = _lte_profile_remark(uri, idx + 1, auto=(idx == 0))
        cfg = build_lte_simple_config(uri, remarks)
        if cfg:
            entries.append(cfg)
    return entries


def build_single_server_config(uri: str, index: int) -> dict | None:
    outbound = uri_to_outbound(uri, "proxy")
    if not outbound:
        return None

    flag = extract_country_flag(uri) or "🌐"
    remarks = _remark_from_branded(uri, f"{flag} {config.BOT_NAME} · Сервер #{index}")
    return {
        "remarks": remarks,
        "log": {"loglevel": "warning"},
        "dns": _dns_block(),
        "inbounds": _client_inbounds(),
        "outbounds": [
            outbound,
            {"tag": "direct", "protocol": "freedom", "settings": {}},
            {"tag": "block", "protocol": "blackhole", "settings": {}},
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [
                {
                    "type": "field",
                    "network": "tcp,udp",
                    "outboundTag": "proxy",
                }
            ],
        },
    }


def build_subscription_json(
    wifi_uris: list[str],
    lte_uris: list[str],
    *,
    show_individual: bool | None = None,
) -> list[dict]:
    """Two visible profiles: АВТО WIFI + АВТО LTE."""
    if show_individual is None:
        show_individual = config.SUBSCRIPTION_SHOW_INDIVIDUAL

    entries: list[dict] = []

    wifi = build_auto_select_config(
        wifi_uris,
        remarks=f"📶 {config.BOT_NAME} · АВТО WIFI",
        node_prefix="wifi-",
        description="Wi‑Fi · чёрные списки",
        probe_url=config.WIFI_PROBE_URL,
        probe_interval_sec=config.AUTO_PROBE_INTERVAL_SEC,
    )
    if wifi:
        entries.append(wifi)

    lte_pool = lte_uris[: max(1, config.LTE_BALANCER_NODES)]
    if config.LTE_DELIVERY == "balancer":
        lte = build_auto_select_config(
            lte_pool,
            remarks=f"📱 {config.BOT_NAME} · АВТО LTE",
            node_prefix="lte-",
            description="LTE · whitelist IP · leastPing",
            probe_url=config.LTE_PROBE_URL,
            probe_interval_sec=config.LTE_PROBE_INTERVAL_SEC,
            max_rtt_ms=config.LTE_MAX_RTT_MS or None,
            lte_dns=True,
        )
        if lte:
            entries.append(lte)
    else:
        entries.extend(build_lte_happ_ping_profiles(lte_pool))

    if show_individual:
        for idx, uri in enumerate(wifi_uris + lte_uris, start=1):
            single = build_single_server_config(uri, idx)
            if single:
                entries.append(single)

    return entries


def json_profiles_from_uris(uris: list[str]) -> list[dict]:
    """Fallback: vless:// → JSON-профиль, чтобы Happ не показывал «Копировать URL»."""
    entries: list[dict] = []
    for idx, uri in enumerate(uris, start=1):
        cfg = build_single_server_config(uri, idx)
        if cfg:
            entries.append(cfg)
    return entries


def subscription_json_bytes(
    wifi_uris: list[str],
    lte_uris: list[str],
    *,
    show_individual: bool | None = None,
) -> bytes:
    return json.dumps(
        build_subscription_json(wifi_uris, lte_uris, show_individual=show_individual),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
