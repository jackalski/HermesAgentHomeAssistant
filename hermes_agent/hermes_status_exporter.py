#!/usr/bin/env python3
"""
Hermes Agent status exporter for Home Assistant add-on.
Collects safe runtime/setup/usage metrics and writes status.json + optional MQTT discovery.
Never logs or publishes secrets.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Reuse config helpers from the add-on helper module.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from hermes_config_helper import (  # noqa: E402
        ADDON_API_KEY_ENV_MAP,
        HERMES_ENV_PATH,
        HERMES_STATE_DIR,
        YAML_CONFIG_PATH,
        _has_api_key,
        has_main_model_api_key,
        model_needs_bootstrap,
        read_yaml_config,
    )
except ImportError:
    # Docker copies to /hermes_status_exporter.py alongside /hermes_config_helper.py
    sys.path.insert(0, "/")
    from hermes_config_helper import (  # type: ignore # noqa: E402
        ADDON_API_KEY_ENV_MAP,
        HERMES_ENV_PATH,
        HERMES_STATE_DIR,
        YAML_CONFIG_PATH,
        _has_api_key,
        has_main_model_api_key,
        model_needs_bootstrap,
        read_yaml_config,
    )

ADDON_VERSION = "0.0.16"
STATUS_FILE = Path("/share/hermes/status.json")
STATUS_HASH_FILE = Path("/share/hermes/.status.json.sha256")
STATE_DB_PATH = HERMES_STATE_DIR / "state.db"

PROVIDER_SENSOR_NAMES = (
    ("openrouter", "OPENROUTER_API_KEY"),
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
    ("google", "GOOGLE_API_KEY"),
    ("minimax", "MINIMAX_API_KEY"),
)

DEVICE_IDENTIFIERS = ["hermes_agent_ha_addon"]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_env_presence() -> dict[str, bool]:
    present: dict[str, bool] = {key: False for key in ADDON_API_KEY_ENV_MAP}
    if not HERMES_ENV_PATH.exists():
        return present
    try:
        for line in HERMES_ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key in present and value.strip():
                present[key] = True
    except OSError:
        pass
    return present


def _provider_configured(env_key: str, api_keys: dict, env_presence: dict[str, bool]) -> bool:
    if _has_api_key(api_keys, env_key):
        return True
    return bool(env_presence.get(env_key))


def _probe_gateway_health(port: int) -> tuple[bool, str | None]:
    url = f"http://127.0.0.1:{port}/api/status"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return True, _utc_now_iso()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        pass
    return False, None


def _hermes_agent_version() -> str:
    for cmd in (["hermes", "--version"],):
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            out = (proc.stdout or proc.stderr or "").strip()
            if out:
                return out.splitlines()[0].strip()
        except (OSError, subprocess.TimeoutExpired):
            continue
    return "unknown"


def _disk_usage_percent() -> int | None:
    try:
        proc = subprocess.run(
            ["df", "-P", "/config"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        lines = (proc.stdout or "").strip().splitlines()
        if len(lines) < 2:
            return None
        parts = lines[1].split()
        if len(parts) < 5:
            return None
        pct = parts[4].rstrip("%")
        return int(pct)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _query_state_db() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "input_tokens_total": None,
        "output_tokens_total": None,
        "total_tokens": None,
        "estimated_cost_usd": None,
        "sessions_total": None,
        "sessions_24h": None,
        "message_count_total": None,
        "tool_call_count_total": None,
        "last_session_at": None,
        "usage_by_model": [],
        "state_db_available": False,
    }
    if not STATE_DB_PATH.exists():
        return defaults

    try:
        conn = sqlite3.connect(f"file:{STATE_DB_PATH}?mode=ro", uri=True, timeout=3)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
              COALESCE(SUM(input_tokens), 0) AS input_tokens,
              COALESCE(SUM(output_tokens), 0) AS output_tokens,
              COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost,
              COALESCE(SUM(message_count), 0) AS message_count,
              COALESCE(SUM(tool_call_count), 0) AS tool_call_count,
              COUNT(*) AS sessions_total,
              MAX(started_at) AS last_session_at
            FROM sessions
            """
        )
        row = cur.fetchone()
        now = time.time()
        day_ago = now - 86400
        cur.execute(
            "SELECT COUNT(*) AS c FROM sessions WHERE started_at >= ?",
            (day_ago,),
        )
        sessions_24h = int(cur.fetchone()["c"])

        cur.execute(
            """
            SELECT model,
                   SUM(input_tokens) AS input_tokens,
                   SUM(output_tokens) AS output_tokens,
                   SUM(estimated_cost_usd) AS estimated_cost_usd
            FROM sessions
            WHERE model IS NOT NULL AND model != ''
            GROUP BY model
            ORDER BY (SUM(input_tokens) + SUM(output_tokens)) DESC
            LIMIT 5
            """
        )
        usage_by_model = []
        for mrow in cur.fetchall():
            usage_by_model.append(
                {
                    "model": mrow["model"],
                    "input_tokens": int(mrow["input_tokens"] or 0),
                    "output_tokens": int(mrow["output_tokens"] or 0),
                    "estimated_cost_usd": float(mrow["estimated_cost_usd"] or 0),
                }
            )

        conn.close()
        input_t = int(row["input_tokens"] or 0)
        output_t = int(row["output_tokens"] or 0)
        last_at = row["last_session_at"]
        last_session_iso = None
        if last_at is not None:
            try:
                last_session_iso = datetime.fromtimestamp(float(last_at), tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            except (TypeError, ValueError, OSError):
                last_session_iso = None

        return {
            "input_tokens_total": input_t,
            "output_tokens_total": output_t,
            "total_tokens": input_t + output_t,
            "estimated_cost_usd": float(row["estimated_cost"] or 0),
            "sessions_total": int(row["sessions_total"] or 0),
            "sessions_24h": sessions_24h,
            "message_count_total": int(row["message_count"] or 0),
            "tool_call_count_total": int(row["tool_call_count"] or 0),
            "last_session_at": last_session_iso,
            "usage_by_model": usage_by_model,
            "state_db_available": True,
        }
    except sqlite3.Error:
        return defaults


def _model_fields(cfg: dict | None) -> tuple[str, str, str]:
    if not cfg:
        return "", "", ""
    model = cfg.get("model")
    main_provider = ""
    main_model = ""
    if isinstance(model, dict):
        main_provider = str(model.get("provider", "") or "").strip()
        main_model = str(model.get("default", "") or "").strip()
    elif isinstance(model, str):
        main_model = model.strip()

    aux_model = ""
    auxiliary = cfg.get("auxiliary")
    if isinstance(auxiliary, dict):
        title = auxiliary.get("title_generation")
        if isinstance(title, dict):
            tp = str(title.get("provider", "") or "").strip()
            tm = str(title.get("model", "") or "").strip()
            aux_model = f"{tp}/{tm}".strip("/") if tp or tm else ""

    return main_provider, main_model, aux_model


def collect_status_snapshot(payload: dict) -> dict[str, Any]:
    gateway_port = int(payload.get("gateway_internal_port", 18789))
    api_keys = payload.get("api_keys", {})
    if not isinstance(api_keys, dict):
        api_keys = {}

    env_presence = _read_env_presence()
    cfg = read_yaml_config()
    if cfg is None:
        cfg = {}

    main_provider, main_model, aux_model = _model_fields(cfg)
    gateway_running, gateway_probe_at = _probe_gateway_health(gateway_port)
    usage = _query_state_db()
    disk_pct = _disk_usage_percent()

    configured_providers = []
    provider_flags: dict[str, bool] = {}
    for name, env_key in PROVIDER_SENSOR_NAMES:
        ok = _provider_configured(env_key, api_keys, env_presence)
        provider_flags[name] = ok
        configured_providers.append({"name": name, "configured": ok})

    any_api_key = has_main_model_api_key(api_keys, env_presence)

    model_ok = bool(cfg) and not model_needs_bootstrap(cfg)
    mcp_ok = Path(HERMES_STATE_DIR / ".mcp_ha_configured").exists()
    assist_ok = str(payload.get("enable_openai_api", "false")).lower() in ("1", "true", "yes")
    ha_token_set = bool(str(payload.get("homeassistant_token", "")).strip())
    setup_complete = any_api_key and model_ok and (mcp_ok if ha_token_set else True)

    hermes_version = _hermes_agent_version()

    snapshot: dict[str, Any] = {
        "schema_version": 1,
        "updated_at": _utc_now_iso(),
        "addon_version": ADDON_VERSION,
        "hermes_agent_version": hermes_version,
        "setup_profile": str(payload.get("setup_profile", "") or ""),
        "access_mode": str(payload.get("access_mode", "") or ""),
        "gateway_mode": str(payload.get("gateway_mode", "") or ""),
        "gateway_running": gateway_running,
        "gateway_health_probe_at": gateway_probe_at,
        "api_key_configured": any_api_key,
        "model_configured": model_ok,
        "mcp_configured": mcp_ok,
        "assist_api_enabled": assist_ok,
        "setup_complete": setup_complete,
        "main_provider": main_provider or "unknown",
        "main_model": main_model or "unknown",
        "auxiliary_title_model": aux_model or "unknown",
        "configured_providers": configured_providers,
        "providers": provider_flags,
        "disk_usage_percent": disk_pct,
        "usage": {
            "input_tokens_total": usage["input_tokens_total"],
            "output_tokens_total": usage["output_tokens_total"],
            "total_tokens": usage["total_tokens"],
            "estimated_cost_usd": usage["estimated_cost_usd"],
            "sessions_total": usage["sessions_total"],
            "sessions_24h": usage["sessions_24h"],
            "message_count_total": usage["message_count_total"],
            "tool_call_count_total": usage["tool_call_count_total"],
            "last_session_at": usage["last_session_at"],
            "usage_by_model": usage["usage_by_model"],
            "state_db_available": usage["state_db_available"],
        },
    }
    return snapshot


def _snapshot_digest(snapshot: dict[str, Any]) -> str:
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_status_file(path: Path, snapshot: dict[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = _snapshot_digest(snapshot)
    if STATUS_HASH_FILE.exists():
        try:
            if STATUS_HASH_FILE.read_text(encoding="utf-8").strip() == digest:
                return True
        except OSError:
            pass

    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        STATUS_HASH_FILE.write_text(digest + "\n", encoding="utf-8")
        return True
    except OSError as e:
        print(f"WARN: Failed to write status file {path}: {e}", file=sys.stderr)
        return False


def _device_block(sw_version: str) -> dict[str, Any]:
    return {
        "identifiers": DEVICE_IDENTIFIERS,
        "name": "Hermes Agent",
        "manufacturer": "Nous Research",
        "model": "Hermes Agent Add-on",
        "sw_version": sw_version,
    }


def resolve_mqtt_config(payload: dict) -> dict[str, Any]:
    try:
        from hermes_mqtt_resolver import resolve_mqtt_broker
    except ImportError:
        sys.path.insert(0, "/")
        from hermes_mqtt_resolver import resolve_mqtt_broker  # type: ignore # noqa: E402

    resolved = resolve_mqtt_broker(payload)
    if resolved.get("host"):
        payload["mqtt"] = resolved
        return resolved
    mqtt_cfg = payload.get("mqtt", {})
    return mqtt_cfg if isinstance(mqtt_cfg, dict) else {}


def _mqtt_pub(mqtt_cfg: dict, topic: str, payload: str, retain: bool = False) -> bool:
    host = mqtt_cfg.get("host", "")
    port = str(mqtt_cfg.get("port", "1883"))
    user = mqtt_cfg.get("username", "")
    password = mqtt_cfg.get("password", "")
    if not host:
        return False

    cmd = [
        "mosquitto_pub",
        "-h",
        host,
        "-p",
        port,
        "-t",
        topic,
        "-m",
        payload,
    ]
    if user:
        cmd.extend(["-u", user])
    if password:
        cmd.extend(["-P", password])
    if retain:
        cmd.append("-r")

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            print(f"WARN: mosquitto_pub failed for {topic}: {err}", file=sys.stderr)
            return False
        return True
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"WARN: mosquitto_pub error for {topic}: {e}", file=sys.stderr)
        return False


def publish_mqtt_discovery(snapshot: dict[str, Any], mqtt_cfg: dict, prefix: str) -> bool:
    if not mqtt_cfg.get("host"):
        return False

    device = _device_block(str(snapshot.get("hermes_agent_version", "unknown")))
    base = prefix.rstrip("/")
    avail_topic = f"{base}/status/availability"

    binaries = [
        ("gateway_running", "Gateway Running", "connectivity"),
        ("api_key_configured", "API Key Configured", None),
        ("model_configured", "Model Configured", None),
        ("mcp_configured", "MCP Configured", None),
        ("assist_api_enabled", "Assist API Enabled", None),
        ("setup_complete", "Setup Complete", None),
    ]
    for name, label, device_class in binaries:
        cfg = {
            "name": f"Hermes {label}",
            "unique_id": f"hermes_agent_ha_addon_{name}",
            "state_topic": f"{base}/status/{name}",
            "payload_on": "true",
            "payload_off": "false",
            "availability_topic": avail_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": device,
        }
        if device_class:
            cfg["device_class"] = device_class
        topic = f"homeassistant/binary_sensor/hermes_agent/{name}/config"
        _mqtt_pub(mqtt_cfg, topic, json.dumps(cfg), retain=True)

    for prov_name, _ in PROVIDER_SENSOR_NAMES:
        cfg = {
            "name": f"Hermes Provider {prov_name.title()}",
            "unique_id": f"hermes_agent_ha_addon_provider_{prov_name}",
            "state_topic": f"{base}/status/provider_{prov_name}",
            "payload_on": "true",
            "payload_off": "false",
            "availability_topic": avail_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": device,
        }
        topic = f"homeassistant/binary_sensor/hermes_agent/provider_{prov_name}/config"
        _mqtt_pub(mqtt_cfg, topic, json.dumps(cfg), retain=True)

    text_sensors = [
        ("main_provider", "Main Provider"),
        ("main_model", "Main Model"),
        ("auxiliary_title_model", "Auxiliary Title Model"),
        ("hermes_agent_version", "Hermes Agent Version"),
        ("addon_version", "Add-on Version"),
        ("setup_profile", "Setup Profile"),
        ("access_mode", "Access Mode"),
        ("gateway_mode", "Gateway Mode"),
    ]
    for key, label in text_sensors:
        cfg = {
            "name": f"Hermes {label}",
            "unique_id": f"hermes_agent_ha_addon_{key}",
            "state_topic": f"{base}/status/{key}",
            "availability_topic": avail_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": device,
        }
        topic = f"homeassistant/sensor/hermes_agent/{key}/config"
        _mqtt_pub(mqtt_cfg, topic, json.dumps(cfg), retain=True)

    numeric_sensors = [
        ("input_tokens_total", "Input Tokens Total", None),
        ("output_tokens_total", "Output Tokens Total", None),
        ("total_tokens", "Total Tokens", None),
        ("estimated_cost_usd", "Estimated Cost USD", "monetary"),
        ("sessions_total", "Sessions Total", None),
        ("sessions_24h", "Sessions 24h", None),
        ("disk_usage_percent", "Disk Usage Percent", None),
        ("message_count_total", "Message Count Total", None),
        ("tool_call_count_total", "Tool Call Count Total", None),
    ]
    for key, label, device_class in numeric_sensors:
        cfg = {
            "name": f"Hermes {label}",
            "unique_id": f"hermes_agent_ha_addon_{key}",
            "state_topic": f"{base}/status/{key}",
            "availability_topic": avail_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "state_class": "total_increasing" if "tokens" in key or "sessions" in key or "message" in key or "tool_call" in key else "measurement",
            "device": device,
        }
        if device_class:
            cfg["device_class"] = device_class
        if key == "disk_usage_percent":
            cfg["unit_of_measurement"] = "%"
        if key == "estimated_cost_usd":
            cfg["unit_of_measurement"] = "USD"
        topic = f"homeassistant/sensor/hermes_agent/{key}/config"
        _mqtt_pub(mqtt_cfg, topic, json.dumps(cfg), retain=True)

    usage_summary_cfg = {
        "name": "Hermes Usage Summary",
        "unique_id": "hermes_agent_ha_addon_usage_summary",
        "state_topic": f"{base}/status/usage_summary_state",
        "json_attributes_topic": f"{base}/status/usage_attributes",
        "availability_topic": avail_topic,
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": device,
    }
    _mqtt_pub(
        mqtt_cfg,
        "homeassistant/sensor/hermes_agent/usage_summary/config",
        json.dumps(usage_summary_cfg),
        retain=True,
    )
    return True


def publish_mqtt_state(snapshot: dict[str, Any], mqtt_cfg: dict, prefix: str) -> bool:
    if not mqtt_cfg.get("host"):
        return False

    base = prefix.rstrip("/")
    _mqtt_pub(mqtt_cfg, f"{base}/status/availability", "online", retain=True)

    def pub_bool(key: str, value: bool):
        _mqtt_pub(mqtt_cfg, f"{base}/status/{key}", "true" if value else "false")

    pub_bool("gateway_running", bool(snapshot.get("gateway_running")))
    pub_bool("api_key_configured", bool(snapshot.get("api_key_configured")))
    pub_bool("model_configured", bool(snapshot.get("model_configured")))
    pub_bool("mcp_configured", bool(snapshot.get("mcp_configured")))
    pub_bool("assist_api_enabled", bool(snapshot.get("assist_api_enabled")))
    pub_bool("setup_complete", bool(snapshot.get("setup_complete")))

    providers = snapshot.get("providers", {})
    if isinstance(providers, dict):
        for prov_name, _ in PROVIDER_SENSOR_NAMES:
            pub_bool(f"provider_{prov_name}", bool(providers.get(prov_name)))

    for key in (
        "main_provider",
        "main_model",
        "auxiliary_title_model",
        "hermes_agent_version",
        "addon_version",
        "setup_profile",
        "access_mode",
        "gateway_mode",
    ):
        _mqtt_pub(mqtt_cfg, f"{base}/status/{key}", str(snapshot.get(key, "unknown")))

    usage = snapshot.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}

    def pub_num(key: str, src_key: str):
        val = usage.get(src_key) if src_key in usage else snapshot.get(src_key)
        if val is None:
            _mqtt_pub(mqtt_cfg, f"{base}/status/{key}", "unknown")
        else:
            _mqtt_pub(mqtt_cfg, f"{base}/status/{key}", str(val))

    pub_num("input_tokens_total", "input_tokens_total")
    pub_num("output_tokens_total", "output_tokens_total")
    pub_num("total_tokens", "total_tokens")
    pub_num("estimated_cost_usd", "estimated_cost_usd")
    pub_num("sessions_total", "sessions_total")
    pub_num("sessions_24h", "sessions_24h")
    pub_num("message_count_total", "message_count_total")
    pub_num("tool_call_count_total", "tool_call_count_total")

    disk = snapshot.get("disk_usage_percent")
    _mqtt_pub(
        mqtt_cfg,
        f"{base}/status/disk_usage_percent",
        "unknown" if disk is None else str(disk),
    )

    attrs = {
        "usage_by_model": usage.get("usage_by_model", []),
        "configured_providers": snapshot.get("configured_providers", []),
        "last_session_at": usage.get("last_session_at"),
        "gateway_health_probe_at": snapshot.get("gateway_health_probe_at"),
        "updated_at": snapshot.get("updated_at"),
    }
    _mqtt_pub(mqtt_cfg, f"{base}/status/usage_attributes", json.dumps(attrs))
    total = usage.get("total_tokens")
    _mqtt_pub(
        mqtt_cfg,
        f"{base}/status/usage_summary_state",
        "unknown" if total is None else str(total),
    )
    return True


def run_once(payload: dict) -> bool:
    snapshot = collect_status_snapshot(payload)
    ok = write_status_file(STATUS_FILE, snapshot)

    mqtt_cfg = resolve_mqtt_config(payload)
    publish_discovery = str(payload.get("publish_mqtt_discovery", "true")).lower() in (
        "1",
        "true",
        "yes",
    )
    prefix = str(payload.get("mqtt_state_prefix", "hermes") or "hermes")

    if mqtt_cfg.get("host"):
        if publish_discovery:
            publish_mqtt_discovery(snapshot, mqtt_cfg, prefix)
        publish_mqtt_state(snapshot, mqtt_cfg, prefix)
    return ok


def run_loop(payload: dict) -> int:
    interval = int(payload.get("status_poll_interval_seconds", 60))
    interval = max(30, min(300, interval))
    mqtt_unavailable_logged = False
    mqtt_available_logged = False

    while True:
        mqtt_cfg = resolve_mqtt_config(payload)
        if mqtt_cfg.get("host"):
            if not mqtt_available_logged:
                source = mqtt_cfg.get("source", "resolved")
                print(
                    f"INFO: MQTT broker resolved ({source}): "
                    f"{mqtt_cfg['host']}:{mqtt_cfg.get('port', '1883')}",
                    file=sys.stderr,
                )
                mqtt_available_logged = True
                mqtt_unavailable_logged = False
        elif not mqtt_unavailable_logged:
            print(
                "INFO: MQTT broker not available yet; status sensors will retry each poll "
                "(ensure Mosquitto add-on is running)",
                file=sys.stderr,
            )
            mqtt_unavailable_logged = True
            mqtt_available_logged = False

        try:
            run_once(payload)
        except Exception as e:
            print(f"WARN: Status exporter cycle failed: {e}", file=sys.stderr)

        time.sleep(interval)


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: hermes_status_exporter.py <collect|write|publish-mqtt|run-loop> '<json-payload>'",
            file=sys.stderr,
        )
        sys.exit(1)

    cmd = sys.argv[1]
    payload: dict = {}
    if len(sys.argv) >= 3:
        try:
            payload = json.loads(sys.argv[2])
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON payload: {e}", file=sys.stderr)
            sys.exit(1)

    if cmd == "collect":
        print(json.dumps(collect_status_snapshot(payload), indent=2))
        sys.exit(0)
    if cmd == "write":
        snapshot = collect_status_snapshot(payload)
        sys.exit(0 if write_status_file(STATUS_FILE, snapshot) else 1)
    if cmd == "publish-mqtt":
        snapshot = collect_status_snapshot(payload)
        mqtt_cfg = resolve_mqtt_config(payload)
        prefix = str(payload.get("mqtt_state_prefix", "hermes") or "hermes")
        ok = True
        if str(payload.get("publish_mqtt_discovery", "true")).lower() in ("1", "true", "yes"):
            ok = publish_mqtt_discovery(snapshot, mqtt_cfg, prefix) and ok
        ok = publish_mqtt_state(snapshot, mqtt_cfg, prefix) and ok
        sys.exit(0 if ok else 1)
    if cmd == "run-loop":
        sys.exit(run_loop(payload))

    print(f"Unknown command: {cmd}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
