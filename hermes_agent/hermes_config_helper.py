#!/usr/bin/env python3
"""
Hermes Agent config helper for Home Assistant add-on.
Safely reads/writes hermes.json without corrupting it.
"""

import json
import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - image installs python3-yaml
    yaml = None

CONFIG_PATH = Path(os.environ.get("HERMES_CONFIG_PATH", "/config/.hermes/hermes.json"))
YAML_CONFIG_PATH = Path(os.environ.get("HERMES_YAML_CONFIG_PATH", "/config/.hermes/config.yaml"))
HERMES_ENV_PATH = Path(os.environ.get("HERMES_ENV_PATH", "/config/.hermes/.env"))
HERMES_STATE_DIR = YAML_CONFIG_PATH.parent

PROFILE_MANIFEST = {
    "home_assistant": {
        "access_mode_when_custom": "lan_https",
        "auto_mcp_when_ha_token": True,
        "bootstrap_auxiliary_title": True,
        "log_gateway_url_hint": True,
    },
    "general": {
        "access_mode_when_custom": "local_only",
        "auto_mcp_when_ha_token": False,
        "bootstrap_auxiliary_title": True,
        "log_gateway_url_hint": False,
    },
    "advanced": {
        "access_mode_when_custom": None,
        "auto_mcp_when_ha_token": False,
        "bootstrap_auxiliary_title": False,
        "log_gateway_url_hint": False,
    },
}

MODEL_PRESETS = {
    "gemini_flash": "google/gemini-2.5-flash",
    "claude_sonnet": "anthropic/claude-sonnet-4-6",
    "gpt_mini": "openai/gpt-4.1-mini",
}

AUXILIARY_TITLE_MODEL = "google/gemini-2.5-flash"


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
    trusted_proxies = []
    for p in [x.strip() for x in trusted_proxies_csv.split(",") if x.strip()]:
        if is_valid_ip_cidr(p):
            trusted_proxies.append(p)
        else:
            print(f"WARN: Skipping invalid trusted proxy entry (expected IP/CIDR): {p!r}", file=sys.stderr)

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


def read_yaml_config():
    if yaml is None:
        print("ERROR: PyYAML is not available (install python3-yaml)", file=sys.stderr)
        return None
    if not YAML_CONFIG_PATH.exists():
        return {}
    try:
        data = yaml.safe_load(YAML_CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (yaml.YAMLError, OSError) as e:
        print(f"ERROR: Failed to read YAML config: {e}", file=sys.stderr)
        return None


def write_yaml_config(cfg):
    if yaml is None:
        print("ERROR: PyYAML is not available (install python3-yaml)", file=sys.stderr)
        return False
    try:
        YAML_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        YAML_CONFIG_PATH.write_text(
            yaml.safe_dump(cfg, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        return True
    except OSError as e:
        print(f"ERROR: Failed to write YAML config: {e}", file=sys.stderr)
        return False


# Add-on option keys synced into /config/.hermes/.env for Hermes setup/runtime.
ADDON_API_KEY_ENV_MAP = {
    "OPENAI_API_KEY": "openai_api_key",
    "OPENROUTER_API_KEY": "openrouter_api_key",
    "ANTHROPIC_API_KEY": "anthropic_api_key",
    "GOOGLE_API_KEY": "google_api_key",
    "MINIMAX_API_KEY": "minimax_api_key",
    "DISCORD_BOT_TOKEN": "discord_bot_token",
    "GITHUB_TOKEN": "github_token",
    "XAI_API_KEY": "xai_api_key",
    "FIRECRAWL_API_KEY": "firecrawl_api_key",
    "SEARXNG_URL": "searxng_url",
}


IP_CIDR_RE = re.compile(
    r"^("
    r"(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}"
    r"(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)(?:\/(?:[0-9]|[1-2][0-9]|3[0-2]))?"
    r"|"
    r"(?:[0-9a-fA-F:]+)(?:\/\d{1,3})?"
    r")$"
)


def is_valid_ip_cidr(value: str) -> bool:
    return bool(IP_CIDR_RE.match((value or "").strip()))


def read_env_var(key: str) -> str:
    if not HERMES_ENV_PATH.exists():
        return ""
    prefix = f"{key}="
    try:
        for line in HERMES_ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.startswith(prefix):
                return line.split("=", 1)[1].strip()
    except OSError:
        return ""
    return ""


def merge_addon_secrets_with_persisted(secrets: dict) -> dict:
    """Keep persisted /config/.hermes/.env values when add-on options are empty (e.g. after reinstall)."""
    if not isinstance(secrets, dict):
        return {}
    merged = dict(secrets)
    for env_key in ADDON_API_KEY_ENV_MAP:
        value = merged.get(env_key, "")
        if isinstance(value, str) and value.strip():
            continue
        persisted = read_env_var(env_key)
        if persisted:
            merged[env_key] = persisted
    return merged


def upsert_env_var(key: str, value: str):
    if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key):
        print(f"ERROR: Invalid env var name: {key}", file=sys.stderr)
        return False
    if not value:
        print(f"ERROR: Refusing to write empty value for {key}", file=sys.stderr)
        return False

    HERMES_ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if HERMES_ENV_PATH.exists():
        lines = HERMES_ENV_PATH.read_text(encoding="utf-8").splitlines()

    prefix = f"{key}="
    replaced = False
    out = []
    for line in lines:
        if line.startswith(prefix):
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{key}={value}")

    try:
        HERMES_ENV_PATH.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
        os.chmod(HERMES_ENV_PATH, 0o600)
        return True
    except OSError as e:
        print(f"ERROR: Failed to update {HERMES_ENV_PATH}: {e}", file=sys.stderr)
        return False


# Default main models when add-on default_model is empty (provider -> model id).
DEFAULT_MODEL_BY_PROVIDER = {
    "openrouter": "google/gemini-2.5-flash",
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4.1-mini",
    "google": "gemini-2.5-flash",
    "minimax": "MiniMax-M2.7",
}

# Provider preference when multiple API keys are configured.
PROVIDER_KEY_PRIORITY = (
    ("openrouter", "OPENROUTER_API_KEY"),
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
    ("google", "GOOGLE_API_KEY"),
    ("minimax", "MINIMAX_API_KEY"),
)

# Main LLM provider env keys only (excludes auxiliary/search tokens).
MAIN_MODEL_PROVIDER_ENV_KEYS = tuple(env_key for _, env_key in PROVIDER_KEY_PRIORITY)

# Local CDP endpoint for browser-cdp tool (headless Chromium in the add-on image).
BROWSER_CDP_URL = "http://127.0.0.1:9222"


def model_needs_bootstrap(cfg: dict) -> bool:
    if not cfg:
        return True
    model = cfg.get("model")
    if model is None:
        return True
    if model == "":
        return True
    if isinstance(model, dict):
        default = model.get("default", "")
        if not default or (isinstance(default, str) and not default.strip()):
            return True
    return False


def _has_api_key(api_keys: dict, env_key: str) -> bool:
    value = api_keys.get(env_key, "")
    return isinstance(value, str) and bool(value.strip())


def has_main_model_api_key(
    api_keys: dict, env_presence: dict[str, bool] | None = None
) -> bool:
    for env_key in MAIN_MODEL_PROVIDER_ENV_KEYS:
        if _has_api_key(api_keys, env_key):
            return True
        if env_presence is not None and env_presence.get(env_key):
            return True
    return False


HA_URL_AUTO_DEFAULTS = frozenset(
    {
        "",
        "http://localhost:8123",
        "https://localhost:8123",
        "http://127.0.0.1:8123",
        "https://127.0.0.1:8123",
    }
)


def is_hass_url_auto(user_url: str) -> bool:
    normalized = (user_url or "").strip().rstrip("/")
    return normalized in HA_URL_AUTO_DEFAULTS


def resolve_home_assistant_url(payload: dict):
    """Resolve HA base URL and MCP endpoint for add-on runtime.

    When hass_url is empty or a local placeholder, prefer supervisor/core on HAOS
    and fall back to loopback. User-provided non-local URLs are never overridden.
    """
    if not isinstance(payload, dict):
        print("ERROR: resolve-home-assistant-url expects a JSON object", file=sys.stderr)
        return None

    user_url = str(payload.get("hass_url", "")).strip().rstrip("/")
    supervisor_available = str(payload.get("supervisor_available", "false")).lower() in (
        "1",
        "true",
        "yes",
    )
    internal_host = str(payload.get("internal_host", "")).strip()
    internal_port = str(payload.get("internal_port", "")).strip()

    if user_url and not is_hass_url_auto(user_url):
        return {
            "homeassistant_url": user_url,
            "mcp_url": f"{user_url}/api/mcp",
            "source": "user",
            "verified": None,
        }

    if supervisor_available:
        ha_url = "http://127.0.0.1:8123"
        if internal_host and internal_port:
            ha_url = f"http://{internal_host}:{internal_port}"
        return {
            "homeassistant_url": ha_url,
            "mcp_url": "http://supervisor/core/api/mcp",
            "source": "supervisor",
            "verified": None,
        }

    fallback = user_url or "http://127.0.0.1:8123"
    return {
        "homeassistant_url": fallback,
        "mcp_url": f"{fallback}/api/mcp",
        "source": "default",
        "verified": None,
    }


def resolve_setup_profile(payload: dict):
    if not isinstance(payload, dict):
        print("ERROR: resolve-setup-profile expects a JSON object", file=sys.stderr)
        return None

    profile = str(payload.get("setup_profile", "home_assistant")).strip() or "home_assistant"
    access_mode = str(payload.get("access_mode", "lan_https")).strip() or "lan_https"
    auto_configure_mcp = str(payload.get("auto_configure_mcp", "false")).lower() in ("1", "true", "yes")
    ha_token = str(payload.get("homeassistant_token", "")).strip()

    manifest = PROFILE_MANIFEST.get(profile, PROFILE_MANIFEST["advanced"])
    effective_access_mode = access_mode
    if access_mode == "custom" and manifest.get("access_mode_when_custom"):
        effective_access_mode = manifest["access_mode_when_custom"]

    effective_auto_configure_mcp = auto_configure_mcp
    if manifest.get("auto_mcp_when_ha_token") and ha_token:
        effective_auto_configure_mcp = True

    return {
        "setup_profile": profile,
        "access_mode": effective_access_mode,
        "auto_configure_mcp": effective_auto_configure_mcp,
        "bootstrap_auxiliary_title": bool(manifest.get("bootstrap_auxiliary_title")),
        "log_gateway_url_hint": bool(manifest.get("log_gateway_url_hint")),
    }


def resolve_default_model_text(default_model_preset: str, default_model: str) -> str:
    preset = (default_model_preset or "auto").strip().lower()
    if preset == "custom":
        return (default_model or "").strip()
    if preset == "auto":
        return (default_model or "").strip()
    return MODEL_PRESETS.get(preset, (default_model or "").strip())


def infer_provider_and_model(default_model: str, api_keys: dict):
    """Return (provider, model) or (None, None) when inference is not possible."""
    explicit = (default_model or "").strip()
    if explicit:
        if "/" in explicit and _has_api_key(api_keys, "OPENROUTER_API_KEY"):
            return "openrouter", explicit
        if "/" in explicit:
            prefix, model_id = explicit.split("/", 1)
            prefix = prefix.strip().lower()
            model_id = model_id.strip()
            if prefix == "anthropic" and _has_api_key(api_keys, "ANTHROPIC_API_KEY"):
                return "anthropic", model_id
            if prefix in ("openai", "gpt") and _has_api_key(api_keys, "OPENAI_API_KEY"):
                return "openai", model_id
            if prefix == "google" and _has_api_key(api_keys, "GOOGLE_API_KEY"):
                return "google", model_id
        for provider, env_key in PROVIDER_KEY_PRIORITY:
            if _has_api_key(api_keys, env_key):
                return provider, explicit
        return None, None

    for provider, env_key in PROVIDER_KEY_PRIORITY:
        if _has_api_key(api_keys, env_key):
            return provider, DEFAULT_MODEL_BY_PROVIDER[provider]

    return None, None


def _infer_provider_from_api_keys(api_keys: dict):
    for provider, env_key in PROVIDER_KEY_PRIORITY:
        if _has_api_key(api_keys, env_key):
            return provider
    return None


def auxiliary_title_needs_bootstrap(cfg: dict) -> bool:
    auxiliary = cfg.get("auxiliary")
    if not isinstance(auxiliary, dict):
        return True
    title = auxiliary.get("title_generation")
    if not isinstance(title, dict):
        return True
    provider = str(title.get("provider", "auto")).strip().lower()
    model = str(title.get("model", "")).strip()
    if provider in ("", "auto") and not model:
        return True
    return False


def bootstrap_auxiliary_title_if_needed(api_keys: dict):
    cfg = read_yaml_config()
    if cfg is None:
        return False
    if not auxiliary_title_needs_bootstrap(cfg):
        return True

    provider = _infer_provider_from_api_keys(api_keys) or "openrouter"
    model = AUXILIARY_TITLE_MODEL
    if provider != "openrouter" and "/" not in model:
        model = DEFAULT_MODEL_BY_PROVIDER.get(provider, model)

    auxiliary = cfg.get("auxiliary")
    if not isinstance(auxiliary, dict):
        auxiliary = {}
    auxiliary["title_generation"] = {
        "provider": provider,
        "model": model,
        "base_url": "",
        "api_key": "",
        "timeout": 30,
    }
    cfg["auxiliary"] = auxiliary
    if write_yaml_config(cfg):
        print(
            "INFO: Bootstrapped auxiliary title_generation in "
            f"{YAML_CONFIG_PATH}: {provider} / {model}"
        )
        return True
    return False


def write_readiness_marker(name: str, present: bool):
    path = HERMES_STATE_DIR / name
    HERMES_STATE_DIR.mkdir(parents=True, exist_ok=True)
    if present:
        path.write_text("ok\n", encoding="utf-8")
    elif path.exists():
        path.unlink()
    return True


def update_readiness_markers(api_keys: dict, enable_openai_api: bool, mcp_configured: bool):
    has_api_key = has_main_model_api_key(api_keys)
    cfg = read_yaml_config()
    model_ok = cfg is not None and not model_needs_bootstrap(cfg)

    write_readiness_marker(".bootstrap-api-key-ok", has_api_key)
    write_readiness_marker(".bootstrap-model-ok", model_ok)
    write_readiness_marker(".bootstrap-mcp-ok", mcp_configured)
    write_readiness_marker(".bootstrap-assist-ok", enable_openai_api)
    return True


API_SERVER_DEFAULT_PORT = 8642


def read_gateway_auth_token() -> str:
    cfg = read_config()
    if not cfg:
        return ""
    token = cfg.get("gateway", {}).get("auth", {}).get("token", "")
    return str(token).strip() if token else ""


def sync_api_server_env(enable: bool, port: int = API_SERVER_DEFAULT_PORT) -> bool:
    """Map enable_openai_api to Hermes API server env vars (API_SERVER_*)."""
    if port < 1 or port > 65535:
        print(f"ERROR: Invalid API server port {port}", file=sys.stderr)
        return False

    if not enable:
        if upsert_env_var("API_SERVER_ENABLED", "false"):
            print("INFO: Assist API disabled (API_SERVER_ENABLED=false).")
        return True

    token = read_gateway_auth_token()
    if not token:
        print(
            "WARN: enable_openai_api is ON but gateway.auth.token is missing; "
            "run 'hermes onboard' then restart. Disabling API server for now.",
            file=sys.stderr,
        )
        upsert_env_var("API_SERVER_ENABLED", "false")
        return False

    ok = True
    ok = upsert_env_var("API_SERVER_ENABLED", "true") and ok
    ok = upsert_env_var("API_SERVER_KEY", token) and ok
    ok = upsert_env_var("API_SERVER_PORT", str(port)) and ok
    ok = upsert_env_var("API_SERVER_HOST", "0.0.0.0") and ok
    if ok:
        print(
            f"INFO: Assist API enabled (API_SERVER_ENABLED=true on 0.0.0.0:{port}; "
            f"Extended OpenAI from HA Core: http://<LAN-IP>:{port}/v1; "
            f"nginx HTTPS /v1/ on gateway port when lan_https)."
        )
    return ok


def sync_router_ssh_env(host: str, user: str, key_path: str):
    host = (host or "").strip()
    user = (user or "").strip()
    key_path = (key_path or "").strip()
    if not host or not user:
        return True

    ok = upsert_env_var("TERMINAL_SSH_HOST", host) and upsert_env_var("TERMINAL_SSH_USER", user)
    if key_path:
        ok = upsert_env_var("TERMINAL_SSH_KEY", key_path) and ok
    if ok:
        print(f"INFO: Synced router SSH env for Hermes: TERMINAL_SSH_HOST, TERMINAL_SSH_USER")
    return ok


def bootstrap_model_if_missing(default_model: str, api_keys: dict):
    cfg = read_yaml_config()
    if cfg is None:
        return False
    if not model_needs_bootstrap(cfg):
        return True

    provider, model_id = infer_provider_and_model(default_model, api_keys)
    if not provider or not model_id:
        return True

    cfg["model"] = {
        "provider": provider,
        "default": model_id,
        "base_url": "",
        "api_mode": "chat_completions",
    }
    if write_yaml_config(cfg):
        print(
            "INFO: Bootstrapped Hermes main model in "
            f"{YAML_CONFIG_PATH}: {provider} / {model_id}"
        )
        write_readiness_marker(".bootstrap-model-ok", True)
        return True
    return False


def bootstrap_browser_if_enabled(enabled: bool):
    if not enabled:
        return True

    cfg = read_yaml_config()
    if cfg is None:
        return False

    browser = cfg.get("browser")
    if isinstance(browser, dict):
        updated = dict(browser)
    else:
        updated = {}

    changed = False
    if not updated.get("noSandbox"):
        updated["enabled"] = True
        updated["headless"] = True
        updated["noSandbox"] = True
        changed = True
    if not str(updated.get("cdp_url", "") or "").strip():
        updated["cdp_url"] = BROWSER_CDP_URL
        changed = True

    if not changed:
        return True

    cfg["browser"] = updated
    if write_yaml_config(cfg):
        print(
            f"INFO: Bootstrapped Docker-safe browser settings in {YAML_CONFIG_PATH} "
            f"(cdp_url={BROWSER_CDP_URL})"
        )
        return True
    return False


def _resolve_web_backend(firecrawl_key: str, searxng_url: str) -> str:
    if (firecrawl_key or "").strip() or _env_has_value("FIRECRAWL_API_KEY"):
        return "firecrawl"
    if (searxng_url or "").strip() or _env_has_value("SEARXNG_URL"):
        return "searxng"
    return "ddgs"


def _env_has_value(key: str) -> bool:
    if not HERMES_ENV_PATH.exists():
        return False
    prefix = f"{key}="
    try:
        for line in HERMES_ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.startswith(prefix) and line[len(prefix) :].strip():
                return True
    except OSError:
        pass
    return False


def bootstrap_web_search_if_missing(firecrawl_key: str, searxng_url: str):
    cfg = read_yaml_config()
    if cfg is None:
        return False

    web = cfg.get("web")
    if isinstance(web, dict) and str(web.get("backend", "") or "").strip():
        return True

    backend = _resolve_web_backend(firecrawl_key, searxng_url)
    cfg["web"] = {"backend": backend}
    if write_yaml_config(cfg):
        print(f"INFO: Bootstrapped web search backend in {YAML_CONFIG_PATH}: {backend}")
        return True
    return False


def bootstrap_kanban_toolset_if_missing(setup_profile: str):
    profile = (setup_profile or "").strip() or "home_assistant"
    if profile not in ("home_assistant", "general"):
        return True

    cfg = read_yaml_config()
    if cfg is None:
        return False

    toolsets = cfg.get("toolsets")
    if isinstance(toolsets, list):
        if "kanban" in toolsets:
            return True
        cfg["toolsets"] = [*toolsets, "kanban"]
    else:
        cfg["toolsets"] = ["kanban"]

    if write_yaml_config(cfg):
        print(f"INFO: Bootstrapped kanban toolset in {YAML_CONFIG_PATH} for profile {profile}")
        return True
    return False


def bootstrap_timezone_if_missing(timezone: str):
    tz = (timezone or "").strip()
    if not tz:
        return True

    cfg = read_yaml_config()
    if cfg is None:
        return False
    if cfg.get("timezone"):
        return True

    cfg["timezone"] = tz
    if write_yaml_config(cfg):
        print(f"INFO: Bootstrapped Hermes timezone in {YAML_CONFIG_PATH}: {tz}")
        return True
    return False


def sync_homeassistant_env(url: str, token: str):
    base = (url or "").strip().rstrip("/")
    tok = (token or "").strip()
    ok = True
    if base:
        ok = upsert_env_var("HOMEASSISTANT_URL", base) and ok
        ok = upsert_env_var("HASS_URL", base) and ok
    if tok:
        ok = upsert_env_var("HOMEASSISTANT_TOKEN", tok) and ok
        ok = upsert_env_var("HASS_TOKEN", tok) and ok
    if ok and (base or tok):
        synced = []
        if base:
            synced.extend(["HOMEASSISTANT_URL", "HASS_URL"])
        if tok:
            synced.extend(["HOMEASSISTANT_TOKEN", "HASS_TOKEN"])
        print(f"INFO: Synced Home Assistant env for Hermes setup: {', '.join(synced)}")
    return ok


def bootstrap_first_run(payload: dict):
    if not isinstance(payload, dict):
        print("ERROR: bootstrap-first-run expects a JSON object", file=sys.stderr)
        return False

    timezone = payload.get("timezone", "")
    browser_enabled = str(payload.get("browser_enabled", "false")).lower() in ("1", "true", "yes")
    default_model_preset = payload.get("default_model_preset", "auto")
    default_model = payload.get("default_model", "")
    bootstrap_auxiliary_title = str(payload.get("bootstrap_auxiliary_title", "false")).lower() in (
        "1",
        "true",
        "yes",
    )
    api_keys = payload.get("api_keys", {})
    ha_url = payload.get("homeassistant_url", "")
    ha_token = payload.get("homeassistant_token", "")
    setup_profile = str(payload.get("setup_profile", "home_assistant"))
    firecrawl_key = str(payload.get("firecrawl_api_key", ""))
    searxng_url = str(payload.get("searxng_url", ""))
    enable_openai_api = str(payload.get("enable_openai_api", "false")).lower() in ("1", "true", "yes")
    mcp_configured = str(payload.get("mcp_configured", "false")).lower() in ("1", "true", "yes")

    if not isinstance(api_keys, dict):
        api_keys = {}

    resolved_model = resolve_default_model_text(str(default_model_preset), str(default_model))

    ok = True
    if ha_url or ha_token:
        ok = sync_homeassistant_env(str(ha_url), str(ha_token)) and ok
    ok = bootstrap_timezone_if_missing(str(timezone)) and ok
    ok = bootstrap_browser_if_enabled(browser_enabled) and ok
    ok = bootstrap_web_search_if_missing(firecrawl_key, searxng_url) and ok
    ok = bootstrap_kanban_toolset_if_missing(setup_profile) and ok
    ok = bootstrap_model_if_missing(resolved_model, api_keys) and ok
    if bootstrap_auxiliary_title:
        ok = bootstrap_auxiliary_title_if_needed(api_keys) and ok
    ok = update_readiness_markers(api_keys, enable_openai_api, mcp_configured) and ok
    return ok


def sync_addon_api_keys(secrets: dict):
    """Write non-empty add-on API keys into Hermes .env for onboard/model setup."""
    if not isinstance(secrets, dict):
        print("ERROR: sync-addon-api-keys expects a JSON object", file=sys.stderr)
        return False

    secrets = merge_addon_secrets_with_persisted(secrets)
    synced = []
    for env_key in ADDON_API_KEY_ENV_MAP:
        value = secrets.get(env_key, "")
        if not isinstance(value, str) or not value.strip():
            continue
        if upsert_env_var(env_key, value.strip()):
            synced.append(env_key)

    if synced:
        print(
            "INFO: Synced add-on API keys to "
            f"{HERMES_ENV_PATH} for Hermes setup: {', '.join(synced)}"
        )
    return True


def configure_ha_mcp(server_name: str, url: str, token_env_key: str = "HOMEASSISTANT_TOKEN"):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", server_name or ""):
        print(f"ERROR: Invalid MCP server name: {server_name!r}", file=sys.stderr)
        return False
    if not url or not url.startswith(("http://", "https://")):
        print(f"ERROR: Invalid MCP URL: {url!r}", file=sys.stderr)
        return False

    cfg = read_yaml_config()
    if cfg is None:
        return False

    mcp_servers = cfg.get("mcp_servers")
    if not isinstance(mcp_servers, dict):
        mcp_servers = {}
    mcp_servers[server_name] = {
        "url": url,
        "enabled": True,
        "headers": {
            "Authorization": f"Bearer ${{{token_env_key}}}",
        },
    }
    cfg["mcp_servers"] = mcp_servers
    return write_yaml_config(cfg)


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
    elif cmd == "configure-ha-mcp":
        if len(sys.argv) < 5:
            print("Usage: hermes_config_helper.py configure-ha-mcp <server_name> <url> <token>", file=sys.stderr)
            sys.exit(1)
        server_name = sys.argv[2]
        url = sys.argv[3]
        token = sys.argv[4]
        env_key = "HOMEASSISTANT_TOKEN"
        ok = upsert_env_var(env_key, token) and configure_ha_mcp(server_name, url, env_key)
        sys.exit(0 if ok else 1)
    elif cmd == "sync-api-server-env":
        if len(sys.argv) < 3:
            print(
                "Usage: hermes_config_helper.py sync-api-server-env <true|false> [port]",
                file=sys.stderr,
            )
            sys.exit(1)
        enable = sys.argv[2].lower() in ("1", "true", "yes")
        port = API_SERVER_DEFAULT_PORT
        if len(sys.argv) > 3:
            try:
                port = int(sys.argv[3])
            except ValueError:
                print(f"ERROR: Invalid API server port: {sys.argv[3]}", file=sys.stderr)
                sys.exit(1)
        sys.exit(0 if sync_api_server_env(enable, port) else 1)
    elif cmd == "sync-addon-api-keys":
        if len(sys.argv) < 3:
            print("Usage: hermes_config_helper.py sync-addon-api-keys '<json-object>'", file=sys.stderr)
            sys.exit(1)
        try:
            payload = json.loads(sys.argv[2])
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON for sync-addon-api-keys: {e}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0 if sync_addon_api_keys(payload) else 1)
    elif cmd == "bootstrap-first-run":
        if len(sys.argv) < 3:
            print("Usage: hermes_config_helper.py bootstrap-first-run '<json-object>'", file=sys.stderr)
            sys.exit(1)
        try:
            payload = json.loads(sys.argv[2])
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON for bootstrap-first-run: {e}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0 if bootstrap_first_run(payload) else 1)
    elif cmd == "sync-homeassistant-env":
        if len(sys.argv) < 4:
            print("Usage: hermes_config_helper.py sync-homeassistant-env <url> <token>", file=sys.stderr)
            sys.exit(1)
        sys.exit(0 if sync_homeassistant_env(sys.argv[2], sys.argv[3]) else 1)
    elif cmd == "resolve-setup-profile":
        if len(sys.argv) < 3:
            print("Usage: hermes_config_helper.py resolve-setup-profile '<json-object>'", file=sys.stderr)
            sys.exit(1)
        try:
            payload = json.loads(sys.argv[2])
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON for resolve-setup-profile: {e}", file=sys.stderr)
            sys.exit(1)
        resolved = resolve_setup_profile(payload)
        if resolved is None:
            sys.exit(1)
        print(json.dumps(resolved))
        sys.exit(0)
    elif cmd == "resolve-home-assistant-url":
        if len(sys.argv) < 3:
            print("Usage: hermes_config_helper.py resolve-home-assistant-url '<json-object>'", file=sys.stderr)
            sys.exit(1)
        try:
            payload = json.loads(sys.argv[2])
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON for resolve-home-assistant-url: {e}", file=sys.stderr)
            sys.exit(1)
        resolved = resolve_home_assistant_url(payload)
        if resolved is None:
            sys.exit(1)
        print(json.dumps(resolved))
        sys.exit(0)
    elif cmd == "sync-router-ssh-env":
        if len(sys.argv) < 5:
            print("Usage: hermes_config_helper.py sync-router-ssh-env <host> <user> <key_path>", file=sys.stderr)
            sys.exit(1)
        sys.exit(0 if sync_router_ssh_env(sys.argv[2], sys.argv[3], sys.argv[4]) else 1)
    elif cmd == "update-readiness-markers":
        if len(sys.argv) < 3:
            print("Usage: hermes_config_helper.py update-readiness-markers '<json-object>'", file=sys.stderr)
            sys.exit(1)
        try:
            payload = json.loads(sys.argv[2])
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON for update-readiness-markers: {e}", file=sys.stderr)
            sys.exit(1)
        api_keys = payload.get("api_keys", {})
        if not isinstance(api_keys, dict):
            api_keys = {}
        enable_openai_api = str(payload.get("enable_openai_api", "false")).lower() in ("1", "true", "yes")
        mcp_configured = str(payload.get("mcp_configured", "false")).lower() in ("1", "true", "yes")
        sys.exit(0 if update_readiness_markers(api_keys, enable_openai_api, mcp_configured) else 1)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
