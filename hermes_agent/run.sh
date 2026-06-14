#!/usr/bin/env bash
set -euo pipefail

# Unified logging (colors + emojis when stderr is a TTY)
ADDON_LOG_PATH="/addon_log.sh"
if [ ! -f "$ADDON_LOG_PATH" ] && [ -f "$(dirname "$0")/addon_log.sh" ]; then
  ADDON_LOG_PATH="$(dirname "$0")/addon_log.sh"
fi
if [ -f "$ADDON_LOG_PATH" ]; then
  # shellcheck disable=SC1091
  . "$ADDON_LOG_PATH"
else
  log_info() { printf '%s\n' "$*" >&2; }
  log_warn() { printf '%s\n' "$*" >&2; }
  log_error() { printf '%s\n' "$*" >&2; }
  log_ok() { printf '%s\n' "$*" >&2; }
  log_debug() { :; }
fi

# Ensure Homebrew and brew-installed binaries are in PATH
# This is needed for Hermes Agent skills that depend on CLI tools (gemini, aider, etc.)
export PATH="/home/linuxbrew/.linuxbrew/bin:/home/linuxbrew/.linuxbrew/sbin:${PATH}"

# Home Assistant add-on options are usually rendered to /data/options.json
OPTIONS_FILE="/data/options.json"

if [ ! -f "$OPTIONS_FILE" ]; then
  log_error "Missing $OPTIONS_FILE (add-on options)."
  exit 1
fi

# Read nested provider_api_keys with legacy flat-key fallback (preserves values after reinstall).
read_provider_option() {
  local field="$1"
  local nested flat
  nested=$(jq -r ".provider_api_keys.${field} // empty" "$OPTIONS_FILE" 2>/dev/null || true)
  if [ -n "$nested" ]; then
    printf '%s' "$nested"
    return 0
  fi
  jq -r ".${field} // empty" "$OPTIONS_FILE" 2>/dev/null || true
}

# Read scalar from nested expansion panel with legacy flat-key fallback.
read_nested_option() {
  local group="$1"
  local field="$2"
  local flat_key="${3:-$field}"
  local nested
  nested=$(jq -r ".${group}.${field} // empty" "$OPTIONS_FILE" 2>/dev/null || true)
  if [ -n "$nested" ] && [ "$nested" != "null" ]; then
    printf '%s' "$nested"
    return 0
  fi
  jq -r ".${flat_key} // empty" "$OPTIONS_FILE" 2>/dev/null || true
}

# Read list from nested group or legacy root key (array rows or comma-separated string).
join_nested_list_option_csv() {
  local group="$1"
  local field="$2"
  local flat_key="${3:-$field}"
  jq -r --arg group "$group" --arg field "$field" --arg flat "$flat_key" '
    (.[$group][$field] // .[$flat]) as $v
    | if ($v | type) == "array" then
        [ $v[]? | if type == "object" then .value elif type == "string" then . else empty end
          | select(. != null and (. | tostring | length) > 0) ]
        | join(",")
      elif ($v | type) == "string" then $v
      else "" end
  ' "$OPTIONS_FILE" 2>/dev/null || echo ""
}

export ADDON_LOG_LEVEL="$(jq -r '.addon_log_level // "info"' "$OPTIONS_FILE")"

HELPER_PATH="/hermes_config_helper.py"
if [ ! -f "$HELPER_PATH" ] && [ -f "$(dirname "$0")/hermes_config_helper.py" ]; then
  HELPER_PATH="$(dirname "$0")/hermes_config_helper.py"
fi

EXPORTER_PATH="/hermes_status_exporter.py"
if [ ! -f "$EXPORTER_PATH" ] && [ -f "$(dirname "$0")/hermes_status_exporter.py" ]; then
  EXPORTER_PATH="$(dirname "$0")/hermes_status_exporter.py"
fi

# ------------------------------------------------------------------------------
# Read add-on options (only add-on-specific knobs; Hermes Agent is configured via onboarding)
# ------------------------------------------------------------------------------

TZNAME=$(jq -r '.timezone // "Europe/Sofia"' "$OPTIONS_FILE")
GW_PUBLIC_URL="$(read_nested_option gateway_access gateway_public_url)"
HA_TOKEN="$(read_nested_option home_assistant homeassistant_token)"
# HA redacts password fields after save — reuse persisted token when the option is empty.
if [ -z "$HA_TOKEN" ] && [ -f /config/secrets/homeassistant.token ]; then
  HA_TOKEN="$(tr -d '\r\n' < /config/secrets/homeassistant.token)"
  log_debug "Loaded homeassistant_token from /config/secrets/homeassistant.token"
fi
ADDON_HTTP_PROXY="$(read_nested_option advanced_settings http_proxy)"
ENABLE_TERMINAL=$(jq -r '.enable_terminal // true' "$OPTIONS_FILE")
TERMINAL_PORT_RAW=$(jq -r '.terminal_port // 7681' "$OPTIONS_FILE")
ENABLE_WEB_INTERFACE="$(read_nested_option web_interface enable_web_interface)"
AUTO_START_WEB_INTERFACE="$(read_nested_option web_interface auto_start_with_integration)"

# SECURITY: Validate TERMINAL_PORT to prevent nginx config injection
# Only allow numeric values in valid port range (1024-65535)
if [[ "$TERMINAL_PORT_RAW" =~ ^[0-9]+$ ]] && [ "$TERMINAL_PORT_RAW" -ge 1024 ] && [ "$TERMINAL_PORT_RAW" -le 65535 ]; then
  TERMINAL_PORT="$TERMINAL_PORT_RAW"
else
  log_error "Invalid terminal_port '$TERMINAL_PORT_RAW'. Must be numeric 1024-65535. Using default 7681."
  TERMINAL_PORT="7681"
fi

# Router SSH (nested panel + legacy flat keys)
ROUTER_HOST="$(read_nested_option router_ssh host router_ssh_host)"
ROUTER_USER="$(read_nested_option router_ssh user router_ssh_user)"
ROUTER_KEY="$(read_nested_option router_ssh key_path router_ssh_key_path)"
if [ -z "$ROUTER_KEY" ]; then
  ROUTER_KEY="/config/keys/router_ssh"
fi
if [ "$ROUTER_KEY" = "/data/keys/router_ssh" ]; then
  ROUTER_KEY="/config/keys/router_ssh"
fi

CLEAN_LOCKS_ON_START="$(read_nested_option advanced_settings clean_session_locks_on_start)"
CLEAN_LOCKS_ON_EXIT="$(read_nested_option advanced_settings clean_session_locks_on_exit)"

# Gateway access (nested panel + legacy flat keys)
GATEWAY_MODE="$(read_nested_option gateway_access gateway_mode)"
GATEWAY_REMOTE_URL="$(read_nested_option gateway_access gateway_remote_url)"
GATEWAY_BIND_MODE="$(read_nested_option gateway_access gateway_bind_mode)"
GATEWAY_PORT="$(read_nested_option gateway_access gateway_port)"
ENABLE_OPENAI_API="$(read_nested_option gateway_access enable_openai_api)"
API_SERVER_PORT=8642
GATEWAY_AUTH_MODE="$(read_nested_option gateway_access gateway_auth_mode)"
GATEWAY_TRUSTED_PROXIES="$(join_nested_list_option_csv gateway_access gateway_trusted_proxies)"
GATEWAY_ADDITIONAL_ALLOWED_ORIGINS="$(join_nested_list_option_csv gateway_access gateway_additional_allowed_origins)"
CONTROLUI_DISABLE_DEVICE_AUTH="$(read_nested_option gateway_access controlui_disable_device_auth)"
FORCE_IPV4_DNS="$(read_nested_option advanced_settings force_ipv4_dns)"
SETUP_PROFILE=$(jq -r '.setup_profile // "home_assistant"' "$OPTIONS_FILE")
DEFAULT_PROVIDER=$(jq -r '.default_provider // "openrouter"' "$OPTIONS_FILE")
DEFAULT_MODEL_PRESET=$(jq -r '.default_model_preset // "custom"' "$OPTIONS_FILE")
DEFAULT_MODEL_OPT=$(jq -r '.default_model // empty' "$OPTIONS_FILE")
HASS_URL="$(read_nested_option home_assistant hass_url)"
ACCESS_MODE="$(read_nested_option gateway_access access_mode)"
FIRECRAWL_API_KEY_OPT="$(read_provider_option firecrawl_api_key)"
SEARXNG_URL_OPT="$(read_provider_option searxng_url)"
BOOTSTRAP_AUXILIARY_TITLE="false"
LOG_GATEWAY_URL_HINT="false"
NGINX_LOG_LEVEL="$(read_nested_option advanced_settings nginx_log_level)"
AUTO_CONFIGURE_MCP="$(read_nested_option home_assistant auto_configure_mcp)"
TOOL_TELEGRAM_ENABLED="$(read_nested_option tools_bootstrap tool_telegram_enabled)"
TOOL_BROWSER_ENABLED="$(read_nested_option tools_bootstrap tool_browser_enabled)"
TOOL_SKILLS_HUB_ENABLED="$(read_nested_option tools_bootstrap tool_skills_hub_enabled)"
OPENAI_API_KEY_OPT="$(read_provider_option openai_api_key)"
OPENROUTER_API_KEY_OPT="$(read_provider_option openrouter_api_key)"
ANTHROPIC_API_KEY_OPT="$(read_provider_option anthropic_api_key)"
GOOGLE_API_KEY_OPT="$(read_provider_option google_api_key)"
OLLAMA_API_KEY_OPT="$(read_provider_option ollama_api_key)"
MINIMAX_API_KEY_OPT="$(read_provider_option minimax_api_key)"
DISCORD_BOT_TOKEN_OPT="$(read_provider_option discord_bot_token)"
GITHUB_TOKEN_OPT="$(read_provider_option github_token)"
XAI_API_KEY_OPT="$(read_provider_option xai_api_key)"
HERMES_AGENT_VERSION_PRESET="$(read_nested_option advanced_settings hermes_agent_version_preset)"
HERMES_AGENT_VERSION_CUSTOM="$(read_nested_option advanced_settings hermes_agent_version_custom)"
ADDON_HERMES_DEFAULT_VERSION="0.16.0"
IMAGE_BAKED_HERMES_SPEC="${ADDON_HERMES_DEFAULT_VERSION}"
GW_ENV_VARS_TYPE=$(jq -r 'if (.advanced_settings.gateway_env_vars // .gateway_env_vars) == null then "null" else ((.advanced_settings.gateway_env_vars // .gateway_env_vars) | type) end' "$OPTIONS_FILE")
GW_ENV_VARS_RAW=$(jq -r '.advanced_settings.gateway_env_vars // .gateway_env_vars // empty' "$OPTIONS_FILE")
GW_ENV_VARS_JSON=$(jq -c '.advanced_settings.gateway_env_vars // .gateway_env_vars // []' "$OPTIONS_FILE")

# MQTT status sensors (nested panel + legacy flat keys)
MQTT_BROKER_HOST="$(read_nested_option mqtt_settings broker_host)"
MQTT_BROKER_PORT="$(read_nested_option mqtt_settings broker_port)"
MQTT_BROKER_USER="$(read_nested_option mqtt_settings broker_username)"
MQTT_BROKER_PASSWORD="$(read_nested_option mqtt_settings broker_password)"
if [ -z "$MQTT_BROKER_PASSWORD" ] && [ -f /config/secrets/mqtt.password ]; then
  MQTT_BROKER_PASSWORD="$(tr -d '\r\n' < /config/secrets/mqtt.password)"
  log_debug "Loaded mqtt_settings.broker_password from /config/secrets/mqtt.password"
fi
ENABLE_HA_STATUS_SENSORS="$(read_nested_option mqtt_settings enable_ha_status_sensors)"
PUBLISH_MQTT_DISCOVERY="$(read_nested_option mqtt_settings publish_mqtt_discovery)"
STATUS_POLL_INTERVAL_RAW="$(read_nested_option mqtt_settings status_poll_interval_seconds)"
MQTT_STATE_PREFIX="$(read_nested_option mqtt_settings state_prefix mqtt_state_prefix)"

# Defaults when nested panels are empty (fresh install or legacy options.json).
[ -z "$GATEWAY_MODE" ] && GATEWAY_MODE="local"
[ -z "$GATEWAY_BIND_MODE" ] && GATEWAY_BIND_MODE="loopback"
[ -z "$GATEWAY_PORT" ] && GATEWAY_PORT="18789"
[ -z "$GATEWAY_AUTH_MODE" ] && GATEWAY_AUTH_MODE="token"
[ -z "$ACCESS_MODE" ] && ACCESS_MODE="lan_https"
[ -z "$CONTROLUI_DISABLE_DEVICE_AUTH" ] && CONTROLUI_DISABLE_DEVICE_AUTH="true"
[ -z "$ENABLE_OPENAI_API" ] && ENABLE_OPENAI_API="false"
[ -z "$FORCE_IPV4_DNS" ] && FORCE_IPV4_DNS="true"
[ -z "$NGINX_LOG_LEVEL" ] && NGINX_LOG_LEVEL="minimal"
[ -z "$AUTO_CONFIGURE_MCP" ] && AUTO_CONFIGURE_MCP="false"
[ -z "$CLEAN_LOCKS_ON_START" ] && CLEAN_LOCKS_ON_START="true"
[ -z "$CLEAN_LOCKS_ON_EXIT" ] && CLEAN_LOCKS_ON_EXIT="true"
[ -z "$TOOL_BROWSER_ENABLED" ] && TOOL_BROWSER_ENABLED="true"
[ -z "$TOOL_SKILLS_HUB_ENABLED" ] && TOOL_SKILLS_HUB_ENABLED="true"
[ -z "$TOOL_TELEGRAM_ENABLED" ] && TOOL_TELEGRAM_ENABLED="false"
[ -z "$HERMES_AGENT_VERSION_PRESET" ] && HERMES_AGENT_VERSION_PRESET="custom"
[ -z "$HERMES_AGENT_VERSION_CUSTOM" ] && HERMES_AGENT_VERSION_CUSTOM="0.16.0"
[ -z "$ENABLE_HA_STATUS_SENSORS" ] && ENABLE_HA_STATUS_SENSORS="true"
[ -z "$PUBLISH_MQTT_DISCOVERY" ] && PUBLISH_MQTT_DISCOVERY="true"
[ -z "$STATUS_POLL_INTERVAL_RAW" ] && STATUS_POLL_INTERVAL_RAW="60"
[ -z "$MQTT_STATE_PREFIX" ] && MQTT_STATE_PREFIX="hermes"
[ -z "$MQTT_BROKER_PORT" ] && MQTT_BROKER_PORT="1883"
[ -z "$ENABLE_WEB_INTERFACE" ] && ENABLE_WEB_INTERFACE="true"
[ -z "$AUTO_START_WEB_INTERFACE" ] && AUTO_START_WEB_INTERFACE="true"

# Validate status poll interval (30-300 seconds)
if [[ "$STATUS_POLL_INTERVAL_RAW" =~ ^[0-9]+$ ]] && [ "$STATUS_POLL_INTERVAL_RAW" -ge 30 ] && [ "$STATUS_POLL_INTERVAL_RAW" -le 300 ]; then
  STATUS_POLL_INTERVAL_SECONDS="$STATUS_POLL_INTERVAL_RAW"
else
  log_warn "Invalid status_poll_interval_seconds '$STATUS_POLL_INTERVAL_RAW'. Using default 60."
  STATUS_POLL_INTERVAL_SECONDS="60"
fi

# Sanitize MQTT state topic prefix (alphanumeric + underscore/hyphen only)
if [[ "$MQTT_STATE_PREFIX" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  MQTT_STATE_PREFIX_SAFE="$MQTT_STATE_PREFIX"
else
  log_warn "Invalid mqtt_state_prefix '$MQTT_STATE_PREFIX'. Using default 'hermes'."
  MQTT_STATE_PREFIX_SAFE="hermes"
fi

export TZ="$TZNAME"

# ------------------------------------------------------------------------------
# Setup profile — simplify first-run defaults without hiding advanced options
# ------------------------------------------------------------------------------
if [ -f "$HELPER_PATH" ]; then
  PROFILE_JSON=$(jq -n \
    --arg setup_profile "$SETUP_PROFILE" \
    --arg access_mode "$ACCESS_MODE" \
    --arg auto_configure_mcp "$AUTO_CONFIGURE_MCP" \
    --arg homeassistant_token "$HA_TOKEN" \
    '{
      setup_profile: $setup_profile,
      access_mode: $access_mode,
      auto_configure_mcp: $auto_configure_mcp,
      homeassistant_token: $homeassistant_token
    }')
  RESOLVED_PROFILE=$(python3 "$HELPER_PATH" resolve-setup-profile "$PROFILE_JSON" 2>/dev/null || true)
  if [ -n "$RESOLVED_PROFILE" ]; then
    resolved_access_mode=$(echo "$RESOLVED_PROFILE" | jq -r '.access_mode // empty')
    if [ -n "$resolved_access_mode" ]; then
      ACCESS_MODE="$resolved_access_mode"
    fi
    EFFECTIVE_AUTO_CONFIGURE_MCP=$(echo "$RESOLVED_PROFILE" | jq -r 'if .auto_configure_mcp then "true" else "false" end')
    BOOTSTRAP_AUXILIARY_TITLE=$(echo "$RESOLVED_PROFILE" | jq -r 'if .bootstrap_auxiliary_title then "true" else "false" end')
    LOG_GATEWAY_URL_HINT=$(echo "$RESOLVED_PROFILE" | jq -r 'if .log_gateway_url_hint then "true" else "false" end')
    log_info "setup_profile=${SETUP_PROFILE} — effective access_mode=${ACCESS_MODE}"
  else
    EFFECTIVE_AUTO_CONFIGURE_MCP="$AUTO_CONFIGURE_MCP"
  fi
else
  EFFECTIVE_AUTO_CONFIGURE_MCP="$AUTO_CONFIGURE_MCP"
fi

# ------------------------------------------------------------------------------
# Home Assistant instance autodetection (hass_url empty/local → supervisor/loopback)
# ------------------------------------------------------------------------------
EFFECTIVE_HASS_URL="$HASS_URL"
MCP_HA_URL=""
HA_URL_SOURCE="user"
HA_INTERNAL_HOST=""
HA_INTERNAL_PORT="8123"

load_bashio() {
  if [ -f /etc/bashio.sh ]; then
    # shellcheck disable=SC1091
    . /etc/bashio.sh
    return 0
  fi
  return 1
}

cloudflared_addon_running() {
  if load_bashio && bashio::addons.installed "a0d7b954_cloudflared" 2>/dev/null; then
    bashio::addons.running "a0d7b954_cloudflared" 2>/dev/null && return 0
  fi
  if [ -n "${SUPERVISOR_TOKEN:-}" ]; then
    local state
    state=$(curl -fsS -m 5 -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
      "http://supervisor/addons/a0d7b954_cloudflared/info" 2>/dev/null \
      | jq -r '.data.state // empty' 2>/dev/null || true)
    [ "$state" = "started" ] && return 0
  fi
  return 1
}

resolve_ha_instance_urls() {
  if [ ! -f "$HELPER_PATH" ]; then
    EFFECTIVE_HASS_URL="${HASS_URL:-http://127.0.0.1:8123}"
    MCP_HA_URL="${EFFECTIVE_HASS_URL%/}/api/mcp"
    return 0
  fi

  local supervisor_available="false"
  if [ -n "${SUPERVISOR_TOKEN:-}" ]; then
    supervisor_available="true"
  fi

  if load_bashio; then
    HA_INTERNAL_HOST="$(bashio::services homeassistant "host" 2>/dev/null || true)"
    HA_INTERNAL_PORT="$(bashio::services homeassistant "port" 2>/dev/null || true)"
    if [ -z "$HA_INTERNAL_PORT" ]; then
      HA_INTERNAL_PORT="8123"
    fi
  fi

  local ha_json resolved
  ha_json=$(jq -n \
    --arg hass_url "$HASS_URL" \
    --arg supervisor_available "$supervisor_available" \
    --arg internal_host "$HA_INTERNAL_HOST" \
    --arg internal_port "$HA_INTERNAL_PORT" \
    '{
      hass_url: $hass_url,
      supervisor_available: $supervisor_available,
      internal_host: $internal_host,
      internal_port: $internal_port
    }')
  resolved=$(python3 "$HELPER_PATH" resolve-home-assistant-url "$ha_json" 2>/dev/null || true)
  if [ -n "$resolved" ]; then
    EFFECTIVE_HASS_URL=$(echo "$resolved" | jq -r '.homeassistant_url // empty')
    MCP_HA_URL=$(echo "$resolved" | jq -r '.mcp_url // empty')
    HA_URL_SOURCE=$(echo "$resolved" | jq -r '.source // "user"')
  fi
  if [ -z "$EFFECTIVE_HASS_URL" ]; then
    EFFECTIVE_HASS_URL="http://127.0.0.1:8123"
  fi
  if [ -z "$MCP_HA_URL" ]; then
    MCP_HA_URL="${EFFECTIVE_HASS_URL%/}/api/mcp"
  fi
  log_info "Home Assistant URL (${HA_URL_SOURCE}): ${EFFECTIVE_HASS_URL} (MCP: ${MCP_HA_URL})"
}

verify_ha_instance_reachable() {
  if [ -z "$HA_TOKEN" ]; then
    return 0
  fi
  local probe_url="${EFFECTIVE_HASS_URL%/}/api/"
  if curl -fsS -m 8 -H "Authorization: Bearer ${HA_TOKEN}" "$probe_url" >/dev/null 2>&1; then
    log_info "Verified Home Assistant API at ${EFFECTIVE_HASS_URL}"
    return 0
  fi
  log_warn "Could not verify Home Assistant at ${EFFECTIVE_HASS_URL}"
  log_warn "If MCP or HA tools fail, set hass_url to your HA URL (e.g. http://homeassistant:8123 or your external URL)"
  return 0
}

resolve_ha_instance_urls
verify_ha_instance_reachable

apply_reverse_proxy_defaults() {
  if [ "$ACCESS_MODE" != "lan_reverse_proxy" ]; then
    return 0
  fi
  if [ -n "$GATEWAY_TRUSTED_PROXIES" ]; then
    return 0
  fi
  GATEWAY_TRUSTED_PROXIES="127.0.0.1,172.30.0.0/16,10.0.0.0/8"
  if cloudflared_addon_running; then
    log_info "Cloudflared add-on detected — applied gateway_trusted_proxies: ${GATEWAY_TRUSTED_PROXIES}"
    log_info "Recommended for Cloudflare Tunnel: access_mode=lan_https with noTLSVerify on origin (see DOCS.md)."
  else
    log_warn "gateway_trusted_proxies was empty — applied defaults: ${GATEWAY_TRUSTED_PROXIES}"
    log_warn "trusted-proxy requires X-Forwarded-User from your reverse proxy (e.g. NPM custom header)."
  fi
}

# ------------------------------------------------------------------------------
# Access mode presets — override individual gateway settings for common scenarios
# ------------------------------------------------------------------------------
ENABLE_HTTPS_PROXY=false
GATEWAY_INTERNAL_PORT="$GATEWAY_PORT"

case "$ACCESS_MODE" in
  local_only)
    GATEWAY_BIND_MODE="loopback"
    GATEWAY_AUTH_MODE="token"
    log_info "Access mode: local_only (loopback + token, Ingress/terminal only)"
    ;;
  lan_https)
    # Gateway binds loopback on internal port; nginx terminates TLS on the external port.
    GATEWAY_BIND_MODE="loopback"
    GATEWAY_AUTH_MODE="token"
    ENABLE_HTTPS_PROXY=true
    GATEWAY_INTERNAL_PORT=$((GATEWAY_PORT + 1))
    log_info "Access mode: lan_https (built-in HTTPS proxy on 0.0.0.0:${GATEWAY_PORT})"
    ;;
  lan_reverse_proxy)
    GATEWAY_BIND_MODE="lan"
    GATEWAY_AUTH_MODE="trusted-proxy"
    apply_reverse_proxy_defaults
    log_info "Access mode: lan_reverse_proxy (LAN bind + trusted-proxy auth)"
    ;;
  tailnet_https)
    GATEWAY_BIND_MODE="tailnet"
    GATEWAY_AUTH_MODE="token"
    log_info "Access mode: tailnet_https (Tailscale bind + token auth)"
    ;;
  custom|*)
    log_info "Access mode: custom (using individual gateway_bind_mode/auth_mode settings)"
    ;;
esac

# Reduce risk of secrets ending up in logs
set +x

# Optional outbound proxy from add-on settings.
# If set, apply it to both HTTP and HTTPS for Node/undici/Hermes Agent tooling.
if [ -n "$ADDON_HTTP_PROXY" ]; then
  if [[ "$ADDON_HTTP_PROXY" =~ ^https?://[^[:space:]]+$ ]]; then
    # Keep local traffic direct to avoid accidental proxying of loopback/LAN services.
    DEFAULT_NO_PROXY="localhost,127.0.0.1,::1,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,.local"

    export HTTP_PROXY="$ADDON_HTTP_PROXY"
    export HTTPS_PROXY="$ADDON_HTTP_PROXY"
    export http_proxy="$ADDON_HTTP_PROXY"
    export https_proxy="$ADDON_HTTP_PROXY"
    export NO_PROXY="${NO_PROXY:+${NO_PROXY},}${DEFAULT_NO_PROXY}"
    export no_proxy="${no_proxy:+${no_proxy},}${DEFAULT_NO_PROXY}"
    log_info "Outbound HTTP/HTTPS proxy enabled from add-on configuration."
    log_info "Applied NO_PROXY defaults for localhost/private network ranges."
  else
    log_warn "Invalid http_proxy value in add-on options; expected URL like http://host:port"
  fi
fi

# Optional network hardening/workaround: force IPv4-first DNS ordering for Node.js.
# Helps in environments where IPv6 resolves but has no working egress.
if [ "$FORCE_IPV4_DNS" = "true" ] || [ "$FORCE_IPV4_DNS" = "1" ]; then
  if [ -n "${NODE_OPTIONS:-}" ]; then
    export NODE_OPTIONS="${NODE_OPTIONS} --dns-result-order=ipv4first"
  else
    export NODE_OPTIONS="--dns-result-order=ipv4first"
  fi
  log_info "Enabled IPv4-first DNS ordering (NODE_OPTIONS=--dns-result-order=ipv4first)"
fi

# HA add-ons mount persistent storage at /config (maps to /addon_configs/<slug> on the host).
export HOME=/config
export PIP_BREAK_SYSTEM_PACKAGES=1
python3 -m pip config set global.break-system-packages true 2>/dev/null || true

# Explicitly set Hermes Agent directories to ensure they persist across add-on updates
# This prevents loss of installed skills, configuration, and workspace state
export HERMES_HOME=/config/.hermes
export HERMES_CONFIG_DIR=/config/.hermes
export HERMES_WORKSPACE_DIR=/config/hermesd
export XDG_CONFIG_HOME=/config

mkdir -p /config/.hermes /config/.hermes/identity /config/hermesd /config/keys /config/secrets

# Hermes npm installs expose a PyPI wheel; without this stamp upstream detects "pip"
# and shows the unsupported pip-install banner. The add-on is a container install.
if [ "$(tr -d '\r\n' < "${HERMES_HOME}/.install_method" 2>/dev/null || true)" != "docker" ]; then
  printf '%s\n' docker > "${HERMES_HOME}/.install_method"
  chmod 600 "${HERMES_HOME}/.install_method" 2>/dev/null || true
  log_info "Stamped ${HERMES_HOME}/.install_method as docker"
fi

if [ -n "$MQTT_BROKER_PASSWORD" ]; then
  printf '%s' "$MQTT_BROKER_PASSWORD" > /config/secrets/mqtt.password
  chmod 600 /config/secrets/mqtt.password 2>/dev/null || true
fi

# Router SSH keys live on persistent /config storage (migrate legacy /data path once).
LEGACY_ROUTER_KEY="/data/keys/router_ssh"
if [ -f "$LEGACY_ROUTER_KEY" ] && [ ! -f "/config/keys/router_ssh" ]; then
  cp "$LEGACY_ROUTER_KEY" "/config/keys/router_ssh"
  chmod 600 "/config/keys/router_ssh" 2>/dev/null || true
  log_info "Migrated router SSH key from ${LEGACY_ROUTER_KEY} to /config/keys/router_ssh"
fi
if [ "$ROUTER_KEY" = "$LEGACY_ROUTER_KEY" ] && [ -f "/config/keys/router_ssh" ]; then
  ROUTER_KEY="/config/keys/router_ssh"
fi

# ------------------------------------------------------------------------------
# Hermes Agent npm version reconcile (must run BEFORE redirecting npm prefix to /config)
# ------------------------------------------------------------------------------
resolve_hermes_agent_npm_spec() {
  local preset
  preset="$(echo "${HERMES_AGENT_VERSION_PRESET:-custom}" | tr '[:upper:]' '[:lower:]')"
  case "$preset" in
    latest)
      echo "latest"
      ;;
    custom)
      if [ -n "${HERMES_AGENT_VERSION_CUSTOM:-}" ]; then
        echo "$HERMES_AGENT_VERSION_CUSTOM"
      else
        log_warn "hermes_agent_version_preset=custom but hermes_agent_version_custom is empty; using ${ADDON_HERMES_DEFAULT_VERSION}." >&2
        echo "$ADDON_HERMES_DEFAULT_VERSION"
      fi
      ;;
    *)
      # Legacy pinned presets (e.g. 0.15.2) still in saved options.json
      echo "$preset"
      ;;
  esac
}

# Install hermes-agent to the image-global npm prefix (matches Dockerfile layout).
# Never use /config/.node_global — postinstall pip fails with PEP 668 on Debian.
install_hermes_agent_npm() {
  local spec="$1"
  local image_npm_prefix="/usr/local"

  rm -rf "/config/.node_global/lib/node_modules/hermes-agent" 2>/dev/null || true
  rm -f "/config/.node_global/bin/hermes" "/config/.node_global/bin/hermes-agent" 2>/dev/null || true

  # Image-baked or prior reconcile leaves /usr/local/bin/hermes; npm EEXIST without this.
  rm -rf "${image_npm_prefix}/lib/node_modules/hermes-agent" 2>/dev/null || true
  rm -f "${image_npm_prefix}/bin/hermes" "${image_npm_prefix}/bin/hermes-agent" 2>/dev/null || true

  HOME=/root \
    NPM_CONFIG_PREFIX="${image_npm_prefix}" \
    NPM_CONFIG_USERCONFIG=/root/.npmrc \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    npm install -g "hermes-agent@${spec}" --prefix "${image_npm_prefix}"
}

reconcile_hermes_agent_version() {
  local spec marker installed_marker
  spec="$(resolve_hermes_agent_npm_spec)"
  marker="/config/.hermes/.addon-managed-hermes-version"
  installed_marker=""
  if [ -f "$marker" ]; then
    installed_marker="$(tr -d '\r\n' < "$marker" 2>/dev/null || true)"
  fi

  if command -v hermes >/dev/null 2>&1; then
    if [ "$installed_marker" = "$spec" ]; then
      log_info "Hermes Agent npm spec '${spec}' already installed."
      return 0
    fi
    if [ "$installed_marker" = "__image_baked__" ] && [ "$spec" = "latest" ]; then
      log_info "Using image-baked hermes CLI (preset: latest)."
      printf '%s\n' "$spec" > "$marker"
      chmod 600 "$marker" 2>/dev/null || true
      return 0
    fi
    if [ -z "$installed_marker" ] && [ "$spec" = "$IMAGE_BAKED_HERMES_SPEC" ]; then
      log_info "Using image-baked hermes CLI (${IMAGE_BAKED_HERMES_SPEC}); seeding version marker."
      printf '%s\n' "$spec" > "$marker"
      chmod 600 "$marker" 2>/dev/null || true
      return 0
    fi
    if [ -z "$installed_marker" ] && [ "$spec" = "latest" ]; then
      log_info "Using image-baked hermes CLI; seeding version marker (preset: latest)."
      printf '%s\n' "$spec" > "$marker"
      chmod 600 "$marker" 2>/dev/null || true
      return 0
    fi
  fi

  log_info "Installing/reconciling hermes-agent@${spec} (add-on preset: ${HERMES_AGENT_VERSION_PRESET})..."
  if install_hermes_agent_npm "$spec"; then
    printf '%s\n' "$spec" > "$marker"
    chmod 600 "$marker" 2>/dev/null || true
    log_info "Hermes Agent installed ($(hermes --version 2>/dev/null | head -1 || echo unknown))."
    return 0
  fi

  log_error "Failed to install hermes-agent@${spec}. Check network connectivity and version tag."
  if command -v hermes >/dev/null 2>&1; then
    log_warn "Continuing with previously installed hermes CLI ($(hermes --version 2>/dev/null | head -1 || echo unknown))."
    printf '%s\n' "$spec" > "$marker"
    chmod 600 "$marker" 2>/dev/null || true
    return 0
  fi
  return 1
}

if ! reconcile_hermes_agent_version; then
  exit 1
fi

if [ -f /repair_hermes_wheel.py ]; then
  python3 /repair_hermes_wheel.py || true
fi

if ! command -v hermes >/dev/null 2>&1; then
  log_error "hermes CLI is not installed. Set hermes_agent_version_preset and restart the add-on."
  exit 1
fi

# Resolve image-global hermes-agent package root (npm root -g can disagree with install prefix).
resolve_image_hermes_node_modules() {
  local candidate hermes_bin prefix_root
  for candidate in \
    "/usr/local/lib/node_modules" \
    "$(HOME=/root NPM_CONFIG_PREFIX=/usr/local npm root -g 2>/dev/null)" \
    "$(HOME=/root npm root -g 2>/dev/null)" \
    "/usr/lib/node_modules"; do
    [ -n "$candidate" ] || continue
    if [ -d "${candidate}/hermes-agent" ]; then
      echo "$candidate"
      return 0
    fi
  done
  hermes_bin="$(command -v hermes 2>/dev/null || true)"
  if [ -n "$hermes_bin" ]; then
    prefix_root="$(cd "$(dirname "$hermes_bin")/.." 2>/dev/null && pwd || true)"
    candidate="${prefix_root}/lib/node_modules"
    if [ -n "$prefix_root" ] && [ -d "${candidate}/hermes-agent" ]; then
      echo "$candidate"
      return 0
    fi
  fi
  return 1
}

# ------------------------------------------------------------------------------
# Sync built-in Hermes Agent skills from image to persistent storage
# On each startup, copy new/updated built-in skills so they survive rebuilds.
# We sync them to /config/.hermes/skills and symlink back.
# ------------------------------------------------------------------------------
IMAGE_NPM_MODULES="$(resolve_image_hermes_node_modules 2>/dev/null || true)"
IMAGE_SKILLS_DIR=""
if [ -n "$IMAGE_NPM_MODULES" ]; then
  IMAGE_SKILLS_DIR="${IMAGE_NPM_MODULES}/hermes-agent/skills"
fi
PERSISTENT_SKILLS_DIR="/config/.hermes/skills"

if [ -n "$IMAGE_SKILLS_DIR" ] && [ -d "$IMAGE_SKILLS_DIR" ] && [ ! -L "$IMAGE_SKILLS_DIR" ]; then
  mkdir -p "$PERSISTENT_SKILLS_DIR"
  # Sync skills: --update replaces older files so upgrades propagate,
  # but doesn't delete user-added files in persistent storage.
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --update "$IMAGE_SKILLS_DIR/" "$PERSISTENT_SKILLS_DIR/" 2>/dev/null || true
  else
    cp -ru "$IMAGE_SKILLS_DIR/"* "$PERSISTENT_SKILLS_DIR/" 2>/dev/null || true
  fi
  # Replace image skills dir with symlink to persistent copy
  rm -rf "$IMAGE_SKILLS_DIR"
  ln -sf "$PERSISTENT_SKILLS_DIR" "$IMAGE_SKILLS_DIR"
  log_info "Synced built-in skills to persistent storage at $PERSISTENT_SKILLS_DIR"
elif [ -n "$IMAGE_SKILLS_DIR" ] && [ -L "$IMAGE_SKILLS_DIR" ]; then
  log_info "Built-in skills already linked to persistent storage"
elif [ -d "$PERSISTENT_SKILLS_DIR" ]; then
  log_info "Built-in skills served from persistent storage at $PERSISTENT_SKILLS_DIR"
else
  log_warn "Built-in skills directory not found (image package: ${IMAGE_SKILLS_DIR:-unknown})"
fi

# Persist user-installed node skills across Docker image rebuilds.
# Redirect npm global installs to PERSISTENT_NODE_GLOBAL so dashboard/skill npm
# packages survive container rebuilds. Add-on bootstrap (hermes-agent, agent-browser)
# still installs to /usr/local explicitly via NPM_CONFIG_PREFIX.
# NOTE: This MUST come after the skills sync above (which needs the original npm root -g).
# ------------------------------------------------------------------------------
PERSISTENT_NODE_GLOBAL="/config/.node_global"
mkdir -p "$PERSISTENT_NODE_GLOBAL"
npm config set prefix "$PERSISTENT_NODE_GLOBAL" 2>/dev/null || true
export PNPM_HOME="${PERSISTENT_NODE_GLOBAL}/pnpm"
mkdir -p "$PNPM_HOME"
export PATH="${PERSISTENT_NODE_GLOBAL}/bin:/usr/local/bin:${PNPM_HOME}:${PATH}"
export NODE_PATH="${PERSISTENT_NODE_GLOBAL}/lib/node_modules:/usr/local/lib/node_modules:${NODE_PATH:-}"

if ! command -v uv >/dev/null 2>&1; then
  log_warn "uv not found on PATH; runtime Python installs fall back to pip."
fi

safe_export_secret_env() {
  local key="$1"
  local value="$2"
  if [ -z "$value" ]; then
    return 0
  fi
  export "${key}=${value}"
  log_info "Loaded ${key} from add-on configuration."
}

install_python_package_if_missing() {
  local module_name="$1"
  local package_spec="$2"
  if python3 -c "import ${module_name}" >/dev/null 2>&1; then
    log_info "Python dependency '${package_spec}' already available."
    return 0
  fi
  log_info "Installing missing Python dependency '${package_spec}' (system-wide)..."
  if command -v uv >/dev/null 2>&1 \
    && uv pip install --system --break-system-packages --no-cache "${package_spec}" >/dev/null 2>&1; then
    log_info "Installed Python dependency '${package_spec}' via uv (system)."
  elif python3 -m pip install --no-cache-dir --break-system-packages "${package_spec}" >/dev/null 2>&1; then
    log_info "Installed Python dependency '${package_spec}' via pip (system)."
  else
    log_warn "Could not install Python dependency '${package_spec}'. Tool may stay unavailable."
    return 1
  fi
}

install_npm_package_if_missing() {
  local command_name="$1"
  local package_name="$2"
  if command -v "${command_name}" >/dev/null 2>&1; then
    log_info "Node dependency '${package_name}' already available."
    return 0
  fi
  log_info "Installing missing Node dependency '${package_name}' (system-wide)..."
  if HOME=/root \
    NPM_CONFIG_PREFIX="/usr/local" \
    NPM_CONFIG_USERCONFIG=/root/.npmrc \
    npm install -g "${package_name}" >/dev/null 2>&1; then
    log_info "Installed Node dependency '${package_name}' (system)."
  else
    log_warn "Could not install Node dependency '${package_name}'. Tool may stay unavailable."
    return 1
  fi
}

initialize_skills_hub_if_enabled() {
  if [ "$TOOL_SKILLS_HUB_ENABLED" != "true" ] && [ "$TOOL_SKILLS_HUB_ENABLED" != "1" ]; then
    return 0
  fi
  local skills_init_flag="/config/.hermes/.skills_hub_initialized"
  if [ -f "$skills_init_flag" ]; then
    return 0
  fi
  if ! command -v hermes >/dev/null 2>&1; then
    log_warn "Hermes CLI is unavailable; cannot initialize Skills Hub yet."
    return 0
  fi
  load_hermes_env_file
  if hermes skills list >/dev/null 2>&1; then
    date -u +"%Y-%m-%dT%H:%M:%SZ" > "$skills_init_flag"
    log_info "Skills Hub directory initialized."
  else
    log_warn "Skills Hub initialization failed. You can retry in terminal with: hermes skills list"
  fi
}

bootstrap_selected_tools() {
  install_python_package_if_missing "mcp" "mcp"
  install_python_package_if_missing "edge_tts" "edge-tts"
  install_python_package_if_missing "ddgs" "ddgs"

  if [ "$TOOL_TELEGRAM_ENABLED" = "true" ] || [ "$TOOL_TELEGRAM_ENABLED" = "1" ]; then
    install_python_package_if_missing "telegram" "python-telegram-bot[webhooks]==22.6"
  fi

  if [ -n "$DISCORD_BOT_TOKEN_OPT" ]; then
    install_python_package_if_missing "discord" "discord.py[voice]==2.7.1"
    install_python_package_if_missing "brotlicffi" "brotlicffi==1.2.0.1"
  fi

  if [ "$TOOL_BROWSER_ENABLED" = "true" ] || [ "$TOOL_BROWSER_ENABLED" = "1" ]; then
    install_npm_package_if_missing "agent-browser" "agent-browser@latest"
  fi
}

load_hermes_env_file() {
  if [ -f /config/.hermes/.env ]; then
    set -a
    # shellcheck disable=SC1091
    . /config/.hermes/.env
    set +a
  fi
}

export_gateway_tool_env() {
  load_hermes_env_file
  safe_export_secret_env "HASS_TOKEN" "$HA_TOKEN"
  if [ -n "$EFFECTIVE_HASS_URL" ]; then
    export HASS_URL="$EFFECTIVE_HASS_URL"
    export HOMEASSISTANT_URL="$EFFECTIVE_HASS_URL"
  fi
  export HERMES_GATEWAY_SESSION=1
  export HERMES_INTERACTIVE=1
}

require_hermes_cli() {
  if command -v hermes >/dev/null 2>&1; then
    return 0
  fi
  log_error "hermes CLI is not installed. Set hermes_agent_version_preset and restart the add-on."
  return 1
}

ensure_default_hermes_profile() {
  mkdir -p "${HERMES_HOME:-/config/.hermes}"
  if [ ! -f "${HERMES_HOME}/config.yaml" ]; then
    log_info "No ${HERMES_HOME}/config.yaml yet; first-run bootstrap will populate it."
  fi
  if ! command -v hermes >/dev/null 2>&1; then
    return 0
  fi
  load_hermes_env_file
  if hermes profile >/dev/null 2>&1; then
    log_info "Hermes profile summary:"
    hermes profile 2>/dev/null | head -8 || true
  fi
  if hermes gateway list >/dev/null 2>&1; then
    log_info "Hermes gateway list:"
    hermes gateway list 2>/dev/null | head -5 || true
  fi
  return 0
}

run_hermes_gateway() {
  export HERMES_GATEWAY_NO_SUPERVISE=1
  hermes gateway run --no-supervise &
}

resolve_hermes_web_dist() {
  local web_dist=""
  web_dist="$(python3 - <<'PY' 2>/dev/null || true
import pathlib
try:
    import hermes_cli
except ImportError:
    raise SystemExit(0)
dist = pathlib.Path(hermes_cli.__file__).resolve().parent / "web_dist"
if (dist / "index.html").is_file():
    print(dist)
PY
)"
  if [ -n "$web_dist" ] && [ -f "${web_dist}/index.html" ]; then
    echo "$web_dist"
    return 0
  fi
  return 1
}

run_hermes_dashboard() {
  local web_dist port host
  port="$GATEWAY_INTERNAL_PORT"
  host="127.0.0.1"

  if ! command -v hermes >/dev/null 2>&1; then
    log_warn "hermes CLI missing; cannot start dashboard Web UI."
    return 1
  fi
  if ! hermes dashboard --help >/dev/null 2>&1; then
    log_warn "hermes dashboard unavailable in installed Hermes version."
    return 1
  fi

  web_dist="$(resolve_hermes_web_dist 2>/dev/null || true)"
  if [ -z "$web_dist" ]; then
    log_warn "Hermes dashboard web_dist not found; HTTPS gateway UI will return 502."
    return 1
  fi

  export HERMES_WEB_DIST="$web_dist"
  log_info "Starting Hermes dashboard (Web UI) on ${host}:${port} ..."
  hermes dashboard --port "$port" --host "$host" --no-open --skip-build &
  DASHBOARD_PID=$!
  return 0
}

start_cdp_chromium_if_enabled() {
  if [ "$TOOL_BROWSER_ENABLED" != "true" ] && [ "$TOOL_BROWSER_ENABLED" != "1" ]; then
    return 0
  fi
  if command -v ss >/dev/null 2>&1 && ss -tln 2>/dev/null | grep -q ":9222 "; then
    log_info "CDP Chromium already listening on 127.0.0.1:9222"
    return 0
  fi

  local chrome_bin=""
  for candidate in chromium chromium-browser google-chrome google-chrome-stable; do
    if command -v "$candidate" >/dev/null 2>&1; then
      chrome_bin="$candidate"
      break
    fi
  done
  if [ -z "$chrome_bin" ]; then
    log_warn "No Chromium binary found; browser-cdp tool may stay unavailable"
    return 0
  fi

  log_info "Starting headless Chromium CDP endpoint on 127.0.0.1:9222 for browser-cdp tool..."
  "$chrome_bin" \
    --headless=new \
    --no-sandbox \
    --disable-gpu \
    --disable-dev-shm-usage \
    --remote-debugging-address=127.0.0.1 \
    --remote-debugging-port=9222 \
    about:blank >/dev/null 2>&1 &
  CDP_CHROMIUM_PID=$!
}

safe_export_secret_env "OPENAI_API_KEY" "$OPENAI_API_KEY_OPT"
safe_export_secret_env "OPENROUTER_API_KEY" "$OPENROUTER_API_KEY_OPT"
safe_export_secret_env "ANTHROPIC_API_KEY" "$ANTHROPIC_API_KEY_OPT"
safe_export_secret_env "GOOGLE_API_KEY" "$GOOGLE_API_KEY_OPT"
safe_export_secret_env "MINIMAX_API_KEY" "$MINIMAX_API_KEY_OPT"
safe_export_secret_env "DISCORD_BOT_TOKEN" "$DISCORD_BOT_TOKEN_OPT"
safe_export_secret_env "GITHUB_TOKEN" "$GITHUB_TOKEN_OPT"
safe_export_secret_env "XAI_API_KEY" "$XAI_API_KEY_OPT"

# Protect critical runtime variables from accidental override via gateway_env_vars.
is_reserved_gateway_env_var() {
  case "$1" in
    # Critical runtime paths/process vars.
    HOME|PATH|PWD|OLDPWD|SHLVL|TZ|XDG_CONFIG_HOME|PNPM_HOME|NODE_PATH|NODE_OPTIONS|NODE_NO_WARNINGS)
      return 0
      ;;
    # Low-level injection vectors that can alter process/linker/shell behavior.
    LD_*|DYLD_*|BASH_ENV|ENV|BASH_FUNC_*)
      return 0
      ;;
    # Proxy vars managed by add-on options.
    HTTP_PROXY|HTTPS_PROXY|NO_PROXY|http_proxy|https_proxy|no_proxy)
      return 0
      ;;
    # Add-on internal control vars.
    HERMES_*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

try_export_gateway_env_var() {
  local key="$1"
  local value="$2"

  if [ -z "$key" ]; then
    return 0
  fi

  # Validate variable name format
  if ! [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    log_warn "Invalid environment variable name: '$key' (must start with letter/underscore, skip)"
    return 0
  fi

  # Protect critical runtime variables from accidental override.
  if is_reserved_gateway_env_var "$key"; then
    log_warn "Reserved environment variable '$key' cannot be overridden via gateway_env_vars (skip)"
    return 0
  fi

  # Enforce max variable name length
  if [ ${#key} -gt $max_var_name_size ]; then
    log_warn "Environment variable name too long: '$key' (max $max_var_name_size chars, skip)"
    return 0
  fi

  # Enforce max variable value length
  if [ ${#value} -gt $max_var_value_size ]; then
    log_warn "Environment variable value too long for '$key' (max $max_var_value_size chars, skip)"
    return 0
  fi

  # Enforce limit on number of variables
  if [ $env_count -ge $max_env_vars ]; then
    log_warn "Maximum environment variables limit ($max_env_vars) reached (skip)"
    return 0
  fi

  export "$key=$value"
  env_count=$((env_count + 1))
  log_info "Exported gateway env var: $key"
}

# Export gateway environment variables from add-on config
# These are user-defined variables that should be available to the gateway process.
# Primary format: array of {name, value} objects.
if [ "$GW_ENV_VARS_TYPE" = "array" ] || [ "$GW_ENV_VARS_TYPE" = "object" ] || { [ "$GW_ENV_VARS_TYPE" = "string" ] && [ -n "$GW_ENV_VARS_RAW" ]; }; then
  env_count=0
  max_env_vars=50
  max_var_name_size=255
  max_var_value_size=10000

  if [ "$GW_ENV_VARS_TYPE" = "array" ] && [ "$GW_ENV_VARS_JSON" != "[]" ]; then
    log_info "Setting gateway environment variables from list config..."

    invalid_entries_count=$(printf '%s' "$GW_ENV_VARS_JSON" | jq '[.[] | select((type != "object") or ((.name | type) != "string") or (has("value") | not))] | length')
    if [ "$invalid_entries_count" -gt 0 ]; then
      log_warn "Found $invalid_entries_count invalid gateway_env_vars entries; expected objects with 'name' and 'value' keys (skip)"
    fi

    while IFS= read -r -d '' key && IFS= read -r -d '' value; do
      try_export_gateway_env_var "$key" "$value"
    done < <(printf '%s' "$GW_ENV_VARS_JSON" | jq -j '.[] | select((type == "object") and ((.name | type) == "string") and (has("value"))) | .name, "\u0000", (.value | tostring), "\u0000"')
  elif [ "$GW_ENV_VARS_TYPE" = "object" ] && [ "$GW_ENV_VARS_JSON" != "{}" ]; then
    # Backward compatibility for old map/object configuration.
    log_info "Setting gateway environment variables from object config (legacy format)..."
    while IFS= read -r -d '' key && IFS= read -r -d '' value; do
      try_export_gateway_env_var "$key" "$value"
    done < <(printf '%s' "$GW_ENV_VARS_JSON" | jq -j 'to_entries[] | .key, "\u0000", (.value | tostring), "\u0000"')
  elif [ "$GW_ENV_VARS_TYPE" = "string" ] && [ -n "$GW_ENV_VARS_RAW" ]; then
    # Preferred for complex values: JSON object string in one line.
    if printf '%s' "$GW_ENV_VARS_RAW" | jq -e 'type == "object"' >/dev/null 2>&1; then
      log_info "Setting gateway environment variables from JSON string config..."
      while IFS= read -r -d '' key && IFS= read -r -d '' value; do
        try_export_gateway_env_var "$key" "$value"
      done < <(printf '%s' "$GW_ENV_VARS_RAW" | jq -j 'to_entries[] | .key, "\u0000", (.value | tostring), "\u0000"')
    else
      # Supported simple format: KEY=VALUE pairs separated by ';' or newlines.
      log_info "Setting gateway environment variables from KEY=VALUE string config..."
      while IFS= read -r entry; do
        entry="${entry%$'\r'}"
        trimmed="$(printf '%s' "$entry" | sed -E 's/^[[:space:]]+//;s/[[:space:]]+$//')"

        # Skip empty lines and comments.
        if [ -z "$trimmed" ] || [[ "$trimmed" == \#* ]]; then
          continue
        fi

        if [[ "$trimmed" != *"="* ]]; then
          log_warn "Invalid gateway_env_vars entry '$trimmed' (expected KEY=VALUE, skip)"
          continue
        fi

        key="${trimmed%%=*}"
        value="${trimmed#*=}"
        key="$(printf '%s' "$key" | sed -E 's/^[[:space:]]+//;s/[[:space:]]+$//')"

        try_export_gateway_env_var "$key" "$value"
      done < <(printf '%s' "$GW_ENV_VARS_RAW" | tr ';' '\n')
    fi
  fi

  if [ $env_count -gt 0 ]; then
    log_info "Successfully exported $env_count gateway environment variable(s)"
  fi
elif [ "$GW_ENV_VARS_TYPE" != "null" ]; then
  log_warn "Invalid gateway_env_vars format in add-on options (expected list, string or object), skipping"
fi

# ------------------------------------------------------------------------------
# Persist Linuxbrew/Homebrew across Docker image rebuilds
# Homebrew installs to /home/linuxbrew/.linuxbrew/ which is ephemeral.
# We sync it to /config/.linuxbrew and symlink back so brew-installed CLI
# tools (gog, gh, bw, etc.) survive add-on updates.
# ------------------------------------------------------------------------------
IMAGE_BREW_DIR="/home/linuxbrew/.linuxbrew"
PERSISTENT_BREW_DIR="/config/.linuxbrew"

if [ -d "$IMAGE_BREW_DIR" ] && [ ! -L "$IMAGE_BREW_DIR" ]; then
  # Image has a real Homebrew install — sync to persistent storage
  if [ -d "$PERSISTENT_BREW_DIR" ]; then
    # Persistent copy exists: sync new/updated files from image (upgrades),
    # but preserve user-installed packages already in persistent storage.
    if command -v rsync >/dev/null 2>&1; then
      rsync -a --update "$IMAGE_BREW_DIR/" "$PERSISTENT_BREW_DIR/" 2>/dev/null || true
    else
      cp -ru "$IMAGE_BREW_DIR/"* "$PERSISTENT_BREW_DIR/" 2>/dev/null || true
    fi
    log_info "Synced Homebrew updates to persistent storage"
  else
    # First time: copy entire Homebrew install to persistent storage
    cp -a "$IMAGE_BREW_DIR" "$PERSISTENT_BREW_DIR" 2>/dev/null || true
    log_info "Copied Homebrew to persistent storage at $PERSISTENT_BREW_DIR"
  fi
  # Replace image dir with symlink to persistent copy
  rm -rf "$IMAGE_BREW_DIR"
  ln -sf "$PERSISTENT_BREW_DIR" "$IMAGE_BREW_DIR"
elif [ -L "$IMAGE_BREW_DIR" ]; then
  log_info "Homebrew already linked to persistent storage"
elif [ -d "$PERSISTENT_BREW_DIR" ]; then
  # Image doesn't have Homebrew (failed install?) but persistent copy exists
  mkdir -p "$(dirname "$IMAGE_BREW_DIR")"
  ln -sf "$PERSISTENT_BREW_DIR" "$IMAGE_BREW_DIR"
  log_info "Restored Homebrew symlink from persistent storage"
else
  log_info "Homebrew not available (install may have failed during image build)"
fi

# Back-compat: some docs/scripts assume /data; point it at /config.
if [ ! -e /data ]; then
  ln -s /config /data || true
fi

# Ensure the agents base directory exists so cleanup scans work even before first run.
# Do NOT pre-create agent-specific directories; Hermes creates them as needed.
mkdir -p /config/.hermes/agents || true

# ------------------------------------------------------------------------------
# SINGLE-INSTANCE GUARD (prevents multiple gateway runs racing each other)
# ------------------------------------------------------------------------------
STARTUP_LOCK="/config/.hermes/gateway.start.lock"
exec 9>"$STARTUP_LOCK"
if ! flock -n 9; then
  log_error "Another instance appears to be running (could not acquire $STARTUP_LOCK)."
  echo "If this is wrong, check for stuck processes or remove the lock file."
  exit 1
fi

# ------------------------------------------------------------------------------
# Session lock cleanup helpers
# ------------------------------------------------------------------------------

gateway_running() {
  if command -v ss >/dev/null 2>&1 && ss -tlnp 2>/dev/null | grep -q ":${GATEWAY_INTERNAL_PORT} "; then
    return 0
  fi
  local pid_file="${HERMES_HOME:-/config/.hermes}/gateway.pid"
  if [ -f "$pid_file" ]; then
    local gpid
    gpid="$(tr -d ' \r\n' < "$pid_file" 2>/dev/null || true)"
    if [ -n "$gpid" ] && kill -0 "$gpid" 2>/dev/null; then
      return 0
    fi
  fi
  pgrep -f '[h]ermes.*gateway' >/dev/null 2>&1
}

cleanup_session_locks() {
  local agents_dir="/config/.hermes/agents"
  local total_locks=0
  local cleaned_dirs=()

  # Scan all agent session directories, not just 'main'.
  # This is needed for users who have gateway.forcedAgentId set to a non-default agent.
  shopt -s nullglob
  local all_locks=()
  for agent_sessions_dir in "${agents_dir}"/*/sessions; do
    local agent_locks=( "${agent_sessions_dir}"/*.jsonl.lock )
    if [ ${#agent_locks[@]} -gt 0 ]; then
      all_locks+=( "${agent_locks[@]}" )
      cleaned_dirs+=( "$agent_sessions_dir" )
      total_locks=$(( total_locks + ${#agent_locks[@]} ))
    fi
  done
  shopt -u nullglob

  if [ "$total_locks" -eq 0 ]; then
    return 0
  fi

  # If gateway is running, do NOT remove locks automatically (could be real).
  if gateway_running; then
    log_info "Gateway appears to be running; leaving session lock files untouched."
    log_info "Locks present: $total_locks"
    return 0
  fi

  log_info "Removing stale session lock files ($total_locks) across agents: ${cleaned_dirs[*]}"
  for agent_sessions_dir in "${cleaned_dirs[@]}"; do
    rm -f "${agent_sessions_dir}"/*.jsonl.lock || true
  done
}

if [ "$CLEAN_LOCKS_ON_START" = "true" ]; then
  cleanup_session_locks
else
  log_info "clean_session_locks_on_start=false; skipping session lock cleanup."
fi

# ------------------------------------------------------------------------------
# Store tokens / export env vars (optional)
# ------------------------------------------------------------------------------

if [ -n "$HA_TOKEN" ]; then
  umask 077
  printf '%s' "$HA_TOKEN" > /config/secrets/homeassistant.token
fi


# ------------------------------------------------------------------------------
# Hermes config is managed by Hermes itself (onboarding / configure).
# This add-on intentionally does NOT create/patch /config/.hermes/hermes.json.
# ------------------------------------------------------------------------------

# Convenience info for later (router SSH access path & HA token file)
cat > /config/CONNECTION_NOTES.txt <<EOF
Home Assistant token (if set): /config/secrets/homeassistant.token
Router SSH (generic):
  host=${ROUTER_HOST}
  user=${ROUTER_USER}
  key=${ROUTER_KEY}
EOF


# ------------------------------------------------------------------------------
# Graceful shutdown handling (PID 1 trap) to reduce stale locks
# ------------------------------------------------------------------------------
GW_PID=""
DASHBOARD_PID=""
GW_RELAY_PID=""
NGINX_PID=""
TTYD_PID=""
STATUS_EXPORTER_PID=""
CDP_CHROMIUM_PID=""
SHUTTING_DOWN="false"

shutdown() {
  SHUTTING_DOWN="true"
  echo "Shutdown requested; stopping services..."

  if [ -n "${NGINX_PID}" ] && kill -0 "${NGINX_PID}" >/dev/null 2>&1; then
    kill -TERM "${NGINX_PID}" >/dev/null 2>&1 || true
    wait "${NGINX_PID}" || true
  fi

  if [ -n "${TTYD_PID}" ] && kill -0 "${TTYD_PID}" >/dev/null 2>&1; then
    kill -TERM "${TTYD_PID}" >/dev/null 2>&1 || true
    wait "${TTYD_PID}" || true
  fi

  if [ -n "${DASHBOARD_PID}" ] && kill -0 "${DASHBOARD_PID}" >/dev/null 2>&1; then
    kill -TERM "${DASHBOARD_PID}" >/dev/null 2>&1 || true
    wait "${DASHBOARD_PID}" 2>/dev/null || true
  fi

  if [ -n "${GW_PID}" ] && kill -0 "${GW_PID}" >/dev/null 2>&1; then
    kill -TERM "${GW_PID}" >/dev/null 2>&1 || true
    # wait reaps child PIDs; for non-child (re-tracked) PIDs it fails instantly,
    # so fall back to a timed kill -0 poll to let the gateway finish cleanly.
    if ! wait "${GW_PID}" 2>/dev/null; then
      for _i in 1 2 3 4 5; do
        kill -0 "${GW_PID}" 2>/dev/null || break
        sleep 1
      done
    fi
  fi

  stop_gw_relay

  if [ -n "${CDP_CHROMIUM_PID}" ] && kill -0 "${CDP_CHROMIUM_PID}" >/dev/null 2>&1; then
    kill -TERM "${CDP_CHROMIUM_PID}" >/dev/null 2>&1 || true
    wait "${CDP_CHROMIUM_PID}" || true
  fi

  if [ -n "${STATUS_EXPORTER_PID}" ] && kill -0 "${STATUS_EXPORTER_PID}" >/dev/null 2>&1; then
    kill -TERM "${STATUS_EXPORTER_PID}" >/dev/null 2>&1 || true
    wait "${STATUS_EXPORTER_PID}" || true
  fi

  if [ "$CLEAN_LOCKS_ON_EXIT" = "true" ]; then
    cleanup_session_locks || true
  fi
}

trap shutdown INT TERM

if ! require_hermes_cli; then
  exit 1
fi

# Verify/install dependencies for user-selected optional tool groups.
bootstrap_selected_tools

# Bootstrap minimal Hermes config ONLY if missing.
# We do not overwrite or patch existing configs; onboarding owns everything else.
HERMES_CONFIG_PATH="/config/.hermes/hermes.json"
if [ ! -f "$HERMES_CONFIG_PATH" ]; then
  log_info "Hermes config missing; bootstrapping minimal config at $HERMES_CONFIG_PATH"
  python3 - <<'PY'
import json
import secrets
from pathlib import Path

cfg_path = Path('/config/.hermes/hermes.json')
cfg_path.parent.mkdir(parents=True, exist_ok=True)

cfg = {
  "gateway": {
    "mode": "local",
    "port": 18789,
    "bind": "loopback",
    "auth": {
      "mode": "token",
      "token": secrets.token_urlsafe(24)
    }
  },
  "agents": {
    "defaults": {
      "workspace": "/config/hermesd"
    }
  }
}

cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding='utf-8')
print("INFO: Wrote minimal Hermes config (gateway.mode=local, auth.token generated)")
PY
fi

# Ensure Skills Hub directory is initialized when enabled.
initialize_skills_hub_if_enabled

# ------------------------------------------------------------------------------
# Apply gateway LAN mode settings safely using helper script
# This updates gateway.bind and gateway.port without touching other settings
# ------------------------------------------------------------------------------
export HERMES_CONFIG_PATH="/config/.hermes/hermes.json"

# Sync add-on API keys into /config/.hermes/.env so hermes onboard/model/setup
# can detect authenticated providers (same persistence model as MCP token sync).
sync_addon_api_keys_to_hermes_env() {
  if [ ! -f "$HELPER_PATH" ]; then
    log_warn "hermes_config_helper.py not found; cannot sync add-on API keys to Hermes .env"
    return 0
  fi

  local sync_json
  sync_json=$(jq -n \
    --arg openai "$OPENAI_API_KEY_OPT" \
    --arg openrouter "$OPENROUTER_API_KEY_OPT" \
    --arg anthropic "$ANTHROPIC_API_KEY_OPT" \
    --arg google "$GOOGLE_API_KEY_OPT" \
    --arg ollama "$OLLAMA_API_KEY_OPT" \
    --arg minimax "$MINIMAX_API_KEY_OPT" \
    --arg discord "$DISCORD_BOT_TOKEN_OPT" \
    --arg github "$GITHUB_TOKEN_OPT" \
    --arg xai "$XAI_API_KEY_OPT" \
    --arg firecrawl "$FIRECRAWL_API_KEY_OPT" \
    --arg searxng "$SEARXNG_URL_OPT" \
    '{
      OPENAI_API_KEY: $openai,
      OPENROUTER_API_KEY: $openrouter,
      ANTHROPIC_API_KEY: $anthropic,
      GOOGLE_API_KEY: $google,
      OLLAMA_API_KEY: $ollama,
      MINIMAX_API_KEY: $minimax,
      DISCORD_BOT_TOKEN: $discord,
      GITHUB_TOKEN: $github,
      XAI_API_KEY: $xai,
      FIRECRAWL_API_KEY: $firecrawl,
      SEARXNG_URL: $searxng
    }')

  if ! python3 "$HELPER_PATH" sync-addon-api-keys "$sync_json"; then
    log_warn "Failed to sync add-on API keys into /config/.hermes/.env"
  fi
}

sync_addon_api_keys_to_hermes_env

sync_router_ssh_env_to_hermes() {
  if [ ! -f "$HELPER_PATH" ]; then
    return 0
  fi
  if ! python3 "$HELPER_PATH" sync-router-ssh-env "$ROUTER_HOST" "$ROUTER_USER" "$ROUTER_KEY"; then
    log_warn "Failed to sync router SSH env into /config/.hermes/.env"
  fi
}

sync_router_ssh_env_to_hermes

bootstrap_hermes_first_run() {
  if [ ! -f "$HELPER_PATH" ]; then
    log_warn "hermes_config_helper.py not found; cannot bootstrap Hermes first-run config"
    return 0
  fi

  local browser_enabled_json="false"
  if [ "$TOOL_BROWSER_ENABLED" = "true" ] || [ "$TOOL_BROWSER_ENABLED" = "1" ]; then
    browser_enabled_json="true"
  fi

  local bootstrap_json
  local mcp_configured_json="false"
  if [ -f "/config/.hermes/.mcp_ha_configured" ]; then
    mcp_configured_json="true"
  fi

  bootstrap_json=$(jq -n \
    --arg timezone "$TZNAME" \
    --arg default_provider "$DEFAULT_PROVIDER" \
    --arg default_model_preset "$DEFAULT_MODEL_PRESET" \
    --arg default_model "$DEFAULT_MODEL_OPT" \
    --arg ha_url "$EFFECTIVE_HASS_URL" \
    --arg ha_token "$HA_TOKEN" \
    --arg setup_profile "$SETUP_PROFILE" \
    --arg firecrawl "$FIRECRAWL_API_KEY_OPT" \
    --arg searxng "$SEARXNG_URL_OPT" \
    --arg bootstrap_auxiliary_title "$BOOTSTRAP_AUXILIARY_TITLE" \
    --arg enable_openai_api "$ENABLE_OPENAI_API" \
    --arg mcp_configured "$mcp_configured_json" \
    --argjson browser_enabled "$browser_enabled_json" \
    --arg openai "$OPENAI_API_KEY_OPT" \
    --arg openrouter "$OPENROUTER_API_KEY_OPT" \
    --arg anthropic "$ANTHROPIC_API_KEY_OPT" \
    --arg google "$GOOGLE_API_KEY_OPT" \
    --arg ollama "$OLLAMA_API_KEY_OPT" \
    --arg minimax "$MINIMAX_API_KEY_OPT" \
    --arg xai "$XAI_API_KEY_OPT" \
    '{
      timezone: $timezone,
      default_provider: $default_provider,
      default_model_preset: $default_model_preset,
      default_model: $default_model,
      browser_enabled: $browser_enabled,
      bootstrap_auxiliary_title: $bootstrap_auxiliary_title,
      enable_openai_api: $enable_openai_api,
      mcp_configured: $mcp_configured,
      homeassistant_url: $ha_url,
      homeassistant_token: $ha_token,
      setup_profile: $setup_profile,
      firecrawl_api_key: $firecrawl,
      searxng_url: $searxng,
      api_keys: {
        OPENROUTER_API_KEY: $openrouter,
        ANTHROPIC_API_KEY: $anthropic,
        OPENAI_API_KEY: $openai,
        GOOGLE_API_KEY: $google,
        OLLAMA_API_KEY: $ollama,
        MINIMAX_API_KEY: $minimax,
        XAI_API_KEY: $xai
      }
    }')

  if ! python3 "$HELPER_PATH" bootstrap-first-run "$bootstrap_json"; then
    log_warn "Failed to bootstrap Hermes first-run config (model/browser/timezone/HA env)"
  fi
}

bootstrap_hermes_first_run

if [ -f "$HERMES_CONFIG_PATH" ]; then
  if [ -f "$HELPER_PATH" ]; then
    if python3 "$HELPER_PATH" repair-known-invalid-settings; then
      :
    else
      rc=$?
      log_error "Failed to repair known invalid Hermes config settings via hermes_config_helper.py (exit code ${rc})."
      log_error "Gateway configuration may be invalid; aborting startup."
      exit "${rc}"
    fi

    # In lan_https mode the gateway uses an internal port; nginx owns the external one.
    EFFECTIVE_GW_PORT="$GATEWAY_INTERNAL_PORT"
    if python3 "$HELPER_PATH" apply-gateway-settings "$GATEWAY_MODE" "$GATEWAY_REMOTE_URL" "$GATEWAY_BIND_MODE" "$EFFECTIVE_GW_PORT" "$ENABLE_OPENAI_API" "$GATEWAY_AUTH_MODE" "$GATEWAY_TRUSTED_PROXIES"; then
      :
    else
      rc=$?
      log_error "Failed to apply gateway settings via hermes_config_helper.py (exit code ${rc})."
      log_error "Gateway configuration may be incorrect; aborting startup."
      exit "${rc}"
    fi

    if ! python3 "$HELPER_PATH" sync-api-server-env "$ENABLE_OPENAI_API" "$API_SERVER_PORT"; then
      log_warn "Failed to sync Assist API server env (API_SERVER_*)."
    fi
  else
    log_warn "hermes_config_helper.py not found, cannot apply gateway settings"
    log_info "Ensure the add-on image includes hermes_config_helper.py and restart"
  fi
elif [ -f "$HELPER_PATH" ]; then
  if ! python3 "$HELPER_PATH" sync-api-server-env "$ENABLE_OPENAI_API" "$API_SERVER_PORT"; then
    log_warn "Failed to sync Assist API server env (API_SERVER_*)."
  fi
else
  log_warn "Hermes config not found at $HERMES_CONFIG_PATH, cannot apply gateway settings"
  log_info "Run 'hermes onboard' first, then restart the add-on"
fi

if [ "$GATEWAY_AUTH_MODE" = "trusted-proxy" ]; then
  log_info "gateway_auth_mode=trusted-proxy is enabled."
  log_info "Direct local CLI calls to the gateway may return unauthorized (trusted_proxy_user_missing) unless identity headers are injected by your reverse proxy."
  log_info "For local terminal CLI workflows, temporarily switch to token auth or use commands that don't require direct gateway WS auth."
fi

# ------------------------------------------------------------------------------
# TLS certificate generation for built-in HTTPS proxy (lan_https mode)
# Generates a local CA + server cert so phones/tablets get proper HTTPS.
# The CA cert can be installed once on a device for trusted access.
# ------------------------------------------------------------------------------
LAN_IP=""
if [ "$ENABLE_HTTPS_PROXY" = "true" ]; then
  CERT_DIR="/config/certs"
  mkdir -p "$CERT_DIR"

  # Detect primary LAN IP
  LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  if [ "$LOG_GATEWAY_URL_HINT" = "true" ] && [ -z "$GW_PUBLIC_URL" ] && [ -n "$LAN_IP" ]; then
    log_info "Gateway LAN URL hint (set gateway_public_url if needed): https://${LAN_IP}:${GATEWAY_PORT}/"
  fi
  STORED_IP=$(cat "$CERT_DIR/.cert_ip" 2>/dev/null || echo "")

  # --- Local CA (generated once, persists across restarts) ---
  if [ ! -f "$CERT_DIR/ca.key" ] || [ ! -f "$CERT_DIR/ca.crt" ]; then
    log_info "Generating local CA certificate (one-time)..."
    openssl genrsa -out "$CERT_DIR/ca.key" 2048 2>/dev/null
    openssl req -new -x509 -key "$CERT_DIR/ca.key" -out "$CERT_DIR/ca.crt" \
      -days 3650 -nodes -subj "/CN=Hermes Local CA" 2>/dev/null
    chmod 600 "$CERT_DIR/ca.key"
    STORED_IP=""  # force server cert regeneration
    log_info "Local CA created at $CERT_DIR/ca.crt"
  fi

  # --- Extra SANs from gateway_additional_allowed_origins + gateway_public_url ---
  EXTRA_SANS=""
  EXTRA_SAN_SOURCES="${GATEWAY_ADDITIONAL_ALLOWED_ORIGINS},${GW_PUBLIC_URL}"
  if [ "$EXTRA_SAN_SOURCES" != "," ]; then
    EXTRA_SANS="$(python3 - "$EXTRA_SAN_SOURCES" "${LAN_IP:-}" <<'PY'
import sys, re
from urllib.parse import urlparse
raw = sys.argv[1] if len(sys.argv) > 1 else ""
lan_ip = sys.argv[2] if len(sys.argv) > 2 else ""
entries = [e.strip() for e in raw.split(",") if e.strip()]
sans = []
seen = {"127.0.0.1", "localhost", "homeassistant", "homeassistant.local"}
if lan_ip:
    seen.add(lan_ip)
for entry in entries:
    if "://" not in entry:
        entry = "https://" + entry
    host = urlparse(entry).hostname or ""
    if host and host not in seen:
        seen.add(host)
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", host):
            sans.append(f"IP:{host}")
        else:
            sans.append(f"DNS:{host}")
print(",".join(sans), end="")
PY
)"
  fi
  STORED_EXTRA_SANS=$(cat "$CERT_DIR/.cert_extra_sans" 2>/dev/null || echo "")

  # --- Server cert (regenerated when LAN IP or SANs change) ---
  if [ ! -f "$CERT_DIR/gateway.crt" ] || [ ! -f "$CERT_DIR/gateway.key" ] || [ "$LAN_IP" != "$STORED_IP" ] || [ "$EXTRA_SANS" != "$STORED_EXTRA_SANS" ]; then
    log_info "Generating server TLS certificate for IP: ${LAN_IP:-unknown}..."
    openssl genrsa -out "$CERT_DIR/gateway.key" 2048 2>/dev/null
    openssl req -new -key "$CERT_DIR/gateway.key" -out "$CERT_DIR/gateway.csr" \
      -subj "/CN=Hermes Gateway" 2>/dev/null

    # SAN extension — include LAN IP, loopback, common mDNS names + user extras
    cat > "$CERT_DIR/_san.ext" <<SANEOF
subjectAltName=IP:${LAN_IP:-127.0.0.1},IP:127.0.0.1,DNS:localhost,DNS:homeassistant,DNS:homeassistant.local${EXTRA_SANS:+,${EXTRA_SANS}}
SANEOF

    openssl x509 -req -in "$CERT_DIR/gateway.csr" \
      -CA "$CERT_DIR/ca.crt" -CAkey "$CERT_DIR/ca.key" -CAcreateserial \
      -out "$CERT_DIR/gateway.crt" -days 3650 \
      -extfile "$CERT_DIR/_san.ext" 2>/dev/null

    rm -f "$CERT_DIR/gateway.csr" "$CERT_DIR/_san.ext" "$CERT_DIR/ca.srl"
    chmod 600 "$CERT_DIR/gateway.key"
    printf '%s' "$LAN_IP" > "$CERT_DIR/.cert_ip"
    printf '%s' "$EXTRA_SANS" > "$CERT_DIR/.cert_extra_sans"
    log_info "Server TLS certificate generated (SAN: IP:${LAN_IP:-127.0.0.1}${EXTRA_SANS:+,${EXTRA_SANS}})"
  else
    log_info "Reusing existing TLS certificate (IP: $STORED_IP)"
  fi

  # Make CA cert available for download via nginx
  mkdir -p /etc/nginx/html
  cp "$CERT_DIR/ca.crt" /etc/nginx/html/hermes-ca.crt 2>/dev/null || true
  log_info "CA certificate available for download at /cert/ca.crt on the HTTPS port"

fi

# ------------------------------------------------------------------
# Configure gateway.controlUi.allowedOrigins:
# - In lan_https: include HTTPS proxy defaults (LAN IP + common hostnames)
# - In all modes: also include origin from gateway_public_url when present
# - Helper merges with existing origins + user extras and deduplicates
# ------------------------------------------------------------------
if [ -f "$HELPER_PATH" ] && [ -f "$HERMES_CONFIG_PATH" ]; then
  ALLOWED_ORIGINS=""

  if [ "$ENABLE_HTTPS_PROXY" = "true" ] && [ -n "$LAN_IP" ]; then
    ALLOWED_ORIGINS="https://${LAN_IP}:${GATEWAY_PORT}"
    ALLOWED_ORIGINS="${ALLOWED_ORIGINS},https://homeassistant.local:${GATEWAY_PORT}"
    ALLOWED_ORIGINS="${ALLOWED_ORIGINS},https://homeassistant:${GATEWAY_PORT}"
  fi

  if [ -n "$GW_PUBLIC_URL" ]; then
    GW_PUBLIC_ORIGIN="$(python3 - "$GW_PUBLIC_URL" <<'PY'
import sys
from urllib.parse import urlparse
u = (sys.argv[1] or '').strip()
p = urlparse(u)
if p.scheme in ('http', 'https') and p.netloc:
    print(f"{p.scheme}://{p.netloc}", end='')
PY
)"
    if [ -n "$GW_PUBLIC_ORIGIN" ]; then
      if [ -n "$ALLOWED_ORIGINS" ]; then
        ALLOWED_ORIGINS="${ALLOWED_ORIGINS},${GW_PUBLIC_ORIGIN}"
      else
        ALLOWED_ORIGINS="$GW_PUBLIC_ORIGIN"
      fi
    fi
  fi

  python3 "$HELPER_PATH" set-control-ui-origins "$ALLOWED_ORIGINS" "$GATEWAY_ADDITIONAL_ALLOWED_ORIGINS" "$CONTROLUI_DISABLE_DEVICE_AUTH" || \
    log_warn "Could not set controlUi settings — gateway may reject the Control UI"
fi

# ------------------------------------------------------------------------------
# Proxy shim for undici/Hermes startup
# Keep official Hermes Agent npm release while enabling HTTP(S)_PROXY support.
# ------------------------------------------------------------------------------
HERMES_GLOBAL_NODE_MODULES="$(resolve_image_hermes_node_modules 2>/dev/null || HOME=/root NPM_CONFIG_PREFIX=/usr/local npm root -g 2>/dev/null || true)"
if [ -f /usr/local/lib/hermes-proxy-shim.cjs ]; then
  if [ -n "${NODE_OPTIONS:-}" ]; then
    export NODE_OPTIONS="--require /usr/local/lib/hermes-proxy-shim.cjs ${NODE_OPTIONS}"
  else
    export NODE_OPTIONS="--require /usr/local/lib/hermes-proxy-shim.cjs"
  fi
  export HERMES_GLOBAL_NODE_MODULES
fi

# ------------------------------------------------------------------------------
# Auto-configure MCP (Model Context Protocol) for Home Assistant
# Registers HA in Hermes built-in MCP config (mcp_servers in /config/.hermes/config.yaml).
# Requires: homeassistant_token set in add-on options.
# Re-runs when the token or resolved MCP URL changes; stores token in /config/.hermes/.env for ${HOMEASSISTANT_TOKEN}.
# On HAOS, MCP URL should be http://supervisor/core/api/mcp (not loopback) — reconciled every start.
# ------------------------------------------------------------------------------
if [ "$EFFECTIVE_AUTO_CONFIGURE_MCP" = "true" ] && [ -n "$HA_TOKEN" ]; then
  if [ -z "$MCP_HA_URL" ]; then
    MCP_HA_URL="${EFFECTIVE_HASS_URL%/}/api/mcp"
  fi
  MCP_FLAG="/config/.hermes/.mcp_ha_configured"
  MCP_TOKEN_HASH=$(printf '%s' "$HA_TOKEN" | sha256sum | cut -d' ' -f1)
  MCP_MARKER="${MCP_TOKEN_HASH}:${MCP_HA_URL}"

  if [ -f "$MCP_FLAG" ] && [ "$(tr -d '\r\n' < "$MCP_FLAG" 2>/dev/null || true)" = "$MCP_MARKER" ]; then
    log_info "MCP Home Assistant server already configured (${MCP_HA_URL})"
  elif [ -f "$HELPER_PATH" ]; then
    log_info "Configuring Home Assistant MCP in Hermes (mcp_servers) at $MCP_HA_URL ..."
    if python3 "$HELPER_PATH" configure-ha-mcp HA "$MCP_HA_URL" "$HA_TOKEN"; then
      printf '%s' "$MCP_MARKER" > "$MCP_FLAG"
      chmod 600 "$MCP_FLAG" 2>/dev/null || true
      log_info "MCP server 'HA' registered in /config/.hermes/config.yaml"
      log_info "Reload MCP in Gateway chat with /reload-mcp after first setup if tools are missing"
    else
      rc=$?
      log_warn "MCP auto-configuration failed (exit code ${rc}). Configure manually:"
      log_warn "  Add mcp_servers.HA in /config/.hermes/config.yaml, then run /reload-mcp"
    fi
  else
    log_warn "hermes_config_helper.py not found; cannot auto-configure MCP"
  fi
elif [ "$EFFECTIVE_AUTO_CONFIGURE_MCP" = "true" ] && [ -z "$HA_TOKEN" ]; then
  log_info "MCP auto-configure enabled but homeassistant_token not set — skipping"
  log_info "To auto-configure, set homeassistant_token in add-on Configuration, then restart"
fi

update_setup_readiness_markers() {
  if [ ! -f "$HELPER_PATH" ]; then
    return 0
  fi
  local mcp_ok="false"
  if [ -f "/config/.hermes/.mcp_ha_configured" ]; then
    mcp_ok="true"
  fi
  local markers_json
  markers_json=$(jq -n \
    --arg enable_openai_api "$ENABLE_OPENAI_API" \
    --arg mcp_configured "$mcp_ok" \
    --arg openai "$OPENAI_API_KEY_OPT" \
    --arg openrouter "$OPENROUTER_API_KEY_OPT" \
    --arg anthropic "$ANTHROPIC_API_KEY_OPT" \
    --arg google "$GOOGLE_API_KEY_OPT" \
    --arg minimax "$MINIMAX_API_KEY_OPT" \
    '{
      enable_openai_api: $enable_openai_api,
      mcp_configured: $mcp_configured,
      api_keys: {
        OPENROUTER_API_KEY: $openrouter,
        ANTHROPIC_API_KEY: $anthropic,
        OPENAI_API_KEY: $openai,
        GOOGLE_API_KEY: $google,
        MINIMAX_API_KEY: $minimax
      }
    }')
  python3 "$HELPER_PATH" update-readiness-markers "$markers_json" >/dev/null 2>&1 || true
}

update_setup_readiness_markers

build_mqtt_settings_json() {
  jq -n \
    --arg broker_host "$MQTT_BROKER_HOST" \
    --arg broker_port "$MQTT_BROKER_PORT" \
    --arg broker_username "$MQTT_BROKER_USER" \
    --arg broker_password "$MQTT_BROKER_PASSWORD" \
    '{
      broker_host: $broker_host,
      broker_port: (if ($broker_port | length) > 0 then $broker_port else "1883" end),
      broker_username: $broker_username,
      broker_password: $broker_password
    }'
}

log_resolved_mqtt_broker() {
  local settings_json resolved host port source
  settings_json="$(build_mqtt_settings_json)"
  resolved="$(python3 -c "
import json, sys
sys.path.insert(0, '/')
from hermes_mqtt_resolver import resolve_mqtt_broker
payload = {'mqtt_settings': json.loads(sys.argv[1])}
print(json.dumps(resolve_mqtt_broker(payload)))
" "$settings_json")"
  host="$(echo "$resolved" | jq -r '.host // empty')"
  port="$(echo "$resolved" | jq -r '.port // "1883"')"
  source="$(echo "$resolved" | jq -r '.source // "none"')"
  if [ -n "$host" ]; then
    log_ok "MQTT broker resolved (${source}): ${host}:${port}"
  else
    log_info "MQTT broker not configured yet (status exporter will autodetect Mosquitto each poll)"
  fi
}

build_status_exporter_payload() {
  local mqtt_settings_json
  mqtt_settings_json="$(build_mqtt_settings_json)"
  jq -n \
    --argjson mqtt_settings "$mqtt_settings_json" \
    --arg gateway_internal_port "$GATEWAY_INTERNAL_PORT" \
    --arg gateway_mode "$GATEWAY_MODE" \
    --arg access_mode "$ACCESS_MODE" \
    --arg setup_profile "$SETUP_PROFILE" \
    --arg enable_openai_api "$ENABLE_OPENAI_API" \
    --arg homeassistant_token "$HA_TOKEN" \
    --arg publish_mqtt_discovery "$PUBLISH_MQTT_DISCOVERY" \
    --arg mqtt_state_prefix "$MQTT_STATE_PREFIX_SAFE" \
    --argjson status_poll_interval_seconds "$STATUS_POLL_INTERVAL_SECONDS" \
    --arg openrouter "$OPENROUTER_API_KEY_OPT" \
    --arg anthropic "$ANTHROPIC_API_KEY_OPT" \
    --arg openai "$OPENAI_API_KEY_OPT" \
    --arg google "$GOOGLE_API_KEY_OPT" \
    --arg minimax "$MINIMAX_API_KEY_OPT" \
    --arg firecrawl "$FIRECRAWL_API_KEY_OPT" \
    --arg searxng "$SEARXNG_URL_OPT" \
    --arg enable_web_interface "$ENABLE_WEB_INTERFACE" \
    '{
      mqtt_settings: $mqtt_settings,
      gateway_internal_port: ($gateway_internal_port | tonumber),
      gateway_mode: $gateway_mode,
      access_mode: $access_mode,
      setup_profile: $setup_profile,
      enable_openai_api: $enable_openai_api,
      homeassistant_token: $homeassistant_token,
      publish_mqtt_discovery: $publish_mqtt_discovery,
      mqtt_state_prefix: $mqtt_state_prefix,
      status_poll_interval_seconds: $status_poll_interval_seconds,
      enable_web_interface: $enable_web_interface,
      api_keys: {
        OPENROUTER_API_KEY: $openrouter,
        ANTHROPIC_API_KEY: $anthropic,
        OPENAI_API_KEY: $openai,
        GOOGLE_API_KEY: $google,
        MINIMAX_API_KEY: $minimax,
        FIRECRAWL_API_KEY: $firecrawl,
        SEARXNG_URL: $searxng
      }
    }'
}

start_status_exporter() {
  if [ "$ENABLE_HA_STATUS_SENSORS" != "true" ] && [ "$ENABLE_HA_STATUS_SENSORS" != "1" ]; then
    log_info "HA status sensors disabled (enable_ha_status_sensors=false)"
    return 0
  fi
  if [ ! -f "$EXPORTER_PATH" ]; then
    log_warn "hermes_status_exporter.py not found; HA status sensors unavailable"
    return 0
  fi

  mkdir -p /share/hermes 2>/dev/null || true

  local payload
  payload="$(build_status_exporter_payload)"

  log_resolved_mqtt_broker
  log_info "Starting HA status exporter (interval=${STATUS_POLL_INTERVAL_SECONDS}s, mqtt_prefix=${MQTT_STATE_PREFIX_SAFE})"
  python3 "$EXPORTER_PATH" run-loop "$payload" &
  STATUS_EXPORTER_PID=$!
}

start_hermes_runtime() {
  echo "Starting Hermes Agent runtime (hermes gateway)..."
  export_gateway_tool_env
  ensure_default_hermes_profile
  start_cdp_chromium_if_enabled
  if [ "$GATEWAY_MODE" = "remote" ]; then
    # Remote mode: do NOT start a local gateway service.
    # Start a node/client host that connects to the configured remote gateway URL.
    # Use $GATEWAY_REMOTE_URL directly from add-on options — do NOT read back via
    # 'hermes config show' which may time out at startup or return redacted values.
    REMOTE_URL="$GATEWAY_REMOTE_URL"
    if [ -z "$REMOTE_URL" ]; then
      log_error "gateway_mode=remote but gateway_remote_url is not set in add-on options"
      log_error "Set gateway_remote_url in add-on Configuration (e.g. ws://192.168.1.10:18789), then restart"
      return 1
    fi

    NODE_HOST=""
    NODE_PORT=""
    NODE_TLS_FLAG=""
    if ! eval "$(python3 - "$REMOTE_URL" <<'PY'
import sys
from urllib.parse import urlparse
url = (sys.argv[1] or '').strip()
p = urlparse(url)
if p.scheme not in ('ws', 'wss') or not p.hostname:
    print('log_error "Invalid gateway.remote.url (expected ws:// or wss://): %s"' % url.replace('"', '\\"'))
    print('exit 1')
    raise SystemExit(0)
port = p.port or (443 if p.scheme == 'wss' else 80)
print(f'NODE_HOST={p.hostname}')
print(f'NODE_PORT={port}')
print(f'NODE_TLS_FLAG={"--tls" if p.scheme == "wss" else ""}')
PY
)"; then
      log_error "Failed to parse gateway.remote.url: $REMOTE_URL"
      return 1
    fi

    if ! hermes node run --help >/dev/null 2>&1; then
      log_error "gateway_mode=remote requires 'hermes node run', which is unavailable in the installed Hermes version."
      log_error "Upgrade via hermes_agent_version_preset or set gateway_mode=local."
      return 1
    fi
    log_info "gateway_mode=remote detected; starting node host to $NODE_HOST:$NODE_PORT ${NODE_TLS_FLAG}"
    # shellcheck disable=SC2086
    hermes node run --host "$NODE_HOST" --port "$NODE_PORT" $NODE_TLS_FLAG &
  else
    run_hermes_gateway
    GW_PID=$!
    if [ "$ENABLE_WEB_INTERFACE" = "true" ] || [ "$ENABLE_WEB_INTERFACE" = "1" ]; then
      if [ "$AUTO_START_WEB_INTERFACE" = "true" ] || [ "$AUTO_START_WEB_INTERFACE" = "1" ]; then
        run_hermes_dashboard || true
      else
        log_info "Web interface enabled but auto_start_with_integration=false; skipping hermes dashboard startup"
      fi
    else
      log_info "Gateway Web UI disabled (enable_web_interface=false)"
    fi
  fi
  if [ -z "${GW_PID:-}" ]; then
    GW_PID=$!
  fi
  return 0
}

# --- Loopback relay helpers for tailnet bind mode (issue #90) ---
# When gateway.bind=tailnet the gateway only listens on the Tailscale IP.
# The local CLI always tries ws://127.0.0.1:PORT and fails with
# "Gateway not running" even though the gateway is healthy.
# These functions start/stop a lightweight Node.js TCP relay on
# 127.0.0.1:PORT -> TAILSCALE_IP:PORT so terminal CLI commands work.
# IMPORTANT: stop_gw_relay must be called before restarting the gateway;
# otherwise the relay holds the loopback port and the new gateway instance
# detects it as "already listening" and exits with code 1.
start_gw_relay() {
  if [ "$GATEWAY_BIND_MODE" != "tailnet" ]; then
    return 0
  fi
  local ts_ip
  ts_ip=$(ip -4 addr show tailscale0 2>/dev/null \
    | awk '/inet /{gsub(/\/.*/,"",$2); print $2; exit}' || true)
  if [[ "${ts_ip:-}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    log_info "Starting loopback relay for tailnet gateway (127.0.0.1:${GATEWAY_PORT} -> ${ts_ip}:${GATEWAY_PORT})"
    node -e "
const net = require('net');
const TARGET_HOST = '${ts_ip}';
const TARGET_PORT = ${GATEWAY_PORT};
const server = net.createServer(function(c) {
  const t = net.createConnection(TARGET_PORT, TARGET_HOST);
  c.pipe(t); t.pipe(c);
  c.on('error', function() { t.destroy(); });
  t.on('error', function() { c.destroy(); });
});
server.listen(TARGET_PORT, '127.0.0.1');" &
    GW_RELAY_PID=$!
    log_info "Loopback relay started (PID ${GW_RELAY_PID})"
  else
    log_warn "tailnet bind mode active but Tailscale IP not found on tailscale0 interface."
    log_warn "Terminal CLI may show gateway as unreachable. Ensure Tailscale is running and restart."
  fi
}

stop_gw_relay() {
  if [ -n "${GW_RELAY_PID}" ] && kill -0 "${GW_RELAY_PID}" >/dev/null 2>&1; then
    kill -TERM "${GW_RELAY_PID}" >/dev/null 2>&1 || true
    wait "${GW_RELAY_PID}" 2>/dev/null || true
    GW_RELAY_PID=""
  fi
}

# Find a running gateway daemon's PID using multiple detection methods.
# Used by the supervisor loop to detect self-restarts without spawning duplicate
# gateway instances that collide on the port.
#
# Three tiers, tried in order of reliability:
#   1. Port ownership via `ss -tlnp` — authoritative once the daemon has bound.
#   2. `${HERMES_HOME}/gateway.pid` — written by `hermes gateway run`.
#   3. `pgrep` for the hermes gateway process.
#
# Returns the PID on stdout and exit 0, or exits with code 1 if nothing found.
find_gateway_daemon_pid() {
  local pid=""
  local pid_file="${HERMES_HOME:-/config/.hermes}/gateway.pid"

  # Tier 1: port ownership (authoritative once port is bound)
  pid=$(ss -tlnp 2>/dev/null \
    | grep ":${GATEWAY_INTERNAL_PORT} " \
    | sed -n 's/.*pid=\([0-9]*\).*/\1/p' \
    | head -1)
  [ -n "$pid" ] && { echo "$pid"; return 0; }

  # Tier 2: profile-scoped gateway.pid
  if [ -f "$pid_file" ]; then
    pid="$(tr -d ' \r\n' < "$pid_file" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      echo "$pid"
      return 0
    fi
  fi

  # Tier 3: hermes gateway process
  pid=$(pgrep -f '[h]ermes.*gateway' 2>/dev/null | head -1)
  [ -n "$pid" ] && { echo "$pid"; return 0; }

  return 1
}

if ! start_hermes_runtime; then
  exit 1
fi

if [ "$ENABLE_HTTPS_PROXY" = "true" ] && [ "$GATEWAY_MODE" != "remote" ] \
    && { [ "$ENABLE_WEB_INTERFACE" = "true" ] || [ "$ENABLE_WEB_INTERFACE" = "1" ]; } \
    && { [ "$AUTO_START_WEB_INTERFACE" = "true" ] || [ "$AUTO_START_WEB_INTERFACE" = "1" ]; }; then
  GATEWAY_BIND_OK=false
  for _gw_wait in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    if command -v ss >/dev/null 2>&1 && ss -tln 2>/dev/null | grep -q ":${GATEWAY_INTERNAL_PORT} "; then
      GATEWAY_BIND_OK=true
      break
    fi
    sleep 2
  done
  if [ "$GATEWAY_BIND_OK" = "true" ]; then
    log_info "Dashboard listening on 127.0.0.1:${GATEWAY_INTERNAL_PORT} (nginx HTTPS proxy on 0.0.0.0:${GATEWAY_PORT})"
    if [ "$ENABLE_OPENAI_API" = "true" ] || [ "$ENABLE_OPENAI_API" = "1" ]; then
      API_BIND_OK=false
      for _api_wait in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
        if command -v ss >/dev/null 2>&1 && ss -tln 2>/dev/null | grep -q ":${API_SERVER_PORT} "; then
          API_BIND_OK=true
          break
        fi
        sleep 2
      done
      if [ "$API_BIND_OK" = "true" ]; then
        log_info "Assist API server listening on 0.0.0.0:${API_SERVER_PORT} (Extended OpenAI from HA Core: http://<LAN-IP>:${API_SERVER_PORT}/v1)"
      else
        log_error "Assist API server did not bind port ${API_SERVER_PORT} within 30s."
        log_error "Set enable_openai_api=true, ensure gateway token exists, and restart."
        log_error "Probe: curl -sS http://127.0.0.1:${API_SERVER_PORT}/health"
      fi
    fi
  else
    log_error "Dashboard did not bind port ${GATEWAY_INTERNAL_PORT} within 30s."
    log_error "https://<LAN-IP>:${GATEWAY_PORT}/ will return 502 until the dashboard is healthy."
    log_error "Messaging gateway uses hermes gateway run (no HTTP listener); nginx proxies to hermes dashboard on ${GATEWAY_INTERNAL_PORT}."
    log_error "Run 'hermes dashboard --port ${GATEWAY_INTERNAL_PORT} --host 127.0.0.1 --no-open --skip-build' in the terminal for startup errors."
    log_error "If import fails with hermes_cli.dashboard_auth, update add-on to 0.0.11+ (wheel repair runs automatically) or set hermes_agent_version_preset to latest."
    log_error "If import fails otherwise, install Web UI deps: uv pip install --system 'fastapi' 'uvicorn[standard]' (or pip --break-system-packages)"
  fi
fi

start_gw_relay

install_hermes_terminal_profile() {
  cat > /config/.hermes-terminal.bashrc <<'EOF'
# Managed by Hermes Agent add-on — sources API keys for onboard/model/setup.
export HOME=/config
export HERMES_HOME=/config/.hermes
export HERMES_CONFIG_DIR=/config/.hermes
export HERMES_WORKSPACE_DIR=/config/hermesd
export XDG_CONFIG_HOME=/config
if [ -f /config/.hermes/.env ]; then
  set -a
  # shellcheck disable=SC1091
  . /config/.hermes/.env
  set +a
fi
EOF
  chmod 600 /config/.hermes-terminal.bashrc 2>/dev/null || true
}

# Start web terminal (optional)
TTYD_PID_FILE="/var/run/hermes-ttyd.pid"

# Clean up stale ttyd process from previous run using PID file
if [ -f "$TTYD_PID_FILE" ]; then
  OLD_PID=$(cat "$TTYD_PID_FILE" 2>/dev/null || echo "")
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "Stopping previous ttyd process (PID $OLD_PID)..."
    kill "$OLD_PID" 2>/dev/null || true
    sleep 1
    # Force kill if still running
    kill -9 "$OLD_PID" 2>/dev/null || true
  fi
  rm -f "$TTYD_PID_FILE"
fi

if [ "$ENABLE_TERMINAL" = "true" ] || [ "$ENABLE_TERMINAL" = "1" ]; then
  # Check if the terminal port is already in use before starting ttyd
  if command -v ss >/dev/null 2>&1 && ss -tlnp 2>/dev/null | grep -q ":${TERMINAL_PORT} "; then
    echo ""
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo "!!  WARNING: terminal_port ${TERMINAL_PORT} IS ALREADY IN USE  !!"
    echo "!!                                                             !!"
    echo "!!  The web terminal (ttyd) may FAIL to start because port     !!"
    echo "!!  ${TERMINAL_PORT} appears to be in use by another process.  !!"
    echo "!!                                                             !!"
    echo "!!  ACTION REQUIRED: If the terminal does not work, go to      !!"
    echo "!!  Add-on Configuration and change 'terminal_port' to a free  !!"
    echo "!!  port, then restart the add-on.                             !!"
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo ""
  fi
  # Source Hermes .env in terminal sessions so onboard/model/setup see add-on keys.
  install_hermes_terminal_profile

  echo "Starting web terminal (ttyd) on 127.0.0.1:${TERMINAL_PORT} ..."
  ttyd -W -i 127.0.0.1 -p "${TERMINAL_PORT}" -b /terminal bash --rcfile /config/.hermes-terminal.bashrc &
  TTYD_PID=$!
  echo "$TTYD_PID" > "$TTYD_PID_FILE"
  echo "ttyd started with PID $TTYD_PID"
else
  echo "Terminal disabled (enable_terminal=$ENABLE_TERMINAL)"
fi

# Start ingress reverse proxy (nginx). This provides the add-on UI inside HA.
# Token is injected server-side; never put it in the browser URL.
NGINX_PID_FILE="/var/run/hermes-nginx.pid"

# Clean up stale nginx process from previous run (e.g., after crash/unclean restart)
if [ -f "$NGINX_PID_FILE" ]; then
  OLD_NGINX_PID=$(cat "$NGINX_PID_FILE" 2>/dev/null || echo "")
  if [ -n "$OLD_NGINX_PID" ] && kill -0 "$OLD_NGINX_PID" 2>/dev/null; then
    echo "Stopping previous nginx process (PID $OLD_NGINX_PID)..."
    kill "$OLD_NGINX_PID" 2>/dev/null || true
    sleep 1
    kill -9 "$OLD_NGINX_PID" 2>/dev/null || true
  fi
  rm -f "$NGINX_PID_FILE"
fi
# Also kill any orphaned nginx workers that might hold port 48099
if command -v pkill >/dev/null 2>&1; then
  pkill -f "nginx.*-c /etc/nginx/nginx.conf" 2>/dev/null || true
  sleep 1
fi
# Verify port 48099 is actually free before proceeding
if command -v ss >/dev/null 2>&1 && ss -tlnp 2>/dev/null | grep -q ':48099 '; then
  log_warn "Port 48099 still in use after cleanup; nginx may fail to start"
fi

# ------------------------------------------------------------------------------
# render_landing: (re-)render the nginx config + landing page HTML.
#
# Called once before nginx starts (token may be empty on first boot/pre-onboard)
# and again in the background after the gateway comes up so a freshly-generated
# token is immediately reflected in the "Open Gateway Web UI" button.
# nginx is sent SIGHUP to reload the updated config without restarting.
# ------------------------------------------------------------------------------
render_landing() {
  local label="${1:-startup}"
  # Read gateway token directly from hermes.json (CLI may redact secrets)
  local token
  token="$(python3 -c "
import json, os
p = os.environ.get('HERMES_CONFIG_PATH', '/config/.hermes/hermes.json')
print(json.load(open(p)).get('gateway',{}).get('auth',{}).get('token',''), end='')
" 2>/dev/null || true)"

  local disk_total="" disk_used="" disk_avail="" disk_pct=""
  if df -h /config >/dev/null 2>&1; then
    disk_total=$(df -h /config | awk 'NR==2{print $2}')
    disk_used=$(df -h /config  | awk 'NR==2{print $3}')
    disk_avail=$(df -h /config | awk 'NR==2{print $4}')
    disk_pct=$(df -h /config   | awk 'NR==2{print $5}')
    if [ "$label" = "startup" ]; then
      log_info "Disk usage: ${disk_used}/${disk_total} (${disk_pct} used, ${disk_avail} free)"
      local pct_num=${disk_pct//%/}
      if [ "$pct_num" -ge 90 ] 2>/dev/null; then
        echo "WARNING: Disk is ${disk_pct} full! Add-on updates may fail. Run 'hermes-cleanup' in the terminal."
      elif [ "$pct_num" -ge 75 ] 2>/dev/null; then
        log_info "Disk is ${disk_pct} full. Consider running 'hermes-cleanup' in the terminal."
      fi
    fi
  fi

  local setup_api_key="no" setup_model="no" setup_mcp="no" setup_assist="no" gateway_url_hint=""
  [ -f "/config/.hermes/.bootstrap-api-key-ok" ] && setup_api_key="yes"
  [ -f "/config/.hermes/.bootstrap-model-ok" ] && setup_model="yes"
  [ -f "/config/.hermes/.mcp_ha_configured" ] && setup_mcp="yes"
  if [ "$ENABLE_OPENAI_API" = "true" ] || [ "$ENABLE_OPENAI_API" = "1" ]; then
    setup_assist="yes"
  fi
  if [ "$LOG_GATEWAY_URL_HINT" = "true" ] && [ -z "$GW_PUBLIC_URL" ] && [ -n "${LAN_IP:-}" ]; then
    gateway_url_hint="https://${LAN_IP}:${GATEWAY_PORT}/"
  fi

  GW_PUBLIC_URL="$GW_PUBLIC_URL" GW_TOKEN="$token" TERMINAL_PORT="$TERMINAL_PORT" \
    ENABLE_HTTPS_PROXY="$ENABLE_HTTPS_PROXY" HTTPS_PROXY_PORT="$GATEWAY_PORT" \
    GATEWAY_INTERNAL_PORT="$GATEWAY_INTERNAL_PORT" ACCESS_MODE="$ACCESS_MODE" \
    ENABLE_OPENAI_API="$ENABLE_OPENAI_API" API_SERVER_PORT="$API_SERVER_PORT" \
    DISK_TOTAL="$disk_total" DISK_USED="$disk_used" DISK_AVAIL="$disk_avail" DISK_PCT="$disk_pct" \
    NGINX_LOG_LEVEL="$NGINX_LOG_LEVEL" \
    ENABLE_WEB_INTERFACE="$ENABLE_WEB_INTERFACE" \
    AUTO_START_WEB_INTERFACE="$AUTO_START_WEB_INTERFACE" \
    SETUP_API_KEY="$setup_api_key" SETUP_MODEL="$setup_model" SETUP_MCP="$setup_mcp" \
    SETUP_ASSIST="$setup_assist" SETUP_GATEWAY_URL_HINT="$gateway_url_hint" \
    python3 /render_nginx.py

  if [ "$label" != "startup" ]; then
    # Signal nginx to reload config/landing HTML without dropping connections.
    local nginx_pid
    nginx_pid=$(cat "${NGINX_PID_FILE:-/var/run/hermes-nginx.pid}" 2>/dev/null || true)
    if [ -n "$nginx_pid" ] && kill -0 "$nginx_pid" 2>/dev/null; then
      kill -HUP "$nginx_pid" 2>/dev/null || true
      log_info "Landing page re-rendered with gateway token (nginx reloaded)."
    fi
  fi
}

# Initial render (token may be absent if hermes.json does not exist yet)
render_landing startup

echo "Starting ingress proxy (nginx) on :48099 ..."
nginx -g 'daemon off;' &
NGINX_PID=$!
sleep 1
if kill -0 "$NGINX_PID" 2>/dev/null; then
  echo "$NGINX_PID" > "$NGINX_PID_FILE"
  echo "nginx started with PID $NGINX_PID"
else
  log_warn "nginx failed to start (PID $NGINX_PID exited); ingress UI may be unavailable"
fi

start_status_exporter

# If the token was not available at startup (first boot / pre-onboard), schedule
# a background re-render so the "Open Gateway Web UI" button gets the real token
# once hermes onboard writes hermes.json (typically within 30-90 s).
(
  CONFIG_PATH="${HERMES_CONFIG_PATH:-/config/.hermes/hermes.json}"
  for _i in $(seq 1 24); do
    sleep 5
    token=$(python3 -c "
import json, os
p='$CONFIG_PATH'
try:
    print(json.load(open(p)).get('gateway',{}).get('auth',{}).get('token',''), end='')
except Exception:
    pass
" 2>/dev/null || true)
    if [ -n "$token" ]; then
      if [ "$ENABLE_OPENAI_API" = "true" ] || [ "$ENABLE_OPENAI_API" = "1" ]; then
        if [ -f "$HELPER_PATH" ]; then
          python3 "$HELPER_PATH" sync-api-server-env true "$API_SERVER_PORT" >/dev/null 2>&1 || true
          log_info "Gateway token available; Assist API env updated. Restart add-on if port ${API_SERVER_PORT} is not listening."
        fi
      fi
      render_landing post-onboard
      break
    fi
  done
) &

# Keep add-on alive even if gateway/node runtime restarts itself (e.g. during onboarding).
# If runtime exits unexpectedly, restart it while nginx/ttyd stay up.
#
# Design notes (issue #95):
#   `hermes gateway run --no-supervise` runs the Python gateway under add-on supervision.
#   When the gateway self-restarts, the old process may exit and a new one is forked —
#   the new PID is NOT always a child of this shell so `wait` cannot block on it.
#
#   The new daemon can take 20-30 seconds to initialise on low-power hardware
#   (Pi / eMMC). During that time port binding may not be visible yet, but
#   `${HERMES_HOME}/gateway.pid` and pgrep can still find the process.
#
#   Strategy:
#     1. `wait` for our child (the wrapper). After it exits, use
#        `find_gateway_daemon_pid` (port → pgrep → /proc scan) with retries
#        to find the daemon. If found → re-track and poll with `kill -0`.
#     2. When the re-tracked daemon eventually exits (crash or another restart),
#        `kill -0` fails, we check again for a live daemon to re-track.
#     3. Before any supervisor-initiated restart, do a final port-occupancy
#        guard to prevent launching a duplicate.
GW_IS_CHILD=true   # true only when GW_PID was started by us (can use `wait`)

while true; do
  if [ "$GW_IS_CHILD" = "true" ]; then
    # Efficient blocking wait on our child process.
    GW_EXIT_CODE=0
    wait "${GW_PID}" 2>/dev/null || GW_EXIT_CODE=$?
  else
    # GW_PID is NOT our child (re-tracked after a self-restart).
    # Poll with kill -0 until it exits.
    while kill -0 "$GW_PID" 2>/dev/null; do
      if [ "$SHUTTING_DOWN" = "true" ]; then break 2; fi
      sleep 5
    done
    GW_EXIT_CODE=0
  fi

  if [ "$SHUTTING_DOWN" = "true" ]; then
    break
  fi

  # --- Detect self-restart ---------------------------------------------------
  # Try up to 10 times (≈ 20 s) using all 3 tiers of find_gateway_daemon_pid.
  # Tier 3 (/proc scan) usually finds the daemon on the very first attempt
  # because the process exists immediately after fork, even before port bind
  # or process.title. The retries cover edge cases on extremely slow I/O.
  RESTARTED_PID=""
  if [ "$GATEWAY_MODE" != "remote" ]; then
    for _attempt in 1 2 3 4 5 6 7 8 9 10; do
      RESTARTED_PID=$(find_gateway_daemon_pid 2>/dev/null || true)
      [ -n "$RESTARTED_PID" ] && break
      sleep 2
    done
  else
    sleep 2
    RESTARTED_PID=$(pgrep -f '[h]ermes.*node.*run' 2>/dev/null | head -1 || true)
  fi

  if [ -n "$RESTARTED_PID" ]; then
    log_info "Hermes runtime active (PID $RESTARTED_PID); monitoring."
    GW_PID="$RESTARTED_PID"
    GW_IS_CHILD=false
    continue
  fi

  # --- Final port guard ------------------------------------------------------
  # Even if all detection methods missed the daemon during the loop above,
  # the port may now be bound (the daemon finished initialising while we slept).
  # Never launch a duplicate if the port is occupied.
  if [ "$GATEWAY_MODE" != "remote" ] && \
     ss -tlnp 2>/dev/null | grep -q ":${GATEWAY_INTERNAL_PORT} "; then
    PORT_PID=$(ss -tlnp 2>/dev/null \
      | grep ":${GATEWAY_INTERNAL_PORT} " \
      | sed -n 's/.*pid=\([0-9]*\).*/\1/p' \
      | head -1 || true)
    log_info "Gateway port ${GATEWAY_INTERNAL_PORT} occupied by PID ${PORT_PID:-unknown}; monitoring."
    GW_PID="${PORT_PID:-$GW_PID}"
    GW_IS_CHILD=false
    continue
  fi

  log_warn "Hermes runtime exited with code ${GW_EXIT_CODE}. Restarting in 2s..."
  sleep 2

  # Stop the loopback relay BEFORE restarting the gateway (tailnet mode only).
  # The relay holds 127.0.0.1:GATEWAY_PORT — leaving it up causes the new gateway
  # to detect the port as occupied and exit with code 1, re-entering the loop.
  stop_gw_relay

  if ! start_hermes_runtime; then
    log_error "Failed to restart Hermes runtime; retrying in 5s..."
    sleep 5
  else
    GW_IS_CHILD=true
    start_gw_relay
  fi
done
