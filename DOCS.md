# Hermes Agent Integration — Home Assistant Add-on

Canonical setup and operations guide. This add-on is marked **Experimental** in the Home Assistant add-on store — expect breaking changes between releases. Read [SECURITY.md](SECURITY.md) before enabling remote access.

## What you get

| Service | Port | Purpose |
|---------|------|---------|
| Hermes Gateway | 18789 (configurable) | Messaging gateway + Control UI |
| Hermes Dashboard | 9119 (configurable) | Admin web UI (`hermes dashboard`) — `lan_https` only; includes embedded Chat tab when `ptyprocess` is present |
| nginx (Ingress) | 48099 | Landing page + `/status.json` |
| ttyd (terminal) | 7681 (configurable) | Browser terminal |

Persistent data lives under `/config/` (`.hermes`, `hermesd`, `secrets`, `keys`, `.linuxbrew`, `.node_global`, etc.). System tools (`hermes`, `uv`, `mcp`) install to **`/usr/local`**; user npm skills from the dashboard go to **`/config/.node_global`**.

## Install

1. **Settings → Add-ons → Add-on store → Repositories**
2. Add `https://github.com/jackalski/HermesAgentHomeAssistant`
3. Install **Hermes Agent Integration** and start it.

Architectures: `amd64`, `aarch64`, `armv7`.

## Quick start (recommended)

**Settings → Add-ons → Hermes Agent Integration → Configuration:**

| Field | What to set |
|-------|-------------|
| `setup_profile` | `home_assistant` (default) |
| **Provider API Keys** → OpenRouter (or another provider) | Your API key |
| `homeassistant_token` | Long-lived HA token (for MCP) |
| `hass_url` | Leave **empty** on HAOS (autodetected) |

Restart. The add-on bootstraps model, browser, timezone, and MCP when a token is set.

Optional: `hermes onboard` in the terminal for OAuth or advanced tuning.

Gateway token:

```sh
jq -r '.gateway.auth.token' /config/.hermes/hermes.json
```

## Home Assistant autodetection

When `hass_url` is empty or a local placeholder (`localhost` / `127.0.0.1:8123`), the add-on resolves URLs at startup:

| Use | Autodetected URL (HAOS) |
|-----|-------------------------|
| MCP registration | `http://supervisor/core/api/mcp` |
| `HOMEASSISTANT_URL` in `.env` | `http://127.0.0.1:8123` (or internal `homeassistant` service host) |

Set `hass_url` only for non-standard setups (external URL, different port, remote HA).

When `homeassistant_token` is set, the add-on probes `${hass_url}/api/` and logs success or a warning.

## Access modes

Set `access_mode` in add-on configuration:

| Mode | Best for |
|------|----------|
| `lan_https` | **Default** — phones/tablets on LAN; built-in HTTPS proxy |
| `local_only` | Ingress + terminal only |
| `lan_reverse_proxy` | NPM, Caddy, Traefik (needs `X-Forwarded-User`) |
| `tailnet_https` | Tailscale |
| `custom` | Manual `gateway_bind_mode` / `gateway_auth_mode` |

Set `gateway_public_url` for the **Open Gateway Web UI** button (auto-filled from LAN IP in `lan_https` when empty).

### Cloudflare Tunnel (Cloudflared add-on)

**Recommended recipe** — keep `access_mode: lan_https` (token auth, no trusted-proxy headers):

1. Install the official **Cloudflared** add-on.
2. In Cloudflare Zero Trust, add a public hostname pointing to the Hermes HTTPS origin:

```yaml
ingress:
  - hostname: hermes.example.com
    service: https://127.0.0.1:18789
    originRequest:
      noTLSVerify: true
```

3. Set `gateway_public_url` to `https://hermes.example.com` and restart.

> Nabu Casa remote access only proxies port 8123 — use Cloudflared or your own tunnel for Hermes.

**Alternative** — `lan_reverse_proxy` only if your proxy sends `X-Forwarded-User` (e.g. NPM custom header). Add proxy CIDRs under **Gateway Trusted Proxies** (one IP/CIDR per row). If the list is empty, the add-on applies defaults (`127.0.0.1,172.30.0.0/16,10.0.0.0/8`) and logs a hint when Cloudflared is detected.

### External reverse proxy (NPM)

1. `access_mode`: `lan_reverse_proxy`
2. `gateway_trusted_proxies`: proxy source CIDR (e.g. `172.30.0.0/16`)
3. NPM: forward to `http://<HA-LAN-IP>:18789`, enable WebSockets, add header `X-Forwarded-User: hermes-agent`

## Home Assistant integration

### MCP (control HA from Hermes)

**Prerequisite:** enable Home Assistant’s **Model Context Protocol Server** integration (Settings → Devices & services → Add integration). Without it, `/api/mcp` returns 404 and Hermes shows `HA (http) — failed`.

1. Create a long-lived token in your HA profile.
2. Paste into `homeassistant_token`; enable `auto_configure_mcp` (or use `setup_profile: home_assistant` with token set).
3. Leave `hass_url` empty on HAOS (MCP URL becomes `http://supervisor/core/api/mcp`).
4. Restart. Logs should show `MCP server 'HA' registered` and `Home Assistant URL (supervisor): ... (MCP: http://supervisor/core/api/mcp)`.
5. In gateway chat: `/reload-mcp` if tools are missing.
6. In HA: open the MCP Server integration → expose entities you want Hermes to control.

### Status sensors

With `enable_ha_status_sensors` (default ON):

- **MQTT** entities when Mosquitto is installed (device: Hermes Agent Integration).
- **JSON API** at Ingress `/status.json` and `/share/hermes/status.json`.

Options: `publish_mqtt_discovery` (one-shot per add-on version — marker `/config/.hermes/.mqtt_discovery_published`), `status_poll_interval_seconds` (30–300), `mqtt_state_prefix`.

### Chat, voice, Assist

- Set **`enable_openai_api: true`** in add-on Configuration (syncs `API_SERVER_ENABLED=true` to `/config/.hermes/.env`).
- Install [Extended OpenAI Conversation](https://github.com/jekalmin/extended_openai_conversation) via HACS, or the [Hermes Agent integration](https://github.com/jackalski/HermesAgentHomeAssistantIntegration) for chat card and voice.
- **Extended OpenAI Conversation** settings:

| Field | Value |
|-------|-------|
| Base URL | `http://<LAN-IP>:8642/v1` (HTTP from HA Core — avoids self-signed HTTPS on 18789) |
| API Key | Gateway token: `jq -r '.gateway.auth.token' /config/.hermes/hermes.json` |
| Model | `hermes-agent` |
| Skip authentication | ON (optional; helps during setup) |

HTTPS on port 18789 still works for browsers and `curl -k`; HA Core rejects the self-signed cert, so use **8642** for Extended OpenAI.

- Restart add-on after enabling Assist API or after first `hermes onboard` (gateway reads `API_SERVER_*` at startup).
- In **Settings → Voice assistants**, set conversation agent to Extended OpenAI Conversation and expose entities.

## Configuration reference

Full schema: [`hermes_agent/config.yaml`](hermes_agent/config.yaml).

| Option | Default | Notes |
|--------|---------|-------|
| `setup_profile` | `home_assistant` | Preset for first-run behavior |
| `default_provider` | `openrouter` | `nous`, `openrouter`, `google`, `anthropic`, `ollama`, `minimax`, `xai`, `openai` |
| `default_model_preset` | `custom` | `custom` only — set model ID in `default_model` |
| `access_mode` | `lan_https` | See access modes above |
| `gateway_port` | `18789` | External HTTPS port in `lan_https` |
| `hass_url` | *(empty)* | Autodetect on HAOS |
| `homeassistant_token` | *(empty)* | Enables MCP + `.env` sync |
| `auto_configure_mcp` | `false` | Auto-on when profile + token set |
| `enable_openai_api` | `false` | Syncs `API_SERVER_ENABLED`; Assist API on **8642**, nginx `/v1/` on **18789** |
| `enable_ha_status_sensors` | `true` | MQTT + status.json |
| **Home Assistant** panel | — | `hass_url`, `homeassistant_token`, `auto_configure_mcp` |
| **Gateway Access** panel | `lan_https` | `access_mode`, `gateway_port`, trusted proxies, Assist API, etc. |
| **MQTT Status Sensors** panel | autodetect | `broker_host` / `broker_port` / `broker_username` / `broker_password`; leave host empty for Mosquitto autodetect |
| **Provider API Keys** panel | *(empty)* | Synced to `/config/.hermes/.env` (preserved on reinstall) |
| **Router SSH** panel | — | `host`, `user`, `key_path` (default `/config/keys/router_ssh`) |
| **Tool Bootstrap** panel | browser ON | Telegram / browser / Skills Hub auto-install toggles |
| **Hermes Dashboard** panel | ON / auto-start / 9119 | `enable_web_interface`, `auto_start_with_integration`, `dashboard_port` — runs the separate `hermes dashboard` admin UI; exposed over HTTPS on `dashboard_port` in `lan_https` (no built-in auth, binds loopback) |
| **Advanced Settings** panel | — | `http_proxy`, `nginx_log_level`, `gateway_env_vars`, Hermes version |
| `addon_log_level` | `info` | Add-on startup log verbosity |
| `force_ipv4_dns` | `true` | Recommended on HAOS |
| `nginx_log_level` | `minimal` | Suppresses HA polling noise |
| `hermes_agent_version_preset` | `custom` | `latest` or `custom` — reconciled on restart |
| `hermes_agent_version_custom` | `0.16.0` | npm tag/semver when preset is `custom` |

Provider keys live under **`provider_api_keys`** in the add-on UI (OpenAI, OpenRouter, Anthropic, Google, Ollama Cloud, MiniMax, Discord, GitHub, xAI, Firecrawl, SearXNG). **Nous Portal** uses OAuth in the terminal (`hermes setup --portal`); **Ollama** in `default_provider` maps to Hermes `ollama-cloud`.

**`enable_openai_api`** maps directly to Hermes **`API_SERVER_ENABLED`** in `/config/.hermes/.env` (with `API_SERVER_HOST`, `API_SERVER_PORT`, `API_SERVER_KEY`).

## Persistence

| Path | Contents |
|------|----------|
| `/config/.hermes/` | `hermes.json`, `config.yaml`, skills, `state.db` |
| `/config/hermesd/` | Workspace |
| `/config/secrets/` | `homeassistant.token` |
| `/config/keys/` | Router SSH private keys (default `router_ssh`) |
| `/config/secrets/mqtt.password` | Persisted MQTT broker password (when set in add-on config) |
| `/config/certs/` | TLS certs (`lan_https`) |

Hermes binary in the image is replaced on update; `/config/` data persists.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `HTTP 400: No models provided` | Set provider API key in add-on config; restart; verify model in `/config/.hermes/config.yaml` |
| OpenRouter HTTP 402 (insufficient credits) | Add credits at [openrouter.ai/settings/credits](https://openrouter.ai/settings/credits) or use a direct provider key (`google_api_key`, `anthropic_api_key`, …) |
| Owl Alpha / Stealth HTTP 400 | Upstream flake on free model; switch to `google/gemini-2.5-flash` via `hermes model` or add-on model preset |
| `no such gateway 'default'` in terminal | Use `hermes gateway run` (not `hermes-agent gateway run`); ensure `HOME=/config` and `HERMES_HOME=/config/.hermes` (ttyd sets this automatically) |
| Gateway unreachable on LAN | Check `access_mode`; install CA cert for `lan_https` (landing page download) |
| `502 Bad Gateway` on `https://<LAN-IP>:9119/` | In `lan_https`, nginx on **9119** (`dashboard_port`) proxies to **`hermes dashboard`** on **9120** — 502 means the dashboard is not listening; check `enable_web_interface`, the `hermes-agent[web]` extra, and the probe below |
| MCP tools missing | Set token, enable MCP, restart, run `/reload-mcp` |
| `HA (http) — failed` in MCP Servers | Add HA **Model Context Protocol Server** integration; verify token; leave `hass_url` empty on HAOS; run probe below |
| `trusted_proxy_user_missing` | Use token auth (`lan_https`) or configure proxy `X-Forwarded-User` |
| HA URL / MCP failures | Set explicit `hass_url`; check add-on log for autodetection line |
| Low disk | Run `hermes-cleanup` in terminal |
| `Method Not Allowed` on `/v1/chat/completions` | Fixed in **0.0.12+** — enable `enable_openai_api` and restart; use `http://<LAN-IP>:8642/v1` from HA Core (not HTTPS 18789) |
| `Connection error` in Extended OpenAI Conversation | HA Core rejects self-signed HTTPS on 18789 — use Base URL `http://<LAN-IP>:8642/v1` (fixed in **0.0.13+**; API binds `0.0.0.0:8642`, bearer token required) |
| MQTT status sensors missing / "MQTT broker not available" | Install and start **Mosquitto broker** add-on; fixed in **0.0.15+** (Supervisor API + retry). Check add-on log for `MQTT broker resolved` or `MQTT broker available for status sensors` |
| `ModuleNotFoundError: No module named 'hermes_cli.dashboard_auth'` | Add-on **0.0.11+** auto-patches missing wheel subpackages on startup; update to **0.0.14+** with Hermes **0.16.0** |
| `EEXIST: file already exists` at `/usr/local/bin/hermes` during npm reconcile | Fixed in 0.0.9+; update add-on. Harmless on 0.0.8 — startup continues with image-baked `hermes` |
| `externally-managed-environment` during `hermes-agent` npm install | Fixed in 0.0.8+; rebuild/update add-on. Image-baked `hermes` is used if reconcile fails. To stop retries: `echo 0.16.0 > /config/.hermes/.addon-managed-hermes-version` |
| `pip install not officially supported` banner in Hermes CLI | Fixed in **0.0.19+** — add-on stamps `/config/.hermes/.install_method` as `docker` on startup. Manual fix: `echo docker > /config/.hermes/.install_method` and restart |
| Mosquitto log spam (`New connection` / `disconnected` every minute) | Fixed in **0.0.19+** — persistent MQTT client + one-shot discovery. Optional: Mosquitto `connection_messages false` in customize |

Gateway token (if CLI redacts secrets):

```sh
jq -r '.gateway.auth.token' /config/.hermes/hermes.json
```

Gateway + dashboard upstream probe (`lan_https` — add-on terminal):

```sh
ss -tlnp | grep -E ':18789|:18790|:9119|:9120'
curl -sS -m 5 -o /dev/null -w "gateway HTTPS: HTTP %{http_code}\n" -k "https://127.0.0.1:18789/"
curl -sS -m 5 -o /dev/null -w "dashboard HTTPS: HTTP %{http_code}\n" -k "https://127.0.0.1:9119/"
curl -sS -m 5 -o /dev/null -w "dashboard loopback: HTTP %{http_code}\n" "http://127.0.0.1:9120/"
jq '{port:.gateway.port,bind:.gateway.bind,mode:.gateway.mode}' /config/.hermes/hermes.json
```

| Check | Healthy |
|-------|---------|
| `:18789` listener | nginx TLS proxy → gateway Control UI (external URL) |
| `:9119` listener | nginx TLS proxy → Hermes **dashboard** (`dashboard_port`) |
| `:9120` listener | Hermes **dashboard** loopback upstream (`hermes dashboard`) |
| Messaging gateway | `hermes gateway run` + `${HERMES_HOME}/gateway.pid` |
| Loopback curl to `:9120` | Not connection refused (200/302 from dashboard is fine) |

If **9120 is missing**: dashboard failed to start — read add-on log for `Starting Hermes dashboard` errors, or run:

```sh
export HOME=/config HERMES_HOME=/config/.hermes
hermes dashboard --port 9120 --host 127.0.0.1 --no-open
```

If import fails: `uv pip install --system 'fastapi' 'uvicorn[standard]' 'ptyprocess'` (or `python3 -m pip install --break-system-packages ...`). Confirm `gateway_mode` is `local` (not `remote`). The dashboard **Chat** tab also needs `ptyprocess` and Node (both bundled in the add-on image from **0.0.22+**).

MCP connectivity probe (add-on terminal):

```sh
TOKEN="$(grep -E '^HOMEASSISTANT_TOKEN=' /config/.hermes/.env | cut -d= -f2-)"
URL="$(python3 -c "import yaml; c=yaml.safe_load(open('/config/.hermes/config.yaml')); print(c.get('mcp_servers',{}).get('HA',{}).get('url',''))")"
curl -sS -m 10 -o /dev/null -w "HTTP %{http_code}\n" -H "Authorization: Bearer ${TOKEN}" "${URL}"
```

| HTTP code | Meaning |
|-----------|---------|
| `404` | MCP Server integration not installed in HA |
| `401` | Token invalid or expired — recreate long-lived token |
| `405` | Endpoint exists (normal for GET on streamable HTTP MCP) |
| `000` / timeout | Wrong `hass_url` or network — leave `hass_url` empty on HAOS, or set `http://homeassistant:8123` |

## Example automations

Gateway offline:

```yaml
automation:
  - alias: Hermes gateway offline
    trigger:
      - platform: state
        entity_id: binary_sensor.hermes_gateway_running
        to: "off"
    action:
      - service: notify.notify
        data:
          message: "Hermes gateway unreachable"
```

## Links

- Repo: https://github.com/jackalski/HermesAgentHomeAssistant
- Integration: https://github.com/jackalski/HermesAgentHomeAssistantIntegration
- Changelog: [`hermes_agent/CHANGELOG.md`](hermes_agent/CHANGELOG.md)
