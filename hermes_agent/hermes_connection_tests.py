#!/usr/bin/env python3
"""On-demand connection tests for the add-on Ingress UI (/test/<name>)."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

OPTIONS_PATH = Path("/data/options.json")
STATUS_PATH = Path("/share/hermes/status.json")
HERMES_JSON = Path("/config/.hermes/hermes.json")
HERMES_YAML = Path("/config/.hermes/config.yaml")
ENV_PATH = Path("/config/.hermes/.env")
HELPER_PATH = Path("/hermes_config_helper.py")
TOKEN_SECRET = Path("/config/secrets/homeassistant.token")

CHECKS = (
    "mqtt_broker",
    "mqtt_auth",
    "hass_url",
    "homeassistant_token",
    "mcp",
    "dashboard",
    "dashboard_https",
    "gateway",
    "gateway_https",
    "gateway_remote",
    "assist_api",
    "terminal",
    "all",
)

# Backward-compatible aliases from 0.0.23 grouped tests.
ALIASES = {
    "mqtt": "mqtt_broker",
    "ha": "hass_url",
    "gateway": "gateway",
    "dashboard": "dashboard",
    "assist": "assist_api",
}


def _load_options() -> dict[str, Any]:
    if not OPTIONS_PATH.is_file():
        return {}
    try:
        data = json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _nested(options: dict[str, Any], *keys: str, default: Any = "") -> Any:
    cur: Any = options
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return cur if cur is not None else default


def _truthy(value: Any) -> bool:
    return str(value).lower() in ("1", "true", "yes")


def _skipped(summary: str, detail: str = "") -> dict[str, Any]:
    return {"ok": True, "skipped": True, "summary": summary, "detail": detail}


def _tcp_reachable(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_status(url: str, headers: dict[str, str] | None = None, timeout: float = 5.0) -> int | None:
    req = urllib.request.Request(url, method="GET", headers=headers or {})
    context = None
    if url.startswith("https://"):
        import ssl  # noqa: PLC0415

        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def _read_env_token() -> str:
    if not ENV_PATH.is_file():
        return ""
    for line in ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("HOMEASSISTANT_TOKEN="):
            return line.split("=", 1)[1].strip()
    return ""


def _ha_token(options: dict[str, Any]) -> str:
    token = str(_nested(options, "home_assistant", "homeassistant_token", default="") or "").strip()
    if token:
        return token
    token = _read_env_token()
    if token:
        return token
    if TOKEN_SECRET.is_file():
        return TOKEN_SECRET.read_text(encoding="utf-8", errors="replace").strip()
    return ""


def _bashio_ha_service() -> tuple[str, str]:
    if not Path("/etc/bashio.sh").is_file():
        return "", "8123"
    script = (
        ". /etc/bashio.sh\n"
        "host=\"$(bashio::services homeassistant host 2>/dev/null || true)\"\n"
        "port=\"$(bashio::services homeassistant port 2>/dev/null || echo 8123)\"\n"
        "printf '%s\\n' \"$host\"\n"
        "printf '%s\\n' \"$port\"\n"
    )
    try:
        proc = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
        if len(lines) >= 2:
            return lines[0], lines[1] or "8123"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "", "8123"


def _resolve_ha_urls(options: dict[str, Any]) -> dict[str, Any]:
    helper = HELPER_PATH if HELPER_PATH.is_file() else Path(__file__).with_name("hermes_config_helper.py")
    if not helper.is_file():
        base = str(_nested(options, "home_assistant", "hass_url", default="") or "").strip().rstrip("/")
        base = base or "http://127.0.0.1:8123"
        return {"homeassistant_url": base, "mcp_url": f"{base}/api/mcp", "source": "fallback"}

    internal_host, internal_port = _bashio_ha_service()
    payload = {
        "hass_url": str(_nested(options, "home_assistant", "hass_url", default="") or "").strip(),
        "supervisor_available": "true" if os.environ.get("SUPERVISOR_TOKEN") else "false",
        "internal_host": internal_host,
        "internal_port": internal_port or "8123",
    }
    try:
        sys.path.insert(0, str(helper.parent))
        from hermes_config_helper import resolve_home_assistant_url  # noqa: PLC0415

        resolved = resolve_home_assistant_url(payload)
        if isinstance(resolved, dict):
            return resolved
    except Exception:
        pass
    base = payload["hass_url"] or "http://127.0.0.1:8123"
    return {"homeassistant_url": base, "mcp_url": f"{base.rstrip('/')}/api/mcp", "source": "fallback"}


def _mcp_url_from_config() -> str:
    if not HERMES_YAML.is_file():
        return ""
    try:
        import yaml  # noqa: PLC0415

        cfg = yaml.safe_load(HERMES_YAML.read_text(encoding="utf-8")) or {}
        ha = (cfg.get("mcp_servers") or {}).get("HA") or {}
        return str(ha.get("url") or "").strip()
    except Exception:
        return ""


def _dashboard_ports(options: dict[str, Any]) -> tuple[int, int]:
    access_mode = str(_nested(options, "gateway_access", "access_mode", default="custom") or "custom")
    dash_port = int(_nested(options, "web_interface", "dashboard_port", default=9119) or 9119)
    if access_mode == "lan_https":
        return dash_port, dash_port + 1
    return dash_port, dash_port


def _build_mqtt_payload(options: dict[str, Any]) -> dict[str, Any]:
    mqtt = _nested(options, "mqtt_settings", default={})
    if not isinstance(mqtt, dict):
        mqtt = {}
    return {
        "mqtt_settings": {
            "broker_host": str(mqtt.get("broker_host") or ""),
            "broker_port": str(mqtt.get("broker_port") or "1883"),
            "broker_username": str(mqtt.get("broker_username") or ""),
            "broker_password": str(mqtt.get("broker_password") or ""),
        }
    }


def check_mqtt_broker(options: dict[str, Any]) -> dict[str, Any]:
    from hermes_mqtt_resolver import resolve_mqtt_broker

    resolved = resolve_mqtt_broker(_build_mqtt_payload(options))
    if not resolved.get("host"):
        return {
            "ok": False,
            "summary": "No MQTT broker configured or autodetected",
            "detail": "Set mqtt_settings.broker_host or install the Mosquitto add-on.",
        }
    host = str(resolved["host"])
    try:
        port = int(resolved.get("port") or 1883)
    except ValueError:
        port = 1883
    ok = _tcp_reachable(host, port)
    return {
        "ok": ok,
        "summary": f"{'Reachable' if ok else 'Unreachable'}: {host}:{port}",
        "detail": f"source={resolved.get('source', 'unknown')}",
        "host": host,
        "port": port,
    }


def check_mqtt_auth(options: dict[str, Any]) -> dict[str, Any]:
    from hermes_mqtt_resolver import resolve_mqtt_broker

    resolved = resolve_mqtt_broker(_build_mqtt_payload(options))
    username = str(resolved.get("username") or "").strip()
    if not username:
        return _skipped(
            "No MQTT username configured (skipped)",
            "Set mqtt_settings.broker_username to test authentication.",
        )
    host = str(resolved.get("host") or "").strip()
    if not host:
        return {
            "ok": False,
            "summary": "MQTT broker not resolved",
            "detail": "Run Test Broker first or set mqtt_settings.broker_host.",
        }
    try:
        port = int(resolved.get("port") or 1883)
    except ValueError:
        port = 1883
    password = str(resolved.get("password") or "")
    try:
        import paho.mqtt.client as mqtt  # noqa: PLC0415

        try:
            api_version = mqtt.CallbackAPIVersion.VERSION2
        except AttributeError:
            api_version = None
        client = mqtt.Client(callback_api_version=api_version) if api_version else mqtt.Client()
        client.username_pw_set(username, password or None)
        client.connect(host, port, keepalive=10)
        client.disconnect()
        return {
            "ok": True,
            "summary": f"MQTT auth OK for {username}@{host}:{port}",
            "detail": f"source={resolved.get('source', 'unknown')}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "summary": "MQTT authentication failed",
            "detail": str(exc),
        }


def check_hass_url(options: dict[str, Any]) -> dict[str, Any]:
    resolved = _resolve_ha_urls(options)
    base = str(resolved.get("homeassistant_url") or "").rstrip("/")
    if not base:
        return {
            "ok": False,
            "summary": "Home Assistant URL not resolved",
            "detail": "Set home_assistant.hass_url or run on HAOS for autodetection.",
        }
    status = _http_status(f"{base}/api/")
    ok = status in (200, 401, 403, 404)
    return {
        "ok": ok,
        "summary": f"HA URL probe HTTP {status if status is not None else 'timeout'}",
        "detail": f"{base} (source={resolved.get('source', 'unknown')})",
        "http_status": status,
    }


def check_homeassistant_token(options: dict[str, Any]) -> dict[str, Any]:
    token = _ha_token(options)
    if not token:
        return {
            "ok": False,
            "summary": "Home Assistant token missing",
            "detail": "Paste a long-lived access token in home_assistant.homeassistant_token.",
        }
    resolved = _resolve_ha_urls(options)
    base = str(resolved.get("homeassistant_url") or "").rstrip("/")
    status = _http_status(f"{base}/api/config", headers={"Authorization": f"Bearer {token}"})
    ok = status == 200
    return {
        "ok": ok,
        "summary": f"Token probe HTTP {status if status is not None else 'timeout'}",
        "detail": base,
        "http_status": status,
    }


def check_mcp(options: dict[str, Any]) -> dict[str, Any]:
    token = _ha_token(options)
    if not token:
        return {
            "ok": False,
            "summary": "Home Assistant token missing",
            "detail": "MCP requires home_assistant.homeassistant_token.",
        }
    url = _mcp_url_from_config()
    if not url:
        resolved = _resolve_ha_urls(options)
        url = str(resolved.get("mcp_url") or "").strip()
    if not url:
        return {
            "ok": False,
            "summary": "MCP URL not configured",
            "detail": "Enable home_assistant.auto_configure_mcp and restart, or configure MCP manually.",
        }
    status = _http_status(url, headers={"Authorization": f"Bearer {token}"})
    ok = status in (200, 405)
    return {
        "ok": ok,
        "summary": f"MCP probe HTTP {status if status is not None else 'timeout'}",
        "detail": url,
        "http_status": status,
    }


def check_gateway(options: dict[str, Any]) -> dict[str, Any]:
    mode = str(_nested(options, "gateway_access", "gateway_mode", default="local") or "local")
    if mode == "remote":
        return _skipped(
            "Local gateway skipped (gateway_mode=remote)",
            "Use Test Remote Gateway instead.",
        )

    running = False
    detail = "hermes gateway process not found"
    try:
        proc = subprocess.run(
            ["pgrep", "-f", r"[h]ermes.*gateway"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0 and (proc.stdout or "").strip():
            running = True
            detail = "hermes gateway run process detected"
    except (OSError, subprocess.TimeoutExpired):
        pass

    if STATUS_PATH.is_file():
        try:
            snap = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
            if isinstance(snap, dict) and snap.get("gateway_running"):
                running = True
                detail = "status.json reports gateway_running=true"
        except (OSError, json.JSONDecodeError):
            pass

    return {
        "ok": running,
        "summary": "Gateway running" if running else "Gateway not running",
        "detail": detail,
    }


def check_gateway_remote(options: dict[str, Any]) -> dict[str, Any]:
    mode = str(_nested(options, "gateway_access", "gateway_mode", default="local") or "local")
    if mode != "remote":
        return _skipped(
            "Remote gateway skipped (gateway_mode=local)",
            "Set gateway_access.gateway_mode to remote to test gateway_remote_url.",
        )
    remote = str(_nested(options, "gateway_access", "gateway_remote_url", default="") or "").strip()
    if not remote:
        return {
            "ok": False,
            "summary": "gateway_remote_url not set",
            "detail": "Set gateway_access.gateway_remote_url (e.g. ws://192.168.1.10:18789).",
        }
    parsed = urlparse(remote)
    host = parsed.hostname or ""
    if not host:
        return {"ok": False, "summary": "Invalid gateway_remote_url", "detail": remote}
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    ok = _tcp_reachable(host, port)
    return {
        "ok": ok,
        "summary": f"{'Reachable' if ok else 'Unreachable'}: {host}:{port}",
        "detail": remote,
    }


def check_gateway_https(options: dict[str, Any]) -> dict[str, Any]:
    access_mode = str(_nested(options, "gateway_access", "access_mode", default="custom") or "custom")
    if access_mode != "lan_https":
        return _skipped(
            "Gateway HTTPS skipped (access_mode is not lan_https)",
            "Switch gateway_access.access_mode to lan_https to test nginx on gateway_port.",
        )
    port = int(_nested(options, "gateway_access", "gateway_port", default=18789) or 18789)
    status = _http_status(f"https://127.0.0.1:{port}/", timeout=8.0)
    ok = status is not None and status < 500
    return {
        "ok": ok,
        "summary": f"Gateway HTTPS HTTP {status if status is not None else 'unreachable'}",
        "detail": f"https://<LAN-IP>:{port}/ (nginx TLS on gateway_port)",
        "http_status": status,
    }


def check_dashboard(options: dict[str, Any]) -> dict[str, Any]:
    if not _truthy(_nested(options, "web_interface", "enable_web_interface", default=True)):
        return {
            "ok": False,
            "summary": "Hermes dashboard disabled",
            "detail": "Enable web_interface.enable_web_interface.",
        }
    if not _truthy(_nested(options, "web_interface", "auto_start_with_integration", default=True)):
        return {
            "ok": False,
            "summary": "Dashboard auto-start disabled",
            "detail": "Enable web_interface.auto_start_with_integration.",
        }

    _, internal = _dashboard_ports(options)
    url = f"http://127.0.0.1:{internal}/"
    status = _http_status(url, headers={"Host": f"127.0.0.1:{internal}"})
    ok = status is not None and status < 500
    return {
        "ok": ok,
        "summary": f"Dashboard loopback HTTP {status if status is not None else 'unreachable'}",
        "detail": f"127.0.0.1:{internal} (hermes dashboard process)",
        "http_status": status,
    }


def check_dashboard_https(options: dict[str, Any]) -> dict[str, Any]:
    access_mode = str(_nested(options, "gateway_access", "access_mode", default="custom") or "custom")
    if access_mode != "lan_https":
        return _skipped(
            "Dashboard HTTPS skipped (access_mode is not lan_https)",
            "Switch gateway_access.access_mode to lan_https.",
        )
    if not _truthy(_nested(options, "web_interface", "enable_web_interface", default=True)):
        return {
            "ok": False,
            "summary": "Hermes dashboard disabled",
            "detail": "Enable web_interface.enable_web_interface.",
        }
    gw_port = int(_nested(options, "gateway_access", "gateway_port", default=18789) or 18789)
    dash_port = int(_nested(options, "web_interface", "dashboard_port", default=9119) or 9119)
    if dash_port == gw_port:
        return _skipped(
            "Dashboard HTTPS skipped (same port as gateway_port)",
            f"Port {dash_port} is already covered by Test Gateway HTTPS.",
        )
    status = _http_status(f"https://127.0.0.1:{dash_port}/", timeout=8.0)
    ok = status is not None and status < 500
    return {
        "ok": ok,
        "summary": f"Dashboard HTTPS HTTP {status if status is not None else 'unreachable'}",
        "detail": f"https://<LAN-IP>:{dash_port}/ (nginx TLS on dashboard_port)",
        "http_status": status,
    }


def check_assist_api(options: dict[str, Any]) -> dict[str, Any]:
    if not _truthy(_nested(options, "gateway_access", "enable_openai_api", default=False)):
        return _skipped(
            "Assist API disabled (skipped)",
            "Enable gateway_access.enable_openai_api and restart to test the API server.",
        )
    status = _http_status("http://127.0.0.1:8642/health")
    ok = status == 200
    return {
        "ok": ok,
        "summary": f"Assist API /health HTTP {status if status is not None else 'unreachable'}",
        "detail": "http://<LAN-IP>:8642/v1 from Home Assistant Core",
        "http_status": status,
    }


def check_terminal(options: dict[str, Any]) -> dict[str, Any]:
    if not _truthy(_nested(options, "enable_terminal", default=True)):
        return _skipped(
            "Web terminal disabled (skipped)",
            "Enable enable_terminal in add-on Configuration.",
        )
    port = int(_nested(options, "terminal_port", default=7681) or 7681)
    ok = _tcp_reachable("127.0.0.1", port)
    return {
        "ok": ok,
        "summary": f"{'Reachable' if ok else 'Unreachable'}: terminal on 127.0.0.1:{port}",
        "detail": "Ingress terminal is proxied from the landing page at ./terminal/",
    }


RUNNERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "mqtt_broker": check_mqtt_broker,
    "mqtt_auth": check_mqtt_auth,
    "hass_url": check_hass_url,
    "homeassistant_token": check_homeassistant_token,
    "mcp": check_mcp,
    "dashboard": check_dashboard,
    "dashboard_https": check_dashboard_https,
    "gateway": check_gateway,
    "gateway_https": check_gateway_https,
    "gateway_remote": check_gateway_remote,
    "assist_api": check_assist_api,
    "terminal": check_terminal,
}


def _canonical_name(name: str) -> str:
    return ALIASES.get(name, name)


def run_check(name: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options if options is not None else _load_options()
    name = _canonical_name(name)

    if name == "all":
        results = {key: run_check(key, options) for key in RUNNERS}
        ok = all(r.get("ok") or r.get("skipped") for r in results.values())
        return {"ok": ok, "checks": results}

    if name not in RUNNERS:
        valid = ", ".join(sorted(RUNNERS) + ["all"])
        return {"ok": False, "summary": f"Unknown test '{name}'", "detail": f"Valid: {valid}"}

    result = RUNNERS[name](options)
    result["check"] = name
    return result


class _TestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path.strip("/")
        parts = [p for p in path.split("/") if p]
        name = parts[-1] if parts and parts[0] == "test" else "all"
        payload = run_check(name)
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def serve(port: int) -> None:
    server = HTTPServer(("127.0.0.1", port), _TestHandler)
    server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes add-on connection tests")
    parser.add_argument("--serve", action="store_true", help="Run HTTP server for Ingress /test/*")
    parser.add_argument("--port", type=int, default=48100)
    parser.add_argument("--check", choices=CHECKS, help="Run one check and print JSON")
    args = parser.parse_args()

    if args.serve:
        serve(args.port)
        return 0

    if args.check:
        json.dump(run_check(args.check), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
