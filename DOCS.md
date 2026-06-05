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

1. Create a long-lived token in your HA profile.
2. Paste into `homeassistant_token`; enable `auto_configure_mcp` (or use `setup_profile: home_assistant` with token set).
3. Restart. Logs should show `MCP server 'HA' registered`.
4. In gateway chat: `/reload-mcp` if tools are missing.

### Status sensors

With `enable_ha_status_sensors` (default ON):

- **MQTT** entities when Mosquitto is installed (device: Hermes Agent).
- **JSON API** at Ingress `/status.json` and `/share/hermes/status.json`.

Options: `publish_mqtt_discovery`, `status_poll_interval_seconds` (30–300), `mqtt_state_prefix`.

### Chat, voice, Assist

- Install [Hermes Agent integration](https://github.com/jackalski/HermesAgentHomeAssistantIntegration) via HACS for chat card and voice.
- For Assist pipeline: set `enable_openai_api: true`, install integration or Extended OpenAI Conversation.

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
| `enable_openai_api` | `false` | Assist / OpenAI-compatible API |
| `enable_ha_status_sensors` | `true` | MQTT + status.json |
| `openrouter_api_key` / other provider keys | *(empty)* | Synced to `/config/.hermes/.env` |
| `force_ipv4_dns` | `true` | Recommended on HAOS |
| `nginx_log_level` | `minimal` | Suppresses HA polling noise |
| `hermes_agent_version_preset` | `latest` | `0.15.2`, `0.15.1`, `0.14.0`, `custom` — reconciled on restart |
| `hermes_agent_version_custom` | *(empty)* | npm tag/semver when preset is `custom` |

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
| MCP tools missing | Set token, enable MCP, restart, run `/reload-mcp` |
| `trusted_proxy_user_missing` | Use token auth (`lan_https`) or configure proxy `X-Forwarded-User` |
| HA URL / MCP failures | Set explicit `hass_url`; check add-on log for autodetection line |
| Low disk | Run `hermes-cleanup` in terminal |

Gateway token (if CLI redacts secrets):

```sh
jq -r '.gateway.auth.token' /config/.hermes/hermes.json
```

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
