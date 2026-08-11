#!/usr/bin/env python3
"""Parse PROXY_URL and generate a local HTTP proxy runtime configuration."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlparse


ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "runtime" / "proxy-config.json"
ENGINE_PATH = ROOT_DIR / "runtime" / "proxy-engine.txt"
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8080


def normalized_proxy_url(value: str | None = None) -> str:
    """Proxy share URIs cannot contain whitespace introduced by copied lines."""
    return "".join((value if value is not None else os.getenv("PROXY_URL", "")).split())


def parse_socks(parsed):
    outbound = {
        "type": "socks",
        "tag": "proxy",
        "server": parsed.hostname,
        "server_port": parsed.port or 1080,
        "version": "5",
    }
    if parsed.username:
        outbound["username"] = unquote(parsed.username)
    if parsed.password:
        outbound["password"] = unquote(parsed.password)
    return outbound


def parse_http(parsed):
    outbound = {
        "type": "http",
        "tag": "proxy",
        "server": parsed.hostname,
        "server_port": parsed.port or 8080,
    }
    if parsed.username:
        outbound["username"] = unquote(parsed.username)
    if parsed.password:
        outbound["password"] = unquote(parsed.password)
    if parsed.scheme == "https":
        outbound["tls"] = {"enabled": True, "server_name": parsed.hostname}
    return outbound


def split_ws_early_data(path: str) -> tuple[str, int | None]:
    decoded_path = unquote(path or "/")
    base_path, separator, query = decoded_path.partition("?")
    query_items = parse_qsl(query, keep_blank_values=True) if separator else []
    early_data = next((value for key, value in query_items if key == "ed"), "")
    remaining = [(key, value) for key, value in query_items if key != "ed"]
    clean_path = base_path or "/"
    if remaining:
        clean_path += "?" + urlencode(remaining)
    return clean_path, int(early_data) if early_data.isdigit() and int(early_data) > 0 else None


def parse_vless(parsed, params):
    outbound = {
        "type": "vless",
        "tag": "proxy",
        "server": parsed.hostname,
        "server_port": parsed.port or 443,
        "uuid": unquote(parsed.username or ""),
    }
    flow = params.get("flow", [""])[0]
    if flow:
        outbound["flow"] = flow

    security = params.get("security", [""])[0]
    if security in ("tls", "reality"):
        tls = {
            "enabled": True,
            "server_name": params.get("sni", [""])[0] or parsed.hostname,
        }
        fingerprint = params.get("fp", [""])[0]
        if fingerprint:
            tls["utls"] = {"enabled": True, "fingerprint": fingerprint}
        alpn = params.get("alpn", [""])[0]
        if alpn:
            tls["alpn"] = alpn.split(",")
        insecure = params.get("insecure", params.get("allowInsecure", ["0"]))[0]
        if insecure in ("1", "true"):
            tls["insecure"] = True
        if security == "reality":
            tls["reality"] = {
                "enabled": True,
                "public_key": params.get("pbk", [""])[0],
                "short_id": params.get("sid", [""])[0],
            }
        outbound["tls"] = tls

    transport_type = params.get("type", [""])[0]
    if transport_type == "ws":
        path, early_data = split_ws_early_data(params.get("path", ["/"])[0])
        transport = {
            "type": "ws",
            "path": path,
            "headers": {"Host": params.get("host", [""])[0] or parsed.hostname},
        }
        if early_data:
            transport["max_early_data"] = early_data
            transport["early_data_header_name"] = "Sec-WebSocket-Protocol"
        outbound["transport"] = transport
    elif transport_type == "grpc":
        outbound["transport"] = {
            "type": "grpc",
            "service_name": params.get("serviceName", [""])[0],
        }
    elif transport_type in ("http", "h2"):
        outbound["transport"] = {
            "type": "http",
            "path": unquote(params.get("path", ["/"])[0]),
            "host": [params.get("host", [""])[0] or parsed.hostname],
        }
    return outbound


def parse_vless_xray(parsed, params):
    stream_settings = {
        "network": "xhttp",
        "security": params.get("security", ["none"])[0] or "none",
        "xhttpSettings": {
            "path": unquote(params.get("path", ["/"])[0] or "/"),
            "mode": params.get("mode", ["auto"])[0] or "auto",
        },
    }
    host = params.get("host", [""])[0]
    if host:
        stream_settings["xhttpSettings"]["host"] = host
    if stream_settings["security"] == "tls":
        tls_settings = {
            "allowInsecure": params.get(
                "insecure", params.get("allowInsecure", ["0"])
            )[0]
            in ("1", "true"),
            "serverName": params.get("sni", [""])[0] or parsed.hostname,
        }
        fingerprint = params.get("fp", [""])[0]
        if fingerprint:
            tls_settings["fingerprint"] = fingerprint
        alpn = params.get("alpn", [""])[0]
        if alpn:
            tls_settings["alpn"] = alpn.split(",")
        stream_settings["tlsSettings"] = tls_settings

    return {
        "protocol": "vless",
        "tag": "proxy",
        "settings": {
            "vnext": [
                {
                    "address": parsed.hostname,
                    "port": parsed.port or 443,
                    "users": [
                        {
                            "id": unquote(parsed.username or ""),
                            "encryption": params.get("encryption", ["none"])[0]
                            or "none",
                        }
                    ],
                }
            ]
        },
        "streamSettings": stream_settings,
    }


def parse_vmess(proxy_url: str):
    encoded = proxy_url.removeprefix("vmess://")
    encoded += "=" * (-len(encoded) % 4)
    config = json.loads(base64.b64decode(encoded).decode("utf-8"))
    outbound = {
        "type": "vmess",
        "tag": "proxy",
        "server": config.get("add", ""),
        "server_port": int(config.get("port", 443)),
        "uuid": config.get("id", ""),
        "security": config.get("scy", "auto"),
        "alter_id": int(config.get("aid", 0)),
    }
    if config.get("tls") == "tls":
        outbound["tls"] = {
            "enabled": True,
            "server_name": config.get("sni") or config.get("host") or config.get("add"),
        }
    transport_type = config.get("net", "tcp")
    if transport_type == "ws":
        path, early_data = split_ws_early_data(config.get("path", "/"))
        transport = {
            "type": "ws",
            "path": path,
            "headers": {"Host": config.get("host") or config.get("add")},
        }
        if early_data:
            transport["max_early_data"] = early_data
            transport["early_data_header_name"] = "Sec-WebSocket-Protocol"
        outbound["transport"] = transport
    elif transport_type == "grpc":
        outbound["transport"] = {
            "type": "grpc",
            "service_name": config.get("path", ""),
        }
    return outbound


def parse_hysteria2(parsed, params):
    tls = {
        "enabled": True,
        "server_name": params.get("sni", [""])[0] or parsed.hostname,
    }
    if params.get("insecure", params.get("allowInsecure", ["0"]))[0] in (
        "1",
        "true",
    ):
        tls["insecure"] = True
    outbound = {
        "type": "hysteria2",
        "tag": "proxy",
        "server": parsed.hostname,
        "server_port": parsed.port or 443,
        "password": unquote(parsed.username or ""),
        "tls": tls,
    }
    obfs = params.get("obfs", [""])[0]
    if obfs:
        outbound["obfs"] = {
            "type": obfs,
            "password": params.get("obfs-password", [""])[0],
        }
    return outbound


def parse_tuic(parsed, params):
    username = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    if ":" in username and not password:
        username, password = username.split(":", 1)
    return {
        "type": "tuic",
        "tag": "proxy",
        "server": parsed.hostname,
        "server_port": parsed.port or 443,
        "uuid": username,
        "password": password,
        "congestion_control": params.get("congestion_control", ["bbr"])[0],
        "tls": {
            "enabled": True,
            "server_name": params.get("sni", [""])[0] or parsed.hostname,
            "insecure": params.get(
                "insecure", params.get("allowInsecure", ["0"])
            )[0]
            in ("1", "true"),
        },
    }


def build_config(proxy_url: str) -> tuple[str, dict]:
    scheme = proxy_url.split("://", 1)[0].lower()
    engine = "sing-box"
    if scheme == "vmess":
        outbound = parse_vmess(proxy_url)
    else:
        parsed = urlparse(proxy_url)
        params = parse_qs(parsed.query)
        if not parsed.hostname:
            raise ValueError("proxy_hostname_missing")
        if scheme in ("socks", "socks5"):
            outbound = parse_socks(parsed)
        elif scheme in ("http", "https"):
            outbound = parse_http(parsed)
        elif scheme == "vless":
            if params.get("type", [""])[0] == "xhttp":
                engine = "xray"
                outbound = parse_vless_xray(parsed, params)
            else:
                outbound = parse_vless(parsed, params)
        elif scheme in ("hy2", "hysteria2"):
            outbound = parse_hysteria2(parsed, params)
        elif scheme == "tuic":
            outbound = parse_tuic(parsed, params)
        else:
            raise ValueError(f"unsupported_proxy_protocol:{scheme}")

    if engine == "xray":
        config = {
            "log": {"loglevel": "warning"},
            "inbounds": [
                {
                    "tag": "http-in",
                    "listen": LISTEN_HOST,
                    "port": LISTEN_PORT,
                    "protocol": "http",
                }
            ],
            "outbounds": [outbound, {"protocol": "freedom", "tag": "direct"}],
        }
    else:
        config = {
            "log": {"level": "info", "timestamp": True},
            "inbounds": [
                {
                    "type": "http",
                    "tag": "http-in",
                    "listen": LISTEN_HOST,
                    "listen_port": LISTEN_PORT,
                }
            ],
            "outbounds": [outbound, {"type": "direct", "tag": "direct"}],
        }
    return engine, config


def main() -> int:
    proxy_url = normalized_proxy_url()
    if not proxy_url:
        print("[Proxy] PROXY_URL is empty; direct connection will be used")
        return 0

    scheme = proxy_url.split("://", 1)[0].lower()
    print(f"[Proxy] Parsing {scheme}://***")
    try:
        engine, config = build_config(proxy_url)
    except Exception as exc:
        print(f"[Proxy] Configuration error: {type(exc).__name__}: {exc}")
        return 1

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    ENGINE_PATH.write_text(engine, encoding="ascii")
    outbound = config["outbounds"][0]
    outbound_type = outbound.get("type", outbound.get("protocol", "unknown"))
    print(f"[Proxy] Engine: {engine}; outbound: {outbound_type}; inbound: http://{LISTEN_HOST}:{LISTEN_PORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
