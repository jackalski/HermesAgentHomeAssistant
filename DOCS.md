# Hermes Agent — Home Assistant Add-on

Canonical setup and operations guide. This add-on is marked **Experimental** in the Home Assistant add-on store — expect breaking changes between releases. Read [SECURITY.md](SECURITY.md) before enabling remote access.

## What you get

| Service | Port | Purpose |
|---------|------|---------|
| Hermes Gateway | 18789 (configurable) | AI agent server |
| nginx (Ingress) | 48099 | Landing page + `/status.json` |
| ttyd (terminal) | 7681 (configurable) | Browser terminal |

Persistent data lives under `/config/` (`.hermes`, `hermesd`, `secrets`, `keys`, `.linuxbrew`, etc.).

## Install

1. **Settings → Add-ons → Add-on store → Repositories**
2. Add `https://github.com/jackalski/HermesAgentHomeAssistant`
3. Install **Hermes Agent** and start it.

Architectures: `amd64`, `aarch64`, `armv7`.

## Quick start (recommended)

**Settings → Add-ons → Hermes Agent → Configuration:**

| Field | What to set |
|-------|-------------|
| `setup_profile` | `home_assistant` (default) |
| `openrouter_api_key` (or another provider) | Your API key |
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

**Alternative** — `lan_reverse_proxy` only if your proxy sends `X-Forwarded-User` (e.g. NPM custom header). If `gateway_trusted_proxies` is empty, the add-on applies defaults (`127.0.0.1,172.30.0.0/16,10.0.0.0/8`) and logs a hint when Cloudflared is detected.

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

- **MQTT** entities when Mosquitto is installed (device: Hermes Agent).
- **JSON API** at Ingress `/status.json` and `/share/hermes/status.json`.

Options: `publish_mqtt_discovery`, `status_poll_interval_seconds` (30–300), `mqtt_state_prefix`.

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
| `default_model_preset` | `auto` | `gemini_flash`, `claude_sonnet`, `gpt_mini`, `custom` |
| `access_mode` | `lan_https` | See access modes above |
| `gateway_port` | `18789` | External HTTPS port in `lan_https` |
| `hass_url` | *(empty)* | Autodetect on HAOS |
| `homeassistant_token` | *(empty)* | Enables MCP + `.env` sync |
| `auto_configure_mcp` | `false` | Auto-on when profile + token set |
| `enable_openai_api` | `false` | Syncs `API_SERVER_ENABLED`; Assist API on **8642**, nginx `/v1/` on **18789** |
| `enable_ha_status_sensors` | `true` | MQTT + status.json |
| `openrouter_api_key` / other provider keys | *(empty)* | Synced to `/config/.hermes/.env` |
| `force_ipv4_dns` | `true` | Recommended on HAOS |
| `nginx_log_level` | `minimal` | Suppresses HA polling noise |
| `hermes_agent_version_preset` | `custom` | `latest` or `custom` — reconciled on restart |
| `hermes_agent_version_custom` | `0.16.0` | npm tag/semver when preset is `custom` |

Provider keys: `openai_api_key`, `openrouter_api_key`, `anthropic_api_key`, `google_api_key`, `minimax_api_key`, `discord_bot_token`, `github_token`, `xai_api_key`.

## Persistence

| Path | Contents |
|------|----------|
| `/config/.hermes/` | `hermes.json`, `config.yaml`, skills, `state.db` |
| `/config/hermesd/` | Workspace |
| `/config/secrets/` | `homeassistant.token` |
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
| `502 Bad Gateway` on `https://<LAN-IP>:18789/` | In `lan_https`, nginx on **18789** proxies to **`hermes dashboard`** on **18790** — 502 means the dashboard is not listening (`hermes gateway run` has no HTTP port); see probe below |
| MCP tools missing | Set token, enable MCP, restart, run `/reload-mcp` |
| `HA (http) — failed` in MCP Servers | Add HA **Model Context Protocol Server** integration; verify token; leave `hass_url` empty on HAOS; run probe below |
| `trusted_proxy_user_missing` | Use token auth (`lan_https`) or configure proxy `X-Forwarded-User` |
| HA URL / MCP failures | Set explicit `hass_url`; check add-on log for autodetection line |
| Low disk | Run `hermes-cleanup` in terminal |
| `Method Not Allowed` on `/v1/chat/completions` | Fixed in **0.0.12+** — enable `enable_openai_api` and restart; use `http://<LAN-IP>:8642/v1` from HA Core (not HTTPS 18789) |
| `Connection error` in Extended OpenAI Conversation | HA Core rejects self-signed HTTPS on 18789 — use Base URL `http://<LAN-IP>:8642/v1` (fixed in **0.0.13+**; API binds `0.0.0.0:8642`, bearer token required) |
| `ModuleNotFoundError: No module named 'hermes_cli.dashboard_auth'` | Add-on **0.0.11+** auto-patches missing wheel subpackages on startup; update to **0.0.14+** with Hermes **0.16.0** |
| `EEXIST: file already exists` at `/usr/local/bin/hermes` during npm reconcile | Fixed in 0.0.9+; update add-on. Harmless on 0.0.8 — startup continues with image-baked `hermes` |
| `externally-managed-environment` during `hermes-agent` npm install | Fixed in 0.0.8+; rebuild/update add-on. Image-baked `hermes` is used if reconcile fails. To stop retries: `echo 0.16.0 > /config/.hermes/.addon-managed-hermes-version` |

Gateway token (if CLI redacts secrets):

```sh
jq -r '.gateway.auth.token' /config/.hermes/hermes.json
```

Gateway upstream probe (`lan_https` — add-on terminal):

```sh
ss -tlnp | grep -E ':18789|:18790'
curl -sS -m 5 -o /dev/null -w "nginx HTTPS: HTTP %{http_code}\n" -k "https://127.0.0.1:18789/"
curl -sS -m 5 -o /dev/null -w "gateway loopback: HTTP %{http_code}\n" "http://127.0.0.1:18790/"
jq '{port:.gateway.port,bind:.gateway.bind,mode:.gateway.mode}' /config/.hermes/hermes.json
```

| Check | Healthy |
|-------|---------|
| `:18789` listener | nginx TLS proxy (external URL) |
| `:18790` listener | Hermes **dashboard** Web UI (nginx upstream; required for HTTPS) |
| Messaging gateway | No HTTP port — `hermes gateway run` + `${HERMES_HOME}/gateway.pid` |
| Loopback curl to `:18790` | Not connection refused (200/302 from dashboard is fine) |

If **18790 is missing**: dashboard failed to start — read add-on log for `Starting Hermes dashboard` errors, or run:

```sh
export HOME=/config HERMES_HOME=/config/.hermes
hermes dashboard --port 18790 --host 127.0.0.1 --no-open --skip-build
```

If import fails: `python3 -m pip install --break-system-packages 'fastapi' 'uvicorn[standard]'`. Confirm `gateway_mode` is `local` (not `remote`).

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
