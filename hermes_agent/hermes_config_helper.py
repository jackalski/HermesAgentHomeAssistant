#!/usr/bin/env python3
"""
Hermes Agent config helper for Home Assistant add-on.
Safely reads/writes hermes.json without corrupting it.
"""

import json
import os
import sys
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("HERMES_CONFIG_PATH", "/config/.hermes/hermes.json"))


def read_config():
    if not CONFIG_PATH.exists():
        return None
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError) as e:
        print(f"ERROR: Failed to read config: {e}", file=sys.stderr)
        return None


def write_config(cfg):
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        return True
    except IOError as e:
        print(f"ERROR: Failed to write config: {e}", file=sys.stderr)
        return False


def apply_gateway_settings(mode: str, remote_url: str, bind_mode: str, port: int, enable_openai_api: bool, auth_mode: str, trusted_proxies_csv: str):
    if mode not in ["local", "remote"]:
        print(f"ERROR: Invalid mode '{mode}'. Must be 'local' or 'remote'")
        return False
    if bind_mode not in ["loopback", "lan", "tailnet"]:
        print(f"ERROR: Invalid bind_mode '{bind_mode}'. Must be 'loopback', 'lan', or 'tailnet'")
        return False
    if port < 1 or port > 65535:
        print(f"ERROR: Invalid port {port}. Must be between 1 and 65535")
        return False
    if auth_mode not in ["token", "trusted-proxy"]:
        print(f"ERROR: Invalid auth_mode '{auth_mode}'. Must be 'token' or 'trusted-proxy'")
        return False

    cfg = read_config() or {}
    gateway = cfg.setdefault("gateway", {})
    remote_cfg = gateway.setdefault("remote", {})
    auth = gateway.setdefault("auth", {})
    chat_completions = gateway.setdefault("http", {}).setdefault("endpoints", {}).setdefault("chatCompletions", {})
    trusted_proxies = [p.strip() for p in trusted_proxies_csv.split(",") if p.strip()]

    gateway["mode"] = mode
    remote_cfg["url"] = remote_url
    gateway["bind"] = bind_mode
    gateway["port"] = port
    chat_completions["enabled"] = enable_openai_api
    auth["mode"] = auth_mode
    gateway["trustedProxies"] = trusted_proxies
    if auth_mode == "trusted-proxy":
        auth["trustedProxy"] = {"userHeader": "x-forwarded-user"}
    return write_config(cfg)


def set_control_ui_origins(origins_csv: str, additional_origins_csv: str = "", disable_device_auth: bool = True):
    cfg = read_config() or {}
    gateway = cfg.setdefault("gateway", {})
    control_ui = gateway.setdefault("controlUi", {})
    defaults = [o.strip() for o in origins_csv.split(",") if o.strip()]
    extras = [o.strip() for o in (additional_origins_csv or "").split(",") if o.strip()]
    current = control_ui.get("allowedOrigins", [])
    if not isinstance(current, list):
        current = []
    merged = []
    for origin in [*defaults, *current, *extras]:
        if isinstance(origin, str) and origin and origin not in merged:
            merged.append(origin)
    control_ui["allowedOrigins"] = merged
    control_ui["dangerouslyDisableDeviceAuth"] = bool(disable_device_auth)
    if "pairingMode" in control_ui:
        del control_ui["pairingMode"]
    return write_config(cfg)


def repair_known_invalid_settings():
    cfg = read_config()
    if cfg is None:
        return True
    tools = cfg.get("tools")
    if not isinstance(tools, dict):
        return True
    web = tools.get("web")
    if not isinstance(web, dict):
        return True
    search = web.get("search")
    if not isinstance(search, dict):
        return True
    if search.get("provider") == "brave":
        del search["provider"]
        return write_config(cfg)
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: hermes_config_helper.py <command> [args...]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "apply-gateway-settings":
        mode = sys.argv[2]
        remote_url = sys.argv[3]
        bind_mode = sys.argv[4]
        port = int(sys.argv[5])
        enable_openai_api = sys.argv[6].lower() == "true"
        auth_mode = sys.argv[7]
        trusted_proxies_csv = sys.argv[8]
        sys.exit(0 if apply_gateway_settings(mode, remote_url, bind_mode, port, enable_openai_api, auth_mode, trusted_proxies_csv) else 1)
    elif cmd == "set-control-ui-origins":
        origins_csv = sys.argv[2]
        additional_origins_csv = sys.argv[3] if len(sys.argv) >= 4 else ""
        disable_device_auth = True if len(sys.argv) < 5 else sys.argv[4].strip().lower() == "true"
        sys.exit(0 if set_control_ui_origins(origins_csv, additional_origins_csv, disable_device_auth) else 1)
    elif cmd == "repair-known-invalid-settings":
        sys.exit(0 if repair_known_invalid_settings() else 1)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
