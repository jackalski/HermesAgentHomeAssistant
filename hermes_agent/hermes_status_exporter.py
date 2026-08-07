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
import re
import sqlite3
import subprocess
import sys
import threading
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
        _APPROVAL_MODES,
        _REASONING_EFFORTS,
        _has_api_key,
        get_approval_mode,
        get_reasoning_effort,
        has_main_model_api_key,
        model_needs_bootstrap,
        read_yaml_config,
        set_approval_mode,
        set_reasoning_effort,
    )
except ImportError:
    # Docker copies to /hermes_status_exporter.py alongside /hermes_config_helper.py
    sys.path.insert(0, "/")
    from hermes_config_helper import (  # type: ignore # noqa: E402
        ADDON_API_KEY_ENV_MAP,
        HERMES_ENV_PATH,
        HERMES_STATE_DIR,
        YAML_CONFIG_PATH,
        _APPROVAL_MODES,
        _REASONING_EFFORTS,
        _has_api_key,
        get_approval_mode,
        get_reasoning_effort,
        has_main_model_api_key,
        model_needs_bootstrap,
        read_yaml_config,
        set_approval_mode,
        set_reasoning_effort,
    )

def _read_addon_version() -> str:
    """Resolve the live add-on version from config.yaml (baked into the image).

    Falls back to a pinned constant if the file is unavailable so the exporter
    never crashes. Keep the fallback in sync with config.yaml on release.
    """
    fallback = "0.1.2"
    candidates = (
        Path("/addon_config.yaml"),
        Path(__file__).resolve().parent / "config.yaml",
    )
    for path in candidates:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("version:"):
                    value = stripped.split(":", 1)[1].strip().strip("\"'")
                    if value:
                        return value
        except OSError:
            continue
    return fallback


ADDON_VERSION = _read_addon_version()
STATUS_FILE = Path("/share/hermes/status.json")
DISCOVERY_MARKER = HERMES_STATE_DIR / ".mqtt_discovery_published"
STATUS_HASH_FILE = Path("/share/hermes/.status.json.sha256")
STATE_DB_PATH = HERMES_STATE_DIR / "state.db"
CONTROL_SPOOL_DIR = Path("/var/run/hermes-control")
API_SERVER_DEFAULT_PORT = 8642
# HA entity state max is 255; keep summary shorter so UTF-8 multi-byte is safe.
LAST_ERROR_STATE_MAX = 200
ERROR_LOG_CANDIDATES = (
    HERMES_STATE_DIR / "logs" / "errors.log",
    HERMES_STATE_DIR / "logs" / "gateway.log",
    HERMES_STATE_DIR / "gateway.log",
)

PROVIDER_SENSOR_NAMES = (
    ("openrouter", "OPENROUTER_API_KEY"),
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
    ("google", "GOOGLE_API_KEY"),
    ("ollama", "OLLAMA_API_KEY"),
    ("minimax", "MINIMAX_API_KEY"),
    ("xai", "XAI_API_KEY"),
)

CONTROL_BUTTONS = (
    ("restart_gateway", "Restart Gateway", "mdi:restart"),
    ("run_backup", "Run Backup", "mdi:cloud-upload-outline"),
    ("run_cleanup", "Run Cleanup", "mdi:broom"),
    ("refresh_status", "Refresh Status", "mdi:refresh"),
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


def _probe_dashboard_health(port: int) -> tuple[bool, str | None]:
    url = f"http://127.0.0.1:{port}/api/status"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return True, _utc_now_iso()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        pass
    return False, None


def _probe_gateway_process() -> tuple[bool, str | None]:
    try:
        proc = subprocess.run(
            ["pgrep", "-f", r"[h]ermes.*gateway"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0 and (proc.stdout or "").strip():
            return True, _utc_now_iso()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False, None


_HERMES_VERSION_CACHE: str | None = None


def _hermes_agent_version() -> str:
    """The installed binary cannot change without a container restart, so the
    subprocess runs once per process. Failures stay uncached so a late-starting
    install is still picked up on a later poll.
    """
    global _HERMES_VERSION_CACHE
    if _HERMES_VERSION_CACHE is not None:
        return _HERMES_VERSION_CACHE
    try:
        proc = subprocess.run(
            ["hermes", "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    out = (proc.stdout or proc.stderr or "").strip()
    if not out:
        return "unknown"
    _HERMES_VERSION_CACHE = out.splitlines()[0].strip()
    return _HERMES_VERSION_CACHE


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


def _redact_secrets(text: str) -> str:
    out = text
    # Bearer / token-like fragments
    out = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}", r"\1***", out)
    out = re.sub(
        r"(?i)(token|api[_-]?key|password|secret)\s*[:=]\s*\S+",
        r"\1=***",
        out,
    )
    out = re.sub(r"sk-[A-Za-z0-9]{10,}", "sk-***", out)
    return out


def _truncate_state(text: str, max_len: int = LAST_ERROR_STATE_MAX) -> str:
    """Truncate for HA entity state (255-byte limit); keep UTF-8 safe."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _read_last_error() -> tuple[str, str]:
    """Best-effort last error from Hermes logs.

    Returns (state_summary, full_redacted). State is truncated for HA's 255
    character limit; full text is published as a JSON attribute.
    """
    for path in ERROR_LOG_CANDIDATES:
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines[-400:]):
            low = line.lower()
            if "error" not in low and "exception" not in low and "traceback" not in low:
                continue
            cleaned = _redact_secrets(line.strip())
            if cleaned:
                return _truncate_state(cleaned), cleaned[:4000]
    return "", ""


def _probe_assist_api(port: int = API_SERVER_DEFAULT_PORT) -> bool:
    """True when the OpenAI-compatible Assist API is accepting connections on port."""
    try:
        import socket

        with socket.create_connection(("127.0.0.1", int(port)), timeout=2.0):
            return True
    except (OSError, ValueError, TypeError):
        return False


def _control_enabled(payload: dict) -> bool:
    return str(payload.get("enable_control_entities", "false")).lower() in (
        "1",
        "true",
        "yes",
    )


def _write_control_request(name: str, body: str = "") -> bool:
    """Drop a request file for run.sh's control watcher (gateway restart)."""
    try:
        CONTROL_SPOOL_DIR.mkdir(parents=True, exist_ok=True)
        path = CONTROL_SPOOL_DIR / f"{name}.request"
        # Atomic-ish: write temp then rename
        tmp = CONTROL_SPOOL_DIR / f".{name}.request.tmp"
        tmp.write_text(body or _utc_now_iso(), encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError as e:
        print(f"WARN: Failed to write control request {name}: {e}", file=sys.stderr)
        return False


def _run_script(cmd: list[str], label: str) -> bool:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[:200]
            print(f"WARN: {label} exited {proc.returncode}: {err}", file=sys.stderr)
            return False
        print(f"INFO: {label} completed successfully", file=sys.stderr)
        return True
    except FileNotFoundError:
        print(f"WARN: {label} command not found: {cmd[0]}", file=sys.stderr)
        return False
    except subprocess.TimeoutExpired:
        print(f"WARN: {label} timed out", file=sys.stderr)
        return False
    except OSError as e:
        print(f"WARN: {label} failed: {e}", file=sys.stderr)
        return False


USAGE_BREAKDOWN_TOP_N = 10
FAILED_END_REASON_FRAGMENTS = (
    "error",
    "exception",
    "crash",
    "timeout",
    "failed",
    "fail",
    "abort",
    "killed",
)


def _empty_window_metrics() -> dict[str, Any]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "actual_cost_usd": 0.0,
        "cost_usd": 0.0,
        "sessions": 0,
        "api_call_count": 0,
        "message_count": 0,
        "tool_call_count": 0,
    }


def _usage_defaults() -> dict[str, Any]:
    empty = _empty_window_metrics()
    return {
        "input_tokens_total": None,
        "output_tokens_total": None,
        "total_tokens": None,
        "estimated_cost_usd": None,
        "actual_cost_usd": None,
        "cache_read_tokens_total": None,
        "cache_write_tokens_total": None,
        "reasoning_tokens_total": None,
        "api_call_count_total": None,
        "sessions_total": None,
        "sessions_24h": None,
        "message_count_total": None,
        "tool_call_count_total": None,
        "cost_24h": None,
        "tokens_24h": None,
        "cache_hit_ratio": None,
        "reasoning_share": None,
        "overhead_ratio": None,
        "overhead_cost_usd": None,
        "overhead_tokens": None,
        "compression_cost_usd": None,
        "aux_cost_usd": None,
        "last_session_at": None,
        "usage_by_model": [],
        "windows": {"lifetime": dict(empty), "24h": dict(empty), "7d": dict(empty)},
        "by_provider": [],
        "by_model": [],
        "by_task": [],
        "overhead": {
            "aux_tokens": 0,
            "aux_cost_usd": 0.0,
            "compression_tokens": 0,
            "compression_cost_usd": 0.0,
            "compression_splits": 0,
            "overhead_tokens": 0,
            "overhead_cost_usd": 0.0,
            "overhead_ratio": 0.0,
            "cache_hit_ratio": 0.0,
            "reasoning_share": 0.0,
            "failed_session_cost_usd": 0.0,
        },
        "state_db_available": False,
    }


def _table_columns(cur: sqlite3.Cursor, table: str) -> set[str]:
    try:
        cur.execute(f"PRAGMA table_info({table})")
        return {str(row[1]) for row in cur.fetchall()}
    except sqlite3.Error:
        return set()


def _table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    try:
        cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table,),
        )
        return cur.fetchone() is not None
    except sqlite3.Error:
        return False


def _safe_sum_expr(columns: set[str], name: str) -> str:
    if name not in columns:
        return f"0 AS {name}"
    return f"COALESCE(SUM({name}), 0) AS {name}"


def _row_int(row: sqlite3.Row | None, key: str) -> int:
    if row is None:
        return 0
    try:
        return int(row[key] or 0)
    except (KeyError, TypeError, ValueError, IndexError):
        return 0


def _row_float(row: sqlite3.Row | None, key: str) -> float:
    if row is None:
        return 0.0
    try:
        return float(row[key] or 0)
    except (KeyError, TypeError, ValueError, IndexError):
        return 0.0


def _prefer_cost(estimated: float, actual: float) -> float:
    return actual if actual > 0 else estimated


def _session_cost_sql(cols: set[str], *, table_alias: str = "") -> str:
    """Per-row cost expression: prefer positive actual, else estimated."""
    prefix = f"{table_alias}." if table_alias else ""
    has_est = f"{prefix}estimated_cost_usd" if "estimated_cost_usd" in cols else None
    has_act = f"{prefix}actual_cost_usd" if "actual_cost_usd" in cols else None
    if has_act and has_est:
        return (
            f"CASE WHEN COALESCE({has_act}, 0) > 0 THEN {has_act} "
            f"ELSE COALESCE({has_est}, 0) END"
        )
    if has_act:
        return f"COALESCE({has_act}, 0)"
    if has_est:
        return f"COALESCE({has_est}, 0)"
    return "0"


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _window_from_row(row: sqlite3.Row | None) -> dict[str, Any]:
    input_t = _row_int(row, "input_tokens")
    output_t = _row_int(row, "output_tokens")
    cache_read = _row_int(row, "cache_read_tokens")
    cache_write = _row_int(row, "cache_write_tokens")
    reasoning = _row_int(row, "reasoning_tokens")
    estimated = _row_float(row, "estimated_cost_usd")
    actual = _row_float(row, "actual_cost_usd")
    cost = _row_float(row, "cost_usd")
    if cost <= 0:
        cost = _prefer_cost(estimated, actual)
    return {
        "input_tokens": input_t,
        "output_tokens": output_t,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "reasoning_tokens": reasoning,
        "total_tokens": input_t + output_t,
        "estimated_cost_usd": estimated,
        "actual_cost_usd": actual,
        "cost_usd": cost,
        "sessions": _row_int(row, "sessions"),
        "api_call_count": _row_int(row, "api_call_count"),
        "message_count": _row_int(row, "message_count"),
        "tool_call_count": _row_int(row, "tool_call_count"),
    }


def _aggregate_sessions_window(
    cur: sqlite3.Cursor,
    cols: set[str],
    *,
    since: float | None = None,
) -> dict[str, Any]:
    cost_sql = _session_cost_sql(cols)
    select_parts = [
        "COALESCE(SUM(input_tokens), 0) AS input_tokens",
        "COALESCE(SUM(output_tokens), 0) AS output_tokens",
        "COALESCE(SUM(message_count), 0) AS message_count",
        "COALESCE(SUM(tool_call_count), 0) AS tool_call_count",
        "COUNT(*) AS sessions",
        f"COALESCE(SUM({cost_sql}), 0) AS cost_usd",
    ]
    for name in (
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "estimated_cost_usd",
        "actual_cost_usd",
        "api_call_count",
    ):
        select_parts.append(_safe_sum_expr(cols, name))

    sql = f"SELECT {', '.join(select_parts)} FROM sessions"
    params: tuple[Any, ...] = ()
    if since is not None:
        sql += " WHERE started_at >= ?"
        params = (since,)
    cur.execute(sql, params)
    return _window_from_row(cur.fetchone())


def _top_n_with_other(
    rows: list[dict[str, Any]],
    *,
    key_fields: tuple[str, ...],
    top_n: int = USAGE_BREAKDOWN_TOP_N,
) -> list[dict[str, Any]]:
    if len(rows) <= top_n:
        return rows
    kept = rows[:top_n]
    rest = rows[top_n:]
    other: dict[str, Any] = {k: "other" for k in key_fields}
    for metric in (
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "total_tokens",
        "estimated_cost_usd",
        "actual_cost_usd",
        "cost_usd",
        "api_call_count",
        "sessions",
    ):
        other[metric] = 0
    for row in rest:
        for metric in (
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "reasoning_tokens",
            "total_tokens",
            "api_call_count",
            "sessions",
        ):
            other[metric] = int(other[metric]) + int(row.get(metric) or 0)
        for metric in ("estimated_cost_usd", "actual_cost_usd", "cost_usd"):
            other[metric] = float(other[metric]) + float(row.get(metric) or 0)
    kept.append(other)
    return kept


def _aggregate_model_usage(
    cur: sqlite3.Cursor,
    *,
    since: float | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (by_provider, by_model, by_task) from session_model_usage when present."""
    if not _table_exists(cur, "session_model_usage"):
        return [], [], []

    smu_cols = _table_columns(cur, "session_model_usage")
    required = {"session_id", "model", "input_tokens", "output_tokens"}
    if not required.issubset(smu_cols):
        return [], [], []

    has_provider = "billing_provider" in smu_cols
    has_task = "task" in smu_cols
    has_cache_read = "cache_read_tokens" in smu_cols
    has_cache_write = "cache_write_tokens" in smu_cols
    has_reasoning = "reasoning_tokens" in smu_cols
    has_est = "estimated_cost_usd" in smu_cols
    has_act = "actual_cost_usd" in smu_cols
    has_api = "api_call_count" in smu_cols

    where = ""
    params: tuple[Any, ...] = ()
    if since is not None:
        where = " WHERE s.started_at >= ?"
        params = (since,)

    provider_expr = "COALESCE(NULLIF(u.billing_provider, ''), 'unknown')" if has_provider else "'unknown'"
    task_expr = "COALESCE(u.task, '')" if has_task else "''"
    cache_read_expr = "COALESCE(SUM(u.cache_read_tokens), 0)" if has_cache_read else "0"
    cache_write_expr = "COALESCE(SUM(u.cache_write_tokens), 0)" if has_cache_write else "0"
    reasoning_expr = "COALESCE(SUM(u.reasoning_tokens), 0)" if has_reasoning else "0"
    est_expr = "COALESCE(SUM(u.estimated_cost_usd), 0)" if has_est else "0"
    act_expr = "COALESCE(SUM(u.actual_cost_usd), 0)" if has_act else "0"
    api_expr = "COALESCE(SUM(u.api_call_count), 0)" if has_api else "0"

    def _fetch(select_group: str, group_by: str, label_keys: tuple[str, ...]) -> list[dict[str, Any]]:
        sql = f"""
            SELECT {select_group},
                   COALESCE(SUM(u.input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(u.output_tokens), 0) AS output_tokens,
                   {cache_read_expr} AS cache_read_tokens,
                   {cache_write_expr} AS cache_write_tokens,
                   {reasoning_expr} AS reasoning_tokens,
                   {est_expr} AS estimated_cost_usd,
                   {act_expr} AS actual_cost_usd,
                   {api_expr} AS api_call_count,
                   COUNT(DISTINCT u.session_id) AS sessions
            FROM session_model_usage u
            JOIN sessions s ON s.id = u.session_id
            {where}
            GROUP BY {group_by}
            ORDER BY ({est_expr} + {act_expr}) DESC,
                     (SUM(u.input_tokens) + SUM(u.output_tokens)) DESC
        """
        cur.execute(sql, params)
        out: list[dict[str, Any]] = []
        for row in cur.fetchall():
            estimated = float(row["estimated_cost_usd"] or 0)
            actual = float(row["actual_cost_usd"] or 0)
            input_t = int(row["input_tokens"] or 0)
            output_t = int(row["output_tokens"] or 0)
            entry: dict[str, Any] = {
                "input_tokens": input_t,
                "output_tokens": output_t,
                "cache_read_tokens": int(row["cache_read_tokens"] or 0),
                "cache_write_tokens": int(row["cache_write_tokens"] or 0),
                "reasoning_tokens": int(row["reasoning_tokens"] or 0),
                "total_tokens": input_t + output_t,
                "estimated_cost_usd": estimated,
                "actual_cost_usd": actual,
                "cost_usd": _prefer_cost(estimated, actual),
                "api_call_count": int(row["api_call_count"] or 0),
                "sessions": int(row["sessions"] or 0),
            }
            for key in label_keys:
                entry[key] = row[key]
            if "task" in entry:
                entry["label"] = "main" if entry["task"] == "" else str(entry["task"])
            out.append(entry)
        return out

    by_provider = _top_n_with_other(
        _fetch(f"{provider_expr} AS provider", provider_expr, ("provider",)),
        key_fields=("provider",),
    )
    model_expr = "COALESCE(NULLIF(u.model, ''), 'unknown')"
    by_model = _top_n_with_other(
        _fetch(
            f"{provider_expr} AS provider, {model_expr} AS model",
            f"{provider_expr}, {model_expr}",
            ("provider", "model"),
        ),
        key_fields=("provider", "model"),
    )
    by_task = _top_n_with_other(
        _fetch(f"{task_expr} AS task", task_expr, ("task",)),
        key_fields=("task",),
    )
    return by_provider, by_model, by_task


def _fallback_by_model_from_sessions(
    cur: sqlite3.Cursor,
    cols: set[str],
) -> list[dict[str, Any]]:
    est = "COALESCE(SUM(estimated_cost_usd), 0)" if "estimated_cost_usd" in cols else "0"
    act = "COALESCE(SUM(actual_cost_usd), 0)" if "actual_cost_usd" in cols else "0"
    cache_read = "COALESCE(SUM(cache_read_tokens), 0)" if "cache_read_tokens" in cols else "0"
    cache_write = "COALESCE(SUM(cache_write_tokens), 0)" if "cache_write_tokens" in cols else "0"
    reasoning = "COALESCE(SUM(reasoning_tokens), 0)" if "reasoning_tokens" in cols else "0"
    api = "COALESCE(SUM(api_call_count), 0)" if "api_call_count" in cols else "0"
    cur.execute(
        f"""
        SELECT COALESCE(NULLIF(model, ''), 'unknown') AS model,
               COALESCE(SUM(input_tokens), 0) AS input_tokens,
               COALESCE(SUM(output_tokens), 0) AS output_tokens,
               {cache_read} AS cache_read_tokens,
               {cache_write} AS cache_write_tokens,
               {reasoning} AS reasoning_tokens,
               {est} AS estimated_cost_usd,
               {act} AS actual_cost_usd,
               {api} AS api_call_count,
               COUNT(*) AS sessions
        FROM sessions
        WHERE model IS NOT NULL AND model != ''
        GROUP BY model
        ORDER BY ({est} + {act}) DESC, (SUM(input_tokens) + SUM(output_tokens)) DESC
        """
    )
    rows: list[dict[str, Any]] = []
    for mrow in cur.fetchall():
        estimated = float(mrow["estimated_cost_usd"] or 0)
        actual = float(mrow["actual_cost_usd"] or 0)
        input_t = int(mrow["input_tokens"] or 0)
        output_t = int(mrow["output_tokens"] or 0)
        model = str(mrow["model"] or "unknown")
        provider = model.split("/", 1)[0] if "/" in model else "unknown"
        rows.append(
            {
                "provider": provider,
                "model": model,
                "input_tokens": input_t,
                "output_tokens": output_t,
                "cache_read_tokens": int(mrow["cache_read_tokens"] or 0),
                "cache_write_tokens": int(mrow["cache_write_tokens"] or 0),
                "reasoning_tokens": int(mrow["reasoning_tokens"] or 0),
                "total_tokens": input_t + output_t,
                "estimated_cost_usd": estimated,
                "actual_cost_usd": actual,
                "cost_usd": _prefer_cost(estimated, actual),
                "api_call_count": int(mrow["api_call_count"] or 0),
                "sessions": int(mrow["sessions"] or 0),
            }
        )
    return _top_n_with_other(rows, key_fields=("provider", "model"))


def _sum_task_metrics(by_task: list[dict[str, Any]], *, aux_only: bool = False, task_name: str | None = None) -> tuple[int, float]:
    tokens = 0
    cost = 0.0
    for row in by_task:
        task = str(row.get("task", ""))
        if aux_only and task == "":
            continue
        if task_name is not None and task != task_name:
            continue
        tokens += int(row.get("total_tokens") or 0) + int(row.get("reasoning_tokens") or 0)
        cost += float(row.get("cost_usd") or 0)
    return tokens, cost


def _failed_session_cost(cur: sqlite3.Cursor, cols: set[str]) -> float:
    if "end_reason" not in cols:
        return 0.0
    cost_expr = _session_cost_sql(cols)
    likes = " OR ".join(["LOWER(COALESCE(end_reason, '')) LIKE ?" for _ in FAILED_END_REASON_FRAGMENTS])
    params = tuple(f"%{frag}%" for frag in FAILED_END_REASON_FRAGMENTS)
    cur.execute(f"SELECT COALESCE(SUM({cost_expr}), 0) AS c FROM sessions WHERE {likes}", params)
    return _row_float(cur.fetchone(), "c")


def _query_state_db() -> dict[str, Any]:
    defaults = _usage_defaults()
    if not STATE_DB_PATH.exists():
        return defaults

    try:
        conn = sqlite3.connect(f"file:{STATE_DB_PATH}?mode=ro", uri=True, timeout=3)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if not _table_exists(cur, "sessions"):
            conn.close()
            return defaults

        cols = _table_columns(cur, "sessions")
        now = time.time()
        day_ago = now - 86400
        week_ago = now - 7 * 86400

        lifetime = _aggregate_sessions_window(cur, cols)
        win_24h = _aggregate_sessions_window(cur, cols, since=day_ago)
        win_7d = _aggregate_sessions_window(cur, cols, since=week_ago)

        cur.execute("SELECT MAX(started_at) AS last_session_at FROM sessions")
        last_at = cur.fetchone()["last_session_at"]
        last_session_iso = None
        if last_at is not None:
            try:
                last_session_iso = datetime.fromtimestamp(float(last_at), tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            except (TypeError, ValueError, OSError):
                last_session_iso = None

        by_provider, by_model, by_task = _aggregate_model_usage(cur)
        if not by_model:
            by_model = _fallback_by_model_from_sessions(cur, cols)
        usage_by_model = [
            {
                "model": row.get("model"),
                "input_tokens": row.get("input_tokens"),
                "output_tokens": row.get("output_tokens"),
                "estimated_cost_usd": row.get("estimated_cost_usd"),
                "actual_cost_usd": row.get("actual_cost_usd"),
                "cache_read_tokens": row.get("cache_read_tokens"),
                "cache_write_tokens": row.get("cache_write_tokens"),
                "reasoning_tokens": row.get("reasoning_tokens"),
                "cost_usd": row.get("cost_usd"),
                "provider": row.get("provider"),
            }
            for row in by_model
            if row.get("model") != "other"
        ][:5]

        aux_tokens, aux_cost = _sum_task_metrics(by_task, aux_only=True)
        compression_tokens, compression_cost = _sum_task_metrics(by_task, task_name="compression")

        compression_splits = 0
        if "parent_session_id" in cols:
            cur.execute(
                "SELECT COUNT(*) AS c FROM sessions WHERE parent_session_id IS NOT NULL AND parent_session_id != ''"
            )
            compression_splits = _row_int(cur.fetchone(), "c")

        failed_cost = _failed_session_cost(cur, cols)
        conn.close()

        input_t = lifetime["input_tokens"]
        output_t = lifetime["output_tokens"]
        cache_read = lifetime["cache_read_tokens"]
        cache_write = lifetime["cache_write_tokens"]
        reasoning = lifetime["reasoning_tokens"]
        estimated = lifetime["estimated_cost_usd"]
        actual = lifetime["actual_cost_usd"]
        total_cost = lifetime["cost_usd"]

        overhead_tokens = aux_tokens + reasoning + cache_write
        # Prefer attributed aux+compression costs; approximate reasoning/cache write share from session totals.
        session_overhead_cost = 0.0
        if total_cost > 0 and (input_t + output_t + reasoning + cache_write) > 0:
            session_overhead_cost = total_cost * (
                (reasoning + cache_write) / float(input_t + output_t + reasoning + cache_write)
            )
        overhead_cost = aux_cost + session_overhead_cost
        cache_hit_ratio = _ratio(cache_read, input_t + cache_read)
        reasoning_share = _ratio(reasoning, output_t + reasoning)
        overhead_ratio = _ratio(overhead_cost, total_cost)

        overhead = {
            "aux_tokens": aux_tokens,
            "aux_cost_usd": round(aux_cost, 6),
            "compression_tokens": compression_tokens,
            "compression_cost_usd": round(compression_cost, 6),
            "compression_splits": compression_splits,
            "overhead_tokens": overhead_tokens,
            "overhead_cost_usd": round(overhead_cost, 6),
            "overhead_ratio": overhead_ratio,
            "cache_hit_ratio": cache_hit_ratio,
            "reasoning_share": reasoning_share,
            "failed_session_cost_usd": round(failed_cost, 6),
        }

        return {
            "input_tokens_total": input_t,
            "output_tokens_total": output_t,
            "total_tokens": input_t + output_t,
            "estimated_cost_usd": estimated,
            "actual_cost_usd": actual,
            "cache_read_tokens_total": cache_read,
            "cache_write_tokens_total": cache_write,
            "reasoning_tokens_total": reasoning,
            "api_call_count_total": lifetime["api_call_count"],
            "sessions_total": lifetime["sessions"],
            "sessions_24h": win_24h["sessions"],
            "message_count_total": lifetime["message_count"],
            "tool_call_count_total": lifetime["tool_call_count"],
            "cost_24h": win_24h["cost_usd"],
            "tokens_24h": win_24h["total_tokens"],
            "cache_hit_ratio": cache_hit_ratio,
            "reasoning_share": reasoning_share,
            "overhead_ratio": overhead_ratio,
            "overhead_cost_usd": overhead["overhead_cost_usd"],
            "overhead_tokens": overhead_tokens,
            "compression_cost_usd": overhead["compression_cost_usd"],
            "aux_cost_usd": overhead["aux_cost_usd"],
            "last_session_at": last_session_iso,
            "usage_by_model": usage_by_model,
            "windows": {"lifetime": lifetime, "24h": win_24h, "7d": win_7d},
            "by_provider": by_provider,
            "by_model": by_model,
            "by_task": by_task,
            "overhead": overhead,
            "state_db_available": True,
        }
    except sqlite3.Error:
        return defaults


def _format_provider_model(
    provider: str,
    model: str,
    *,
    fallback_provider: str = "",
    fallback_model: str = "",
) -> str:
    """Render a stable provider/model label for MQTT status sensors."""
    provider = (provider or "").strip()
    model = (model or "").strip()
    fallback_provider = (fallback_provider or "").strip()
    fallback_model = (fallback_model or "").strip()
    prov_lower = provider.lower()

    if prov_lower in ("", "auto"):
        if model:
            if "/" in model:
                return model
            if fallback_provider:
                return f"{fallback_provider}/{model}"
            return model
        if fallback_provider and fallback_model:
            return _format_provider_model(fallback_provider, fallback_model)
        return ""

    if not model:
        return provider

    if "/" in model:
        prefix = model.split("/", 1)[0].lower()
        if prefix == prov_lower:
            return model
    return f"{provider}/{model}"


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

    # Reflect the configured main model (not bootstrapped auxiliary.title_generation).
    aux_model = _format_provider_model(main_provider, main_model)

    return main_provider, main_model, aux_model


def collect_status_snapshot(payload: dict) -> dict[str, Any]:
    dashboard_port = int(payload.get("dashboard_internal_port", 0) or 0)
    api_keys = payload.get("api_keys", {})
    if not isinstance(api_keys, dict):
        api_keys = {}

    env_presence = _read_env_presence()
    cfg = read_yaml_config()
    if cfg is None:
        cfg = {}

    main_provider, main_model, aux_model = _model_fields(cfg)
    # gateway_running reflects the messaging gateway (hermes gateway run).
    gateway_running, gateway_probe_at = _probe_gateway_process()
    dashboard_running = False
    dashboard_probe_at = None
    if dashboard_port > 0:
        dashboard_running, dashboard_probe_at = _probe_dashboard_health(dashboard_port)
    if not gateway_running and dashboard_running:
        gateway_running = True
        gateway_probe_at = dashboard_probe_at
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
    # Prefer a live probe so the sensor means "Assist API is answering", not
    # merely "enable_openai_api is ticked". Fall back to the option when the
    # option is off (probe would always fail) or when probing is unavailable.
    assist_option = str(payload.get("enable_openai_api", "false")).lower() in (
        "1",
        "true",
        "yes",
    )
    assist_ok = _probe_assist_api() if assist_option else False
    ha_token_set = bool(str(payload.get("homeassistant_token", "")).strip())
    setup_complete = any_api_key and model_ok and (mcp_ok if ha_token_set else True)
    last_error_summary, last_error_full = _read_last_error()
    gateway_ready = bool(gateway_running) and bool(setup_complete)

    hermes_version = _hermes_agent_version()

    stt_block = cfg.get("stt") if isinstance(cfg.get("stt"), dict) else {}
    tts_block = cfg.get("tts") if isinstance(cfg.get("tts"), dict) else {}
    agent_block = cfg.get("agent") if isinstance(cfg.get("agent"), dict) else {}
    hooks_block = cfg.get("hooks") if isinstance(cfg.get("hooks"), dict) else {}
    outbound = hooks_block.get("outbound")
    outbound_enabled = isinstance(outbound, list) and len(outbound) > 0
    max_turns_val = agent_block.get("max_turns")
    try:
        max_turns_out = int(max_turns_val) if max_turns_val is not None else 0
    except (TypeError, ValueError):
        max_turns_out = 0

    snapshot: dict[str, Any] = {
        "schema_version": 2,
        "updated_at": _utc_now_iso(),
        "addon_version": ADDON_VERSION,
        "hermes_agent_version": hermes_version,
        "setup_profile": str(payload.get("setup_profile", "") or ""),
        "access_mode": str(payload.get("access_mode", "") or ""),
        "gateway_mode": str(payload.get("gateway_mode", "") or ""),
        "gateway_running": gateway_running,
        "gateway_ready": gateway_ready,
        "gateway_health_probe_at": gateway_probe_at,
        "last_error": last_error_summary or "none",
        "last_error_full": last_error_full or "none",
        "api_key_configured": any_api_key,
        "model_configured": model_ok,
        "mcp_configured": mcp_ok,
        "assist_api_enabled": assist_ok,
        "setup_complete": setup_complete,
        "approval_mode": get_approval_mode(),
        "reasoning_effort": get_reasoning_effort(),
        "stt_provider": str(stt_block.get("provider") or "unknown"),
        "tts_provider": str(tts_block.get("provider") or "unknown"),
        "max_turns": max_turns_out if max_turns_out > 0 else "unknown",
        "outbound_events_enabled": outbound_enabled,
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
            "actual_cost_usd": usage["actual_cost_usd"],
            "cache_read_tokens_total": usage["cache_read_tokens_total"],
            "cache_write_tokens_total": usage["cache_write_tokens_total"],
            "reasoning_tokens_total": usage["reasoning_tokens_total"],
            "api_call_count_total": usage["api_call_count_total"],
            "sessions_total": usage["sessions_total"],
            "sessions_24h": usage["sessions_24h"],
            "message_count_total": usage["message_count_total"],
            "tool_call_count_total": usage["tool_call_count_total"],
            "cost_24h": usage["cost_24h"],
            "tokens_24h": usage["tokens_24h"],
            "cache_hit_ratio": usage["cache_hit_ratio"],
            "reasoning_share": usage["reasoning_share"],
            "overhead_ratio": usage["overhead_ratio"],
            "overhead_cost_usd": usage["overhead_cost_usd"],
            "overhead_tokens": usage["overhead_tokens"],
            "compression_cost_usd": usage["compression_cost_usd"],
            "aux_cost_usd": usage["aux_cost_usd"],
            "last_session_at": usage["last_session_at"],
            "usage_by_model": usage["usage_by_model"],
            "windows": usage["windows"],
            "by_provider": usage["by_provider"],
            "by_model": usage["by_model"],
            "by_task": usage["by_task"],
            "overhead": usage["overhead"],
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
        "name": "Hermes Agent Integration",
        "manufacturer": "Nous Research",
        "model": "Hermes Agent Integration Add-on",
        "sw_version": sw_version,
    }


def _discovery_entity_id(domain: str, slug: str) -> dict[str, str]:
    """Pin entity_id slug so HA does not prefix the device name.

    Without this, newer Home Assistant often creates IDs like
    sensor.hermes_agent_integration_hermes_last_error. The usage dashboard and
    package expect sensor.hermes_* / binary_sensor.hermes_* / button.hermes_*.

    HA 2025.10+ prefers default_entity_id (domain.slug); object_id is deprecated
    and ignored by Core 2026.4+. Publish both during the transition window.
    """
    return {
        "object_id": slug,
        "default_entity_id": f"{domain}.{slug}",
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


def _discovery_marker_key(prefix: str, control_enabled: bool = False) -> str:
    ctrl = "ctrl1" if control_enabled else "ctrl0"
    return f"{ADDON_VERSION}:{prefix.rstrip('/')}:{ctrl}"


def discovery_needs_publish(prefix: str, control_enabled: bool = False) -> bool:
    expected = _discovery_marker_key(prefix, control_enabled)
    try:
        return DISCOVERY_MARKER.read_text(encoding="utf-8").strip() != expected
    except OSError:
        return True


def mark_discovery_published(prefix: str, control_enabled: bool = False) -> None:
    try:
        DISCOVERY_MARKER.parent.mkdir(parents=True, exist_ok=True)
        DISCOVERY_MARKER.write_text(
            _discovery_marker_key(prefix, control_enabled) + "\n", encoding="utf-8"
        )
    except OSError as e:
        print(f"WARN: Failed to write MQTT discovery marker: {e}", file=sys.stderr)


class MqttPublisher:
    """Persistent MQTT client — one broker connection reused across poll cycles."""

    CLIENT_ID = "hermes-agent-integration"
    KEEPALIVE = 60
    CONNECT_TIMEOUT = 15
    PUBLISH_TIMEOUT = 10
    # One poll cycle emits ~50 topics; keep them all in flight at once.
    MAX_INFLIGHT = 64

    def __init__(self) -> None:
        self._client: Any = None
        self._cfg_key: str | None = None
        self._loop_running = False
        self._availability_topic: str | None = None
        self._pending: list[tuple[str, Any]] = []
        self._wake = threading.Event()
        self._command_handler: Any = None
        self._command_topic: str | None = None
        self._subscribed_command = False

    def set_command_handler(self, topic: str | None, handler: Any) -> None:
        """Register (or clear) the MQTT command subscription callback."""
        self._command_topic = topic
        self._command_handler = handler
        self._subscribed_command = False
        if self._client is not None and self.is_ready():
            self._apply_command_subscription()

    def request_wake(self) -> None:
        self._wake.set()

    def wait_interval(self, seconds: float) -> None:
        """Sleep up to `seconds`, but return early if request_wake() is called."""
        self._wake.clear()
        self._wake.wait(timeout=max(1.0, seconds))

    def is_ready(self) -> bool:
        if self._client is None:
            return False
        try:
            return bool(self._client.is_connected())
        except Exception:
            return False

    def disconnect(self) -> None:
        if self._client is not None:
            try:
                if self._availability_topic and self.is_ready():
                    info = self._client.publish(
                        self._availability_topic, "offline", qos=1, retain=True
                    )
                    info.wait_for_publish(timeout=2)
                if self._loop_running:
                    self._client.loop_stop()
                    self._loop_running = False
                self._client.disconnect()
            except Exception:
                pass
        self._client = None
        self._cfg_key = None
        self._pending = []
        self._subscribed_command = False

    def _on_message(self, _client: Any, _userdata: Any, msg: Any) -> None:
        if self._command_handler is None:
            return
        try:
            topic = getattr(msg, "topic", "") or ""
            payload = msg.payload
            if isinstance(payload, bytes):
                text = payload.decode("utf-8", errors="replace")
            else:
                text = str(payload or "")
            self._command_handler(topic, text)
        except Exception as e:
            print(f"WARN: MQTT command handler failed: {e}", file=sys.stderr)

    def _apply_command_subscription(self) -> None:
        if self._client is None or not self.is_ready():
            return
        try:
            if self._command_topic and self._command_handler is not None:
                self._client.on_message = self._on_message
                self._client.subscribe(self._command_topic, qos=1)
                self._subscribed_command = True
                print(f"INFO: Subscribed to MQTT commands: {self._command_topic}", file=sys.stderr)
            else:
                # Best-effort unsubscribe when control is disabled.
                if self._subscribed_command and self._command_topic:
                    try:
                        self._client.unsubscribe(self._command_topic)
                    except Exception:
                        pass
                self._subscribed_command = False
        except Exception as e:
            print(f"WARN: MQTT command subscribe failed: {e}", file=sys.stderr)

    def _make_client(self) -> Any:
        import paho.mqtt.client as mqtt

        client = None
        for callback_api in (
            getattr(mqtt.CallbackAPIVersion, "VERSION2", None),
            getattr(mqtt.CallbackAPIVersion, "VERSION1", None),
        ):
            if callback_api is None:
                continue
            try:
                client = mqtt.Client(
                    callback_api,
                    client_id=self.CLIENT_ID,
                    protocol=mqtt.MQTTv311,
                )
                break
            except (AttributeError, TypeError):
                continue
        if client is None:
            client = mqtt.Client(client_id=self.CLIENT_ID, protocol=mqtt.MQTTv311)

        client.max_inflight_messages_set(self.MAX_INFLIGHT)
        if self._availability_topic:
            # Without a will, an add-on crash leaves every entity "available"
            # with frozen values until the next successful publish.
            client.will_set(self._availability_topic, "offline", qos=1, retain=True)
        return client

    def ensure_connected(self, mqtt_cfg: dict, availability_topic: str | None = None) -> bool:
        host = str(mqtt_cfg.get("host", "") or "").strip()
        if not host:
            self.disconnect()
            return False

        port_raw = str(mqtt_cfg.get("port", "1883") or "1883").strip()
        try:
            port = int(port_raw)
        except ValueError:
            print(f"WARN: Invalid MQTT port '{port_raw}'; using 1883", file=sys.stderr)
            port = 1883
        user = str(mqtt_cfg.get("username", "") or "")
        password = str(mqtt_cfg.get("password", "") or "")
        cfg_key = f"{host}:{port}:{user}"

        if (
            self._client is not None
            and self._cfg_key == cfg_key
            and self._availability_topic == availability_topic
            and self.is_ready()
        ):
            if self._command_topic and self._command_handler and not self._subscribed_command:
                self._apply_command_subscription()
            return True

        self.disconnect()
        self._availability_topic = availability_topic
        try:
            client = self._make_client()
            if user:
                client.username_pw_set(user, password or None)
            client.connect(host, port, keepalive=self.KEEPALIVE)
            client.loop_start()
            for _ in range(50):
                if client.is_connected():
                    break
                time.sleep(0.1)
            if not client.is_connected():
                raise RuntimeError("broker did not acknowledge connection")
            self._client = client
            self._cfg_key = cfg_key
            self._loop_running = True
            self._apply_command_subscription()
            return True
        except Exception as e:
            print(f"WARN: MQTT connect failed ({host}:{port}): {e}", file=sys.stderr)
            self.disconnect()
            return False

    def publish(self, topic: str, payload: str, retain: bool = False) -> bool:
        """Hand the message to paho and return; call flush() to await PUBACKs.

        Waiting per message would serialise ~50 broker round-trips per cycle.
        """
        if not self.is_ready():
            return False
        try:
            info = self._client.publish(topic, payload, qos=1, retain=retain)
        except Exception as e:
            print(f"WARN: MQTT publish failed for {topic}: {e}", file=sys.stderr)
            self.disconnect()
            return False
        # rc != 0 means the client never queued the message (not connected /
        # queue full). wait_for_publish would only hang until timeout.
        rc = getattr(info, "rc", 0)
        if rc not in (0, None):
            print(
                f"WARN: MQTT publish rejected locally for {topic} (rc={rc})",
                file=sys.stderr,
            )
            self.disconnect()
            return False
        self._pending.append((topic, info))
        return True

    def flush(self) -> bool:
        """Await every queued publish within one shared timeout window."""
        pending, self._pending = self._pending, []
        if not pending:
            return True
        deadline = time.monotonic() + self.PUBLISH_TIMEOUT
        ok = True
        timed_out = 0
        first_timeout_topic: str | None = None
        for topic, info in pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out += 1
                if first_timeout_topic is None:
                    first_timeout_topic = topic
                ok = False
                continue
            try:
                if not info.wait_for_publish(timeout=remaining):
                    timed_out += 1
                    if first_timeout_topic is None:
                        first_timeout_topic = topic
                    ok = False
            except Exception as e:
                print(f"WARN: MQTT publish failed for {topic}: {e}", file=sys.stderr)
                ok = False
        if timed_out:
            print(
                f"WARN: MQTT publish timed out for {timed_out}/{len(pending)} topics "
                f"(first: {first_timeout_topic}). Broker accepted the TCP session but "
                f"did not PUBACK — check ACL write access to homeassistant/# and your "
                f"state prefix, credentials, and that Mosquitto is reachable.",
                file=sys.stderr,
            )
        return ok


def publish_mqtt_discovery(
    snapshot: dict[str, Any],
    publisher: MqttPublisher,
    prefix: str,
    control_enabled: bool = False,
) -> bool:
    if not publisher.is_ready():
        return False

    device = _device_block(str(snapshot.get("hermes_agent_version", "unknown")))
    base = prefix.rstrip("/")
    avail_topic = f"{base}/status/availability"

    binaries = [
        ("gateway_running", "Gateway Running", "connectivity"),
        ("gateway_ready", "Gateway Ready", "connectivity"),
        ("api_key_configured", "API Key Configured", None),
        ("model_configured", "Model Configured", None),
        ("mcp_configured", "MCP Configured", None),
        ("assist_api_enabled", "Assist API Enabled", None),
        ("outbound_events_enabled", "Outbound Events Enabled", None),
        ("setup_complete", "Setup Complete", None),
    ]
    for name, label, device_class in binaries:
        cfg = {
            "name": f"Hermes {label}",
            "unique_id": f"hermes_agent_ha_addon_{name}",
            **_discovery_entity_id("binary_sensor", f"hermes_{name}"),
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
        publisher.publish(topic, json.dumps(cfg), retain=True)

    for prov_name, _ in PROVIDER_SENSOR_NAMES:
        cfg = {
            "name": f"Hermes Provider {prov_name.title()}",
            "unique_id": f"hermes_agent_ha_addon_provider_{prov_name}",
            **_discovery_entity_id("binary_sensor", f"hermes_provider_{prov_name}"),
            "state_topic": f"{base}/status/provider_{prov_name}",
            "payload_on": "true",
            "payload_off": "false",
            "availability_topic": avail_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": device,
        }
        topic = f"homeassistant/binary_sensor/hermes_agent/provider_{prov_name}/config"
        publisher.publish(topic, json.dumps(cfg), retain=True)

    text_sensors = [
        ("main_provider", "Main Provider"),
        ("main_model", "Main Model"),
        ("auxiliary_title_model", "Auxiliary Title Model"),
        ("hermes_agent_version", "Hermes Agent Version"),
        ("addon_version", "Add-on Version"),
        ("setup_profile", "Setup Profile"),
        ("access_mode", "Access Mode"),
        ("gateway_mode", "Gateway Mode"),
        ("stt_provider", "STT Provider"),
        ("tts_provider", "TTS Provider"),
        ("max_turns", "Max Turns"),
    ]
    for key, label in text_sensors:
        cfg = {
            "name": f"Hermes {label}",
            "unique_id": f"hermes_agent_ha_addon_{key}",
            **_discovery_entity_id("sensor", f"hermes_{key}"),
            "state_topic": f"{base}/status/{key}",
            "availability_topic": avail_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": device,
        }
        topic = f"homeassistant/sensor/hermes_agent/{key}/config"
        publisher.publish(topic, json.dumps(cfg), retain=True)

    # last_error: short state + full text in attributes (HA state ≤ 255 chars)
    last_error_cfg = {
        "name": "Hermes Last Error",
        "unique_id": "hermes_agent_ha_addon_last_error",
        **_discovery_entity_id("sensor", "hermes_last_error"),
        "state_topic": f"{base}/status/last_error",
        "json_attributes_topic": f"{base}/status/last_error_attributes",
        "availability_topic": avail_topic,
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": device,
    }
    publisher.publish(
        "homeassistant/sensor/hermes_agent/last_error/config",
        json.dumps(last_error_cfg),
        retain=True,
    )

    timestamp_sensors = [
        ("updated_at", "Status Updated At"),
        ("last_session_at", "Last Session At"),
        ("gateway_health_probe_at", "Gateway Health Probe At"),
    ]
    for key, label in timestamp_sensors:
        cfg = {
            "name": f"Hermes {label}",
            "unique_id": f"hermes_agent_ha_addon_{key}",
            **_discovery_entity_id("sensor", f"hermes_{key}"),
            "state_topic": f"{base}/status/{key}",
            "device_class": "timestamp",
            "availability_topic": avail_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": device,
        }
        topic = f"homeassistant/sensor/hermes_agent/{key}/config"
        publisher.publish(topic, json.dumps(cfg), retain=True)

    numeric_sensors = [
        ("input_tokens_total", "Input Tokens Total", None, "total_increasing", None),
        ("output_tokens_total", "Output Tokens Total", None, "total_increasing", None),
        ("total_tokens", "Total Tokens", None, "total_increasing", None),
        ("estimated_cost_usd", "Estimated Cost USD", "monetary", "total_increasing", "USD"),
        ("actual_cost_usd", "Actual Cost USD", "monetary", "total_increasing", "USD"),
        ("cache_read_tokens_total", "Cache Read Tokens Total", None, "total_increasing", None),
        ("cache_write_tokens_total", "Cache Write Tokens Total", None, "total_increasing", None),
        ("reasoning_tokens_total", "Reasoning Tokens Total", None, "total_increasing", None),
        ("api_call_count_total", "API Call Count Total", None, "total_increasing", None),
        ("sessions_total", "Sessions Total", None, "total_increasing", None),
        ("sessions_24h", "Sessions 24h", None, "measurement", None),
        ("cost_24h", "Cost 24h", "monetary", "measurement", "USD"),
        ("tokens_24h", "Tokens 24h", None, "measurement", None),
        ("cache_hit_ratio", "Cache Hit Ratio", None, "measurement", "%"),
        ("reasoning_share", "Reasoning Share", None, "measurement", "%"),
        ("overhead_ratio", "Overhead Ratio", None, "measurement", "%"),
        ("overhead_cost_usd", "Overhead Cost USD", "monetary", "measurement", "USD"),
        ("compression_cost_usd", "Compression Cost USD", "monetary", "measurement", "USD"),
        ("aux_cost_usd", "Auxiliary Cost USD", "monetary", "measurement", "USD"),
        ("disk_usage_percent", "Disk Usage Percent", None, "measurement", "%"),
        ("message_count_total", "Message Count Total", None, "total_increasing", None),
        ("tool_call_count_total", "Tool Call Count Total", None, "total_increasing", None),
    ]
    for key, label, device_class, state_class, unit in numeric_sensors:
        cfg = {
            "name": f"Hermes {label}",
            "unique_id": f"hermes_agent_ha_addon_{key}",
            **_discovery_entity_id("sensor", f"hermes_{key}"),
            "state_topic": f"{base}/status/{key}",
            "availability_topic": avail_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "state_class": state_class,
            "device": device,
        }
        if device_class:
            cfg["device_class"] = device_class
        if unit:
            cfg["unit_of_measurement"] = unit
        if device_class == "monetary":
            cfg["suggested_display_precision"] = 2
        elif unit == "%":
            cfg["suggested_display_precision"] = 0
        topic = f"homeassistant/sensor/hermes_agent/{key}/config"
        publisher.publish(topic, json.dumps(cfg), retain=True)

    usage_summary_cfg = {
        "name": "Hermes Usage Summary",
        "unique_id": "hermes_agent_ha_addon_usage_summary",
        **_discovery_entity_id("sensor", "hermes_usage_summary"),
        "state_topic": f"{base}/status/usage_summary_state",
        "json_attributes_topic": f"{base}/status/usage_attributes",
        "availability_topic": avail_topic,
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": device,
    }
    publisher.publish(
        "homeassistant/sensor/hermes_agent/usage_summary/config",
        json.dumps(usage_summary_cfg),
        retain=True,
    )

    if control_enabled:
        publish_control_discovery(publisher, prefix, device, avail_topic)
    else:
        clear_control_discovery(publisher)

    return True


def publish_control_discovery(
    publisher: MqttPublisher,
    prefix: str,
    device: dict[str, Any],
    avail_topic: str,
) -> None:
    base = prefix.rstrip("/")
    for slug, label, icon in CONTROL_BUTTONS:
        cfg = {
            "name": f"Hermes {label}",
            "unique_id": f"hermes_agent_ha_addon_{slug}",
            **_discovery_entity_id("button", f"hermes_{slug}"),
            "command_topic": f"{base}/command/{slug}",
            "availability_topic": avail_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "icon": icon,
            "device": device,
        }
        topic = f"homeassistant/button/hermes_agent/{slug}/config"
        publisher.publish(topic, json.dumps(cfg), retain=True)

    select_defs = (
        (
            "approval_mode",
            "Approval Mode",
            sorted(_APPROVAL_MODES),
            "mdi:shield-check-outline",
        ),
        (
            "reasoning_effort",
            "Reasoning Effort",
            sorted(_REASONING_EFFORTS),
            "mdi:brain",
        ),
    )
    for slug, label, options, icon in select_defs:
        cfg = {
            "name": f"Hermes {label}",
            "unique_id": f"hermes_agent_ha_addon_{slug}",
            **_discovery_entity_id("select", f"hermes_{slug}"),
            "command_topic": f"{base}/command/{slug}",
            "state_topic": f"{base}/status/{slug}",
            "options": options,
            "availability_topic": avail_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "icon": icon,
            "device": device,
        }
        topic = f"homeassistant/select/hermes_agent/{slug}/config"
        publisher.publish(topic, json.dumps(cfg), retain=True)


def clear_control_discovery(publisher: MqttPublisher) -> None:
    """Remove retained control discovery so stale entities disappear when disabled."""
    for slug, _, _ in CONTROL_BUTTONS:
        publisher.publish(f"homeassistant/button/hermes_agent/{slug}/config", "", retain=True)
    for slug in ("approval_mode", "reasoning_effort"):
        publisher.publish(f"homeassistant/select/hermes_agent/{slug}/config", "", retain=True)


def _ratio_as_percent(value: Any) -> str:
    if value is None:
        return "unknown"
    try:
        return str(int(round(float(value) * 100.0)))
    except (TypeError, ValueError):
        return "unknown"


def publish_mqtt_state(snapshot: dict[str, Any], publisher: MqttPublisher, prefix: str) -> bool:
    if not publisher.is_ready():
        return False

    base = prefix.rstrip("/")
    publisher.publish(f"{base}/status/availability", "online", retain=True)

    def pub_bool(key: str, value: bool):
        publisher.publish(f"{base}/status/{key}", "true" if value else "false")

    pub_bool("gateway_running", bool(snapshot.get("gateway_running")))
    pub_bool("gateway_ready", bool(snapshot.get("gateway_ready")))
    pub_bool("api_key_configured", bool(snapshot.get("api_key_configured")))
    pub_bool("model_configured", bool(snapshot.get("model_configured")))
    pub_bool("mcp_configured", bool(snapshot.get("mcp_configured")))
    pub_bool("assist_api_enabled", bool(snapshot.get("assist_api_enabled")))
    pub_bool("outbound_events_enabled", bool(snapshot.get("outbound_events_enabled")))
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
        "last_error",
        "approval_mode",
        "reasoning_effort",
        "stt_provider",
        "tts_provider",
        "max_turns",
    ):
        publisher.publish(f"{base}/status/{key}", str(snapshot.get(key, "unknown")))

    # Full last-error text as attributes (state is truncated).
    publisher.publish(
        f"{base}/status/last_error_attributes",
        json.dumps(
            {
                "full": snapshot.get("last_error_full") or snapshot.get("last_error") or "none",
            }
        ),
    )

    usage = snapshot.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}

    # Timestamp sensors (ISO-8601 or "unknown")
    for key, src in (
        ("updated_at", snapshot.get("updated_at")),
        ("gateway_health_probe_at", snapshot.get("gateway_health_probe_at")),
        ("last_session_at", usage.get("last_session_at")),
    ):
        publisher.publish(f"{base}/status/{key}", str(src) if src else "unknown")

    def pub_num(key: str, src_key: str | None = None):
        src = src_key or key
        val = usage.get(src) if src in usage else snapshot.get(src)
        if val is None:
            publisher.publish(f"{base}/status/{key}", "unknown")
        else:
            publisher.publish(f"{base}/status/{key}", str(val))

    pub_num("input_tokens_total")
    pub_num("output_tokens_total")
    pub_num("total_tokens")
    pub_num("estimated_cost_usd")
    pub_num("actual_cost_usd")
    pub_num("cache_read_tokens_total")
    pub_num("cache_write_tokens_total")
    pub_num("reasoning_tokens_total")
    pub_num("api_call_count_total")
    pub_num("sessions_total")
    pub_num("sessions_24h")
    pub_num("message_count_total")
    pub_num("tool_call_count_total")
    pub_num("cost_24h")
    pub_num("tokens_24h")
    pub_num("overhead_cost_usd")
    pub_num("compression_cost_usd")
    pub_num("aux_cost_usd")

    publisher.publish(f"{base}/status/cache_hit_ratio", _ratio_as_percent(usage.get("cache_hit_ratio")))
    publisher.publish(f"{base}/status/reasoning_share", _ratio_as_percent(usage.get("reasoning_share")))
    publisher.publish(f"{base}/status/overhead_ratio", _ratio_as_percent(usage.get("overhead_ratio")))

    disk = snapshot.get("disk_usage_percent")
    publisher.publish(
        f"{base}/status/disk_usage_percent",
        "unknown" if disk is None else str(disk),
    )

    overhead = usage.get("overhead", {})
    if not isinstance(overhead, dict):
        overhead = {}

    attrs = {
        "usage_by_model": usage.get("usage_by_model", []),
        "configured_providers": snapshot.get("configured_providers", []),
        "last_session_at": usage.get("last_session_at"),
        "gateway_health_probe_at": snapshot.get("gateway_health_probe_at"),
        "updated_at": snapshot.get("updated_at"),
        "windows": usage.get("windows", {}),
        "by_provider": usage.get("by_provider", []),
        "by_model": usage.get("by_model", []),
        "by_task": usage.get("by_task", []),
        "overhead": overhead,
        "schema_version": snapshot.get("schema_version", 2),
    }
    publisher.publish(f"{base}/status/usage_attributes", json.dumps(attrs))
    total = usage.get("total_tokens")
    publisher.publish(
        f"{base}/status/usage_summary_state",
        "unknown" if total is None else str(total),
    )
    return True


def _publish_mqtt_discovery_enabled(payload: dict) -> bool:
    return str(payload.get("publish_mqtt_discovery", "true")).lower() in (
        "1",
        "true",
        "yes",
    )


def publish_mqtt_updates(
    snapshot: dict[str, Any],
    payload: dict,
    publisher: MqttPublisher,
    mqtt_cfg: dict[str, Any] | None = None,
) -> bool:
    if mqtt_cfg is None:
        mqtt_cfg = resolve_mqtt_config(payload)
    if not mqtt_cfg.get("host"):
        publisher.disconnect()
        return False

    prefix = str(payload.get("mqtt_state_prefix", "hermes") or "hermes")
    control_enabled = _control_enabled(payload)
    if not publisher.ensure_connected(mqtt_cfg, f"{prefix.rstrip('/')}/status/availability"):
        return False

    if _publish_mqtt_discovery_enabled(payload) and discovery_needs_publish(
        prefix, control_enabled
    ):
        # Only stamp the marker once the broker has acknowledged the whole batch.
        if (
            publish_mqtt_discovery(snapshot, publisher, prefix, control_enabled)
            and publisher.flush()
        ):
            mark_discovery_published(prefix, control_enabled)
            print(
                f"INFO: MQTT discovery published once (prefix={prefix}, addon={ADDON_VERSION}, "
                f"control={control_enabled})",
                file=sys.stderr,
            )
    published = publish_mqtt_state(snapshot, publisher, prefix)
    return publisher.flush() and published


def handle_mqtt_command(topic: str, body: str, publisher: MqttPublisher, prefix: str) -> None:
    """Dispatch MQTT command topics under <prefix>/command/#."""
    base = prefix.rstrip("/")
    cmd_prefix = f"{base}/command/"
    if not topic.startswith(cmd_prefix):
        return
    name = topic[len(cmd_prefix) :].strip("/")
    if not name or "/" in name:
        return
    text = (body or "").strip()
    print(f"INFO: MQTT command received: {name}", file=sys.stderr)

    if name == "refresh_status":
        publisher.request_wake()
        return
    if name == "run_cleanup":
        _run_script(["hermes-cleanup"], "hermes-cleanup")
        publisher.request_wake()
        return
    if name == "run_backup":
        _run_script(["hermes-backup-share", "--quick"], "hermes-backup-share")
        publisher.request_wake()
        return
    if name == "restart_gateway":
        if _write_control_request("restart_gateway"):
            print("INFO: Queued gateway restart request for run.sh watcher", file=sys.stderr)
        return
    if name == "approval_mode":
        if text not in _APPROVAL_MODES:
            print(f"WARN: Ignoring invalid approval_mode={text!r}", file=sys.stderr)
            return
        if set_approval_mode(text):
            publisher.publish(f"{base}/status/approval_mode", text)
            # Config is read at gateway start — chain a restart so it applies.
            _write_control_request("restart_gateway", f"approval_mode={text}")
            publisher.request_wake()
        return
    if name == "reasoning_effort":
        if text not in _REASONING_EFFORTS:
            print(f"WARN: Ignoring invalid reasoning_effort={text!r}", file=sys.stderr)
            return
        if set_reasoning_effort(text):
            publisher.publish(f"{base}/status/reasoning_effort", text)
            _write_control_request("restart_gateway", f"reasoning_effort={text}")
            publisher.request_wake()
        return
    print(f"WARN: Unknown MQTT command: {name}", file=sys.stderr)


def run_once(
    payload: dict,
    publisher: MqttPublisher | None = None,
    mqtt_cfg: dict[str, Any] | None = None,
) -> bool:
    snapshot = collect_status_snapshot(payload)
    ok = write_status_file(STATUS_FILE, snapshot)
    if publisher is not None:
        publish_mqtt_updates(snapshot, payload, publisher, mqtt_cfg)
    return ok


def run_loop(payload: dict) -> int:
    interval = int(payload.get("status_poll_interval_seconds", 60))
    interval = max(30, min(300, interval))
    mqtt_unavailable_logged = False
    mqtt_available_logged = False
    publisher = MqttPublisher()
    mqtt_cfg: dict[str, Any] = {}
    prefix = str(payload.get("mqtt_state_prefix", "hermes") or "hermes")

    def _on_command(topic: str, body: str) -> None:
        handle_mqtt_command(topic, body, publisher, prefix)

    if _control_enabled(payload):
        publisher.set_command_handler(f"{prefix.rstrip('/')}/command/#", _on_command)
        print(
            f"INFO: MQTT control entities enabled (commands on {prefix}/command/#)",
            file=sys.stderr,
        )
    else:
        publisher.set_command_handler(None, None)

    try:
        while True:
            # Resolve broker only when we have no usable endpoint or the session dropped.
            # Avoids duplicate resolve + TCP probes on every poll while MQTT is live.
            if not (mqtt_cfg.get("host") and publisher.is_ready()):
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
                    publisher.disconnect()
                    mqtt_unavailable_logged = True
                    mqtt_available_logged = False

            cycle_started = time.monotonic()
            try:
                run_once(payload, publisher, mqtt_cfg)
            except Exception as e:
                print(f"WARN: Status exporter cycle failed: {e}", file=sys.stderr)

            # Keep the poll period stable; wake early on MQTT refresh/commands.
            publisher.wait_interval(max(1.0, interval - (time.monotonic() - cycle_started)))
    finally:
        publisher.disconnect()
    return 0


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
        publisher = MqttPublisher()
        try:
            ok = publish_mqtt_updates(snapshot, payload, publisher)
        finally:
            publisher.disconnect()
        sys.exit(0 if ok else 1)
    if cmd == "run-loop":
        sys.exit(run_loop(payload))

    print(f"Unknown command: {cmd}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
