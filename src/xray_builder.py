"""Build Happ-compatible Xray JSON configs (balancer АВТО-ВЫБОР + single servers)."""

from __future__ import annotations

import base64
import json
import logging
import urllib.parse

from config import config
from parser import extract_country_flag, extract_host_port

logger = logging.getLogger(__name__)

PROBE_URL = "https://www.gstatic.com/generate_204"
NODE_TAG_PREFIX = "node-"


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
    """Returns (user, host, port) for vless/trojan/ss-style URIs."""
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

    if security == "reality":
        reality: dict = {
            "fingerprint": params.get("fp") or "chrome",
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
            "fingerprint": params.get("fp") or "chrome",
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
    }


def uri_to_outbound(uri: str, tag: str) -> dict | None:
    try:
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


def _dns_block() -> dict:
    return {
        "servers": [
            "1.1.1.1",
            "8.8.8.8",
        ],
        "queryStrategy": "UseIP",
    }


def build_auto_select_config(uris: list[str]) -> dict | None:
    """One selectable Happ entry: leastPing balancer + continuous health checks."""
    outbounds: list[dict] = []
    for idx, uri in enumerate(uris):
        outbound = uri_to_outbound(uri, f"{NODE_TAG_PREFIX}{idx}")
        if outbound:
            outbounds.append(outbound)

    if len(outbounds) < 2:
        # Need at least 2 nodes for meaningful auto-failover
        if not outbounds and uris:
            one = uri_to_outbound(uris[0], f"{NODE_TAG_PREFIX}0")
            if one:
                outbounds = [one]
        if not outbounds:
            return None

    outbounds.append({"tag": "direct", "protocol": "freedom", "settings": {}})
    outbounds.append({"tag": "block", "protocol": "blackhole", "settings": {}})

    remarks = f"⚡ {config.BOT_NAME} · АВТО-ВЫБОР"
    return {
        "remarks": remarks,
        "meta": {
            "serverDescription": base64.b64encode(
                "leastPing · автопереключение".encode()
            ).decode()
        },
        "log": {"loglevel": "warning"},
        "dns": _dns_block(),
        "inbounds": _client_inbounds(),
        "outbounds": outbounds,
        "routing": {
            "domainStrategy": "AsIs",
            "balancers": [
                {
                    "tag": "auto",
                    "selector": [NODE_TAG_PREFIX],
                    "fallbackTag": "direct",
                    "strategy": {"type": "leastPing"},
                }
            ],
            "rules": [
                {
                    "type": "field",
                    "network": "tcp,udp",
                    "balancerTag": "auto",
                }
            ],
        },
        "observatory": {
            "subjectSelector": [NODE_TAG_PREFIX],
            "probeUrl": PROBE_URL,
            "probeInterval": "20s",
            "enableConcurrency": True,
        },
    }


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


def build_subscription_json(uris: list[str]) -> list[dict]:
    """Happ JSON-array subscription: АВТО-ВЫБОР first, then manual servers."""
    entries: list[dict] = []
    auto = build_auto_select_config(uris)
    if auto:
        entries.append(auto)

    for idx, uri in enumerate(uris, start=1):
        single = build_single_server_config(uri, idx)
        if single:
            entries.append(single)

    return entries


def subscription_json_bytes(uris: list[str]) -> bytes:
    return json.dumps(build_subscription_json(uris), ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
