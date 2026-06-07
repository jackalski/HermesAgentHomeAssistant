#!/usr/bin/env python3
"""Resolve Mosquitto broker settings for the Hermes status exporter."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import urllib.error
import urllib.request
from typing import Any


def _tcp_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _from_env() -> dict[str, Any]:
    host = (os.environ.get("MQTT_HOST") or "").strip()
    if not host:
        return {}
    return {
        "host": host,
        "port": str(os.environ.get("MQTT_PORT") or "1883"),
        "username": (os.environ.get("MQTT_USER") or os.environ.get("MQTT_USERNAME") or ""),
        "password": os.environ.get("MQTT_PASSWORD") or "",
        "source": "env",
    }


def _from_mqtt_settings(payload: dict[str, Any]) -> dict[str, Any]:
    """User override from add-on mqtt_settings expansion panel."""
    settings = payload.get("mqtt_settings")
    if not isinstance(settings, dict):
        settings = {}
    host = str(settings.get("broker_host") or "").strip()
    if not host:
        return {}
    return {
        "host": host,
        "port": str(settings.get("broker_port") or "1883"),
        "username": str(settings.get("broker_username") or ""),
        "password": str(settings.get("broker_password") or ""),
        "source": "addon_options",
    }


def _from_options_payload(payload: dict[str, Any]) -> dict[str, Any]:
    mqtt_cfg = payload.get("mqtt")
    if not isinstance(mqtt_cfg, dict):
        return {}
    host = str(mqtt_cfg.get("host") or "").strip()
    if not host:
        return {}
    return {
        "host": host,
        "port": str(mqtt_cfg.get("port") or "1883"),
        "username": str(mqtt_cfg.get("username") or ""),
        "password": str(mqtt_cfg.get("password") or ""),
        "source": "runtime_payload",
    }


def _supervisor_request(base_url: str, token: str) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/services/mqtt"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return {}

    data = body.get("data") if isinstance(body, dict) else {}
    if not isinstance(data, dict):
        return {}
    host = str(data.get("host") or "").strip()
    if not host:
        return {}
    return {
        "host": host,
        "port": str(data.get("port") or "1883"),
        "username": str(data.get("username") or ""),
        "password": str(data.get("password") or ""),
        "source": f"supervisor:{base_url}",
    }


def _from_supervisor() -> dict[str, Any]:
    token = (os.environ.get("SUPERVISOR_TOKEN") or "").strip()
    if not token:
        return {}
    for base in ("http://supervisor", "http://172.30.32.2"):
        resolved = _supervisor_request(base, token)
        if resolved.get("host"):
            return resolved
    return {}


def _from_bashio() -> dict[str, Any]:
    bashio = "/etc/bashio.sh"
    if not os.path.isfile(bashio):
        return {}
    try:
        proc = subprocess.run(
            ["bash", "-c", ". /etc/bashio.sh; bashio::services mqtt host; echo ---; bashio::services mqtt port"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip() and line.strip() != "---"]
    if not lines:
        return {}
    host = lines[0]
    port = lines[1] if len(lines) > 1 else "1883"
    if not host:
        return {}
    return {
        "host": host,
        "port": str(port or "1883"),
        "username": "",
        "password": "",
        "source": "bashio",
    }


def _host_network_fallback(supervisor_cfg: dict[str, Any]) -> dict[str, Any]:
    """On host-network add-ons, Mosquitto is often reachable on loopback."""
    host = str(supervisor_cfg.get("host") or "").strip()
    port_raw = str(supervisor_cfg.get("port") or "1883")
    try:
        port = int(port_raw)
    except ValueError:
        port = 1883

    if host and _tcp_reachable(host, port):
        return supervisor_cfg

    if _tcp_reachable("127.0.0.1", 1883):
        fallback = dict(supervisor_cfg)
        fallback.update({"host": "127.0.0.1", "port": "1883", "source": "host_network:127.0.0.1"})
        return fallback
    return supervisor_cfg


def resolve_mqtt_broker(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}

    for resolver in (
        lambda: _from_mqtt_settings(payload),
        lambda: _from_options_payload(payload),
        _from_env,
        _from_bashio,
        _from_supervisor,
    ):
        resolved = resolver()
        if resolved.get("host"):
            return _host_network_fallback(resolved)
    return {}
