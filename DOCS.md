# Hermes Agent Integration — Home Assistant Add-on

Canonical setup and operations guide. This add-on is marked **Experimental** in the Home Assistant add-on store — expect breaking changes between releases. Read [SECURITY.md](SECURITY.md) before enabling remote access.

## What you get

| Service | Port | Purpose |
|---------|------|---------|
| Hermes Web UI (HTTPS) | 18789 (`gateway_port`) | TLS entry to `hermes dashboard` admin UI; `/api/*` for dashboard REST/WebSocket; `/v1/` and `/health` to Assist API when enabled |
| Assist API (HTTP) | 8642 | Extended OpenAI / voice from HA Core (`http://<LAN-IP>:8642/v1`) |
| nginx (Ingress) | 48099 | Landing page, **Connection tests** (`/test/`), `/status.json` |
| ttyd (terminal) | 7681 (configurable) | Browser terminal |

The `hermes gateway run` messaging process has **no HTTP listener** on `gateway.port` in Hermes 0.16+. Loopback dashboard binds a fixed internal port **9120** (9119 + 1); this is not user-configurable and no external HTTPS port is opened for it.

Persistent data lives under `/config/` (`.hermes`, `hermesd`, `secrets`, `keys`, `.linuxbrew`, `.node_global`, etc.). System tools (`hermes`, `uv`, `mcp`) install to **`/usr/local`**; user npm skills from the dashboard go to **`/config/.node_global`**.

## Install

Click the button to open the add add-on repository dialog on your Home Assistant instance:

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fjackalski%2FHermesAgentHomeAssistant)

Or add the repository manually:

1. **Settings → Add-ons → Add-on store → Repositories**
2. Add `https://github.com/jackalski/HermesAgentHomeAssistant`
3. Install **Hermes Agent Integration** and start it.

Architectures: `amd64`, `aarch64` (armv7 dropped in **0.1.0** — Hermes 0.20+ requires Node 26).

From **0.0.37**, the Supervisor **pulls** a prebuilt image (`ghcr.io/jackalski/hermes-agent-addon:<version>`) built by GitHub Actions. It does **not** run `docker build` on the HA host. If install fails with a pull/manifest error, confirm that GHCR package version exists and is **Public**.

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

When `hass_url` is empty or a local placeholder (`localhost` / `127.0.0.1`, with or without `:80` / `:8123`), the add-on resolves URLs at startup:

| Use | Autodetected URL (HAOS) |
|-----|-------------------------|
| MCP registration | `http://supervisor/core/api/mcp` |
| `HOMEASSISTANT_URL` in `.env` | Internal Core host/port from Supervisor (HAOS **2026.8+** defaults to port **80**; older installs and Container stay on **8123**) |

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

`gateway_bind_mode` and `gateway_auth_mode` only take effect when `access_mode` is `custom` — for the other presets, the add-on sets them automatically and any value entered there is ignored.

Set `gateway_public_url` for the **Open Hermes Web UI** button (auto-filled from LAN IP in `lan_https` when empty).

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

Cloudflared forwards WebSockets to the add-on HTTPS origin on `:18789`; add-on nginx normalizes proxy headers (including `Origin`) before the loopback dashboard.

> Nabu Casa remote access only proxies Home Assistant’s HTTP port — use Cloudflared or your own tunnel for Hermes.

**Alternative** — `lan_reverse_proxy` only if your proxy sends `X-Forwarded-User` (e.g. NPM custom header). Add proxy CIDRs under **Gateway Trusted Proxies** (one IP/CIDR per row). If the list is empty, the add-on applies defaults (`127.0.0.1,172.30.0.0/16,10.0.0.0/8`) and logs a hint when Cloudflared is detected.

### External reverse proxy (NPM)

1. `access_mode`: `lan_reverse_proxy`
2. `gateway_trusted_proxies`: proxy source CIDR (e.g. `172.30.0.0/16`)
3. NPM: forward to `http://<HA-LAN-IP>:18789`, enable WebSockets, add header `X-Forwarded-User: hermes-agent`

The add-on nginx on `:18789` normalizes WebSocket proxy headers (including `Origin`) before forwarding to the loopback dashboard. External proxies must still pass WebSocket upgrades through to `:18789`; they do not need to rewrite `Origin` themselves.

## Home Assistant integration

### Tokens (Supervisor vs long-lived)

With **`homeassistant_api`** / **`hassio_api`** enabled (default from **0.0.33**), the add-on can use **`SUPERVISOR_TOKEN`** when:

- `prefer_supervisor_token` is ON (default), and
- no long-lived token is pasted / stored under `/config/secrets/homeassistant.token`

Supervisor tokens are **not** written to secrets. If HA tools/MCP return 401, paste a **long-lived access token** from your HA profile instead.

When the supervisor token is active, `HASS_URL` is set to `http://supervisor/core`.

### MCP (control HA from Hermes)

**Prerequisite:** enable Home Assistant’s **Model Context Protocol Server** integration (Settings → Devices & services → Add integration). Without it, `/api/mcp` returns 404 and Hermes shows `HA (http) — failed`.

1. Prefer Supervisor token (default) **or** create a long-lived token and paste into `homeassistant_token`.
2. Enable `auto_configure_mcp` (or use `setup_profile: home_assistant` with a token available).
3. Leave `hass_url` empty on HAOS (MCP URL becomes `http://supervisor/core/api/mcp`).
4. Restart. Logs should show `MCP server 'HA' registered` and a Home Assistant URL line with MCP endpoint.
5. In gateway chat: `/reload-mcp` if tools are missing.
6. In HA: open the MCP Server integration → expose entities you want Hermes to control.

### Native HA gateway platform (opt-in)

Upstream Hermes also has a **Home Assistant messaging platform** (WebSocket `state_changed` → agent). Setting `HASS_TOKEN` enables HA **device tools** (`ha_*`). Event forwarding still requires filters.

- Leave **`enable_native_ha_platform: false`** (default) unless you want the add-on to seed `platforms.homeassistant` with safe `watch_domains` (binary_sensor, alarm_control_panel, climate).
- Agent replies on this platform use HA **persistent notifications**.
- Hermes 0.22+ ships this platform as the **`homeassistant` plugin** (the `[homeassistant]` extra was removed). The add-on runs `hermes plugins install homeassistant` automatically on startup when it is missing; if that fails (offline), run it manually in the terminal.
- See [Hermes HA messaging docs](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/homeassistant).

### Webhooks + direct delivery (opt-in)

Enable **`webhooks.enable_webhooks`**, restart, then POST to `http://<HA-LAN-IP>:8644/webhooks/<route>` (host network). HMAC secret: `/config/secrets/webhook.secret` (never logged).

Default seeded route **`ha-alert`** (when seed option is ON):

- `deliver_only: true` → **no LLM cost**
- `deliver: homeassistant` → HA persistent notification
- Body JSON field `message` rendered into the notification

Example from HA (shell_command / curl on the HA host network):

```bash
# Read secret from the add-on share/secret path you copied into an HA secret
MSG='{"message":"Front door opened"}'
SECRET="$(cat /config/secrets/webhook.secret)"  # inside the Hermes add-on terminal
# See Hermes docs for HMAC header format (X-Hub-Signature-256 / X-Hermes-Signature).
curl -fsS -X POST "http://127.0.0.1:8644/webhooks/ha-alert" \
  -H "Content-Type: application/json" \
  --data "$MSG"
```

Prefer validating HMAC per [Hermes webhooks docs](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/webhooks). For local testing only, routes can use `INSECURE_NO_AUTH` (not recommended on exposed networks).

### Backup / restore

- Manual: open the add-on terminal and run `hermes-backup-share` (full) or `hermes-backup-share --quick`.
- Archives land in **`/share/hermes/backups/`** (HAOS Share).
- Restore: `hermes import /share/hermes/backups/<file>.zip --force` then restart the add-on.
- Optional: set **`backup.auto_backup_on_start: true`**.

### Status sensors

With `enable_ha_status_sensors` (default ON):

- **MQTT** entities when Mosquitto is installed (device: Hermes Agent Integration).
- **JSON API** at Ingress `/status.json` and `/share/hermes/status.json` (`schema_version: 2`).
- Includes **`gateway_ready`** (gateway up + setup complete) and redacted **`last_error`** from Hermes logs.
- **Usage / cost metrics** from Hermes `state.db` (`sessions` + `session_model_usage` when present):
  - Lifetime + **24h / 7d** windows (tokens, estimated/actual cost, sessions, API calls)
  - Token split: input, output, cache read/write, reasoning
  - Scalars: `cost_24h`, `tokens_24h`, `cache_hit_ratio`, `reasoning_share`, `overhead_ratio`, `overhead_cost_usd`, `compression_cost_usd`, `aux_cost_usd`
  - Rich attributes on **Hermes Usage Summary** (`by_provider`, `by_model`, `by_task`, `windows`, `overhead`)

Options: `publish_mqtt_discovery` (one-shot per add-on version — marker `/config/.hermes/.mqtt_discovery_published`), `status_poll_interval_seconds` (30–300), `mqtt_state_prefix`, `enable_control_entities` (default **OFF** — MQTT buttons/selects; only enable on a trusted broker).

`binary_sensor.hermes_assist_api_enabled` is **true only when the Assist API is accepting connections on port 8642**, not merely when `enable_openai_api` is ticked.

#### MQTT control entities (optional)

When `mqtt_settings.enable_control_entities` is **ON**, the status exporter publishes:

| Entity | Action |
|---|---|
| `button.hermes_refresh_status` | Immediate status poll |
| `button.hermes_run_backup` | `hermes-backup-share --quick` |
| `button.hermes_run_cleanup` | `hermes-cleanup` |
| `button.hermes_restart_gateway` | TERM gateway (supervisor restarts with drain) |
| `select.hermes_approval_mode` | Writes Hermes `approvals.mode`, then queues gateway restart |
| `select.hermes_reasoning_effort` | Writes Hermes `agent.reasoning_effort`, then queues gateway restart |

Anyone with **broker write access** can trigger these — keep Mosquitto locked down. Disabling the option removes retained control discovery topics.

#### Overhead proxies (not absolute waste)

| Field | Formula |
|---|---|
| Aux tokens / cost | `session_model_usage` where `task ≠ ''` (non-main: compression, title, vision, …) |
| Compression cost | task `compression` |
| Compression splits | sessions with `parent_session_id` set |
| Overhead tokens | aux + reasoning + cache write |
| Overhead cost | aux cost + session cost share of reasoning + cache write |
| Overhead ratio | overhead cost ÷ total cost |
| Cache hit ratio | cache read ÷ (input + cache read) |
| Reasoning share | reasoning ÷ (output + reasoning) |
| Failed-session cost | sessions whose `end_reason` matches error/timeout/crash/… |

#### Usage dashboard (Home Assistant)

On each add-on start, importable YAML is copied to **`/share/hermes/ha/`**. The same tree is also served read-only on Ingress under `./ha/` from an **image-local copy** (so Copy/Download buttons work regardless of Share directory permissions):

| Path | Purpose |
|---|---|
| `/share/hermes/ha/packages/hermes_usage.yaml` | Template sensors, monthly/daily utility meters, budget helpers |
| `/share/hermes/ha/dashboards/hermes_usage.yaml` | Lovelace dashboard (**Operations** / **Analysis**) |
| `/share/hermes/ha/blueprints/automation/` | Budget, gateway-offline, disk, and voice-announce blueprints |

**HACS frontend cards required** (install via HACS → Frontend before importing the dashboard):

- [Mushroom](https://github.com/piitaya/lovelace-mushroom)
- [card-mod](https://github.com/thomasloven/lovelace-card-mod)
- [apexcharts-card](https://github.com/RomRider/apexcharts-card)

Install steps:

1. Enable MQTT status sensors + Mosquitto; wait for discovery entities (device **Hermes Agent Integration**).
2. In HA `configuration.yaml`:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
3. Copy the package file into HA config: `config/packages/hermes_usage.yaml` (from Share `hermes/ha/packages/`).
4. Restart Home Assistant Core.
5. Install the three HACS cards above (Lovelace resources are added automatically).
6. Create a dashboard and paste `/share/hermes/ha/dashboards/hermes_usage.yaml` (or merge its `views:`).
   Tip: open the add-on **Ingress** page → Home Assistant → **Copy dashboard YAML**.
7. Optional: copy blueprints from `/share/hermes/ha/blueprints/automation/` into `config/blueprints/automation/hermes/` and create automations from them.
   Tip: on the Ingress page use each blueprint’s **Copy** / **Download** buttons (same as the dashboard YAML).
8. Set `input_number.hermes_monthly_budget_usd` on the Operations view (or Developer Tools) for the budget gauge.

If cards show as `Custom element doesn't exist` / unknown `custom:…` type, the HACS cards are missing or the browser cache needs a hard refresh.

Source YAML in the repo lives under [`hermes_agent/ha_dashboard/`](hermes_agent/ha_dashboard/) (baked into the add-on image). For browsing without an installed add-on, download the **`homeassistant-hermes-usage-*`** artifact from the [HA dashboard artifact](https://github.com/jackalski/HermesAgentHomeAssistant/actions/workflows/ha-dashboard.yml) workflow (layout: `homeassistant/packages/` + `homeassistant/dashboards/`).

Expected MQTT entity IDs use discovery slugs (`sensor.hermes_*`, `binary_sensor.hermes_*`, `button.hermes_*`) from add-on **0.0.42+** (`object_id`) and **0.0.47+** (`default_entity_id`, required on Home Assistant **2026.4+** where `object_id` is ignored). If you renamed entities, or first discovered them where HA prefixed the device name (`sensor.hermes_agent_integration_hermes_*`), either rename entity IDs to match or delete the **Hermes Agent Integration** MQTT device and restart the add-on so discovery recreates them.

### ntfy (opt-in)

Enable **`ntfy.enable_ntfy`**, set **`ntfy_topic`**, restart. Env is written to `/config/.hermes/.env`. With **`ntfy_publish_only`** (default ON), Hermes pushes alerts without accepting inbound ntfy chat.

### LM Studio (local OpenAI-compatible)

Set **`default_provider: lm_studio`**, **`lm_studio_base_url`** (e.g. `http://192.168.1.50:1234/v1`), and **`default_model`**. First-run bootstrap writes Hermes `model.provider: custom` with that base URL (only when model config is still empty).

### no_agent cron (zero LLM)

Example scripts are seeded under `/config/.hermes/scripts/` when **`seed_example_scripts`** is ON:

```bash
hermes cron create "*/15 * * * *" --no-agent --script disk-alert.sh --deliver homeassistant --name disk-alert
hermes cron create "0 8 * * *" --no-agent --script morning-heartbeat.sh --deliver ntfy --name morning-heartbeat
```

See [Script-only cron](https://hermes-agent.nousresearch.com/docs/guides/cron-script-only). Empty stdout = silent tick.

### Scale-to-zero note

Upstream **Chronos** cron (`cron.provider: chronos`) is for Nous-hosted scale-to-zero gateways. On HAOS the add-on stays running; use **webhook wake**, **no_agent cron**, and **`gateway_drain_seconds`** on stop instead.

### Chat, voice, Assist

Hermes 0.20+ splits voice into two directions. **Wake word and microphone stay on Home Assistant
Voice satellites** (Voice PE, ESPHome Assist satellite, Android companion) — the add-on container
has no audio device. Hermes is the **brain** (conversation agent) and can also **push spoken
announcements** back into the house.

#### Inbound — you talk to the house (Assist)

1. Set **`enable_openai_api: true`** in add-on Configuration (syncs `API_SERVER_ENABLED=true` to `/config/.hermes/.env`).
2. Install [Extended OpenAI Conversation](https://github.com/jekalmin/extended_openai_conversation) via HACS, or the [Hermes Agent integration](https://github.com/jackalski/HermesAgentHomeAssistantIntegration) for chat card and voice.
3. **Extended OpenAI Conversation** settings:

| Field | Value |
|-------|-------|
| Base URL | `http://<LAN-IP>:8642/v1` (HTTP from HA Core — avoids self-signed HTTPS on 18789) |
| API Key | Gateway token: `jq -r '.gateway.auth.token' /config/.hermes/hermes.json` |
| Model | `hermes-agent` |
| Skip authentication | ON (optional; helps during setup) |

HTTPS on port 18789 still works for browsers and `curl -k`; HA Core rejects the self-signed cert, so use **8642** for Extended OpenAI.

4. Restart add-on after enabling Assist API or after first `hermes onboard` (gateway reads `API_SERVER_*` at startup).
5. In **Settings → Voice assistants**, set conversation agent to Extended OpenAI Conversation (or Hermes Agent), STT to Whisper (or cloud), TTS to Piper / HA Cloud, and expose entities.
6. Keep **`agent_behavior.max_turns`** modest (default **60**). Upstream Hermes jumped the iteration default to 500 — fine for coding, expensive and slow for Assist.
7. For Assist session memory continuity, clients can send Hermes session headers:
   - `X-Hermes-Session-Key: ha-assist-<device_id>` (stable per device/conversation)
   - optional `X-Hermes-Session-Name: Assist Kitchen`
   - Without a session key, each Assist request may start a fresh Hermes session.

#### Outbound — the house talks to you

1. Create a Home Assistant webhook automation from blueprint
   `/share/hermes/ha/blueprints/automation/hermes_voice_announce.yaml`
   (copy into `config/blueprints/automation/hermes/` first).
2. Set add-on **`outbound_events.enable_outbound_events: true`** and
   **`outbound_events.ha_webhook_id`** to that webhook id (HMAC secret stored at
   `/config/secrets/outbound_webhook.secret` — never logged).
3. Or enable webhooks and keep **`ha_voice_bridge.seed_ha_speak_route: true`** so Hermes gets a
   zero-LLM `ha-speak` direct-delivery route (`deliver: homeassistant`).
4. Package scripts `script.hermes_announce` / `script.hermes_ask` (in
   `/share/hermes/ha/packages/hermes_usage.yaml`) speak arbitrary text or run Assist then TTS.

#### Hermes STT / TTS tools (gateway voice notes)

Use the **Voice & Speech** panel for Hermes-side transcription of inbound voice notes and the
`text_to_speech` tool (`edge` default; optional Piper / KittenTTS / cloud providers).
`stt_language: auto` picks up Home Assistant Core's language when available.

Optional: seed **`ha-tts-command.py`** (`ha_voice_bridge.seed_ha_tts_command_script`) so Hermes
command-TTS can call HA `/api/tts_get_url` and speak in your existing Piper / Cloud voice.

**Troubleshooting:** if you expected on-device wake words inside the add-on terminal, use a Voice
satellite instead — wake word detection requires a microphone, which the container does not have.

## Configuration reference

Full schema: [`hermes_agent/config.yaml`](hermes_agent/config.yaml).

| Option | Default | Notes |
|--------|---------|-------|
| `setup_profile` | `home_assistant` | Preset for first-run behavior |
| `timezone` | `auto` | Detect from HA Core via Supervisor; fallback `Etc/UTC` |
| `default_provider` | `openrouter` | `nous`, `openrouter`, `google`, `anthropic`, `ollama`, `minimax`, `xai`, `openai`, `lm_studio` |
| `default_model_preset` | `custom` | `custom` only — set model ID in `default_model` |
| `lm_studio_base_url` | `http://127.0.0.1:1234/v1` | Used when provider is `lm_studio` |
| `access_mode` | `lan_https` | See access modes above |
| `gateway_port` | `18789` | External HTTPS port for Hermes Web UI in `lan_https`; Assist API `/v1/` proxied here when enabled |
| `hass_url` | *(empty)* | Autodetect on HAOS |
| `homeassistant_token` | *(empty)* | Optional if `prefer_supervisor_token` |
| `prefer_supervisor_token` | `true` | Use `SUPERVISOR_TOKEN` when no pasted token |
| `auto_configure_mcp` | `false` | Auto-on when profile + token set |
| `enable_native_ha_platform` | `false` | Seed `platforms.homeassistant` event filters |
| `enable_webhooks` | `false` | Webhook adapter + `WEBHOOK_*` env |
| `webhook_port` | `8644` | Host-network webhook listen port |
| `auto_backup_on_start` | `false` | Quick backup to `/share/hermes/backups` |
| `fallback_providers` | `[]` | Bootstrap Hermes fallback chain if missing |
| `nous_tool_gateway` | `false` | Seed `use_gateway` on managed tools |
| `gateway_drain_seconds` | `15` | Drain wait on add-on stop |
| `enable_ntfy` | `false` | Sync `NTFY_*` for push/cron |
| `seed_example_scripts` | `true` | Seed no_agent example scripts |
| `approval_mode` | `smart` | Bootstraps `approvals.mode` if missing |
| `reasoning_effort` | `medium` | Bootstraps `agent.reasoning_effort` if missing |
| `show_reasoning` | `true` | Bootstraps `display.show_reasoning` if missing |
| `max_turns` | `60` | Bootstraps `agent.max_turns` if missing (Assist-safe) |
| `session_auto_prune` | `false` | Bootstraps `sessions.auto_prune` if missing (Hermes 0.22+ upstream default is OFF). Pruned sessions disappear from usage history |
| `session_retention_days` | `90` | Bootstraps `sessions.retention_days` if missing (1–3650) |
| `smart_policy` | *(empty)* | Bootstraps `approvals.smart_policy` if missing |
| `denial_breaker_threshold` | `3` | Bootstraps `approvals.denial_breaker_threshold` |
| `deny_patterns` | HA-safe defaults | Bootstraps `approvals.deny` if missing |
| `stt_enabled` / `stt_provider` / `stt_language` | on / local / auto | Voice & Speech panel → `stt.*` |
| `tts_provider` / `tts_voice` / `tts_speed` | edge / AriaNeural / 1.0 | Voice & Speech panel → `tts.*` |
| `threshold_tokens` / `proactive_prune_tokens` | `0` / `0` | Context compression (0 = unset/off) |
| `min_tail_user_messages` | `4` | Guaranteed recent user messages after compression |
| `enable_outbound_events` | `false` | Seed `hooks.outbound` when Hermes supports it |
| `ha_webhook_id` | *(empty)* | Target HA webhook for outbound lifecycle events |
| `seed_ha_speak_route` | `true` | Seed webhook route `ha-speak` |
| `seed_ha_tts_command_script` | `true` | Seed `ha-tts-command.py` |
| `tool_a2a_enabled` | `false` | A2A plugin (capability-probed) |
| `tool_office_skills_enabled` | `false` | Attempt office skills install |
| `enable_openai_api` | `false` | Syncs `API_SERVER_ENABLED`; Assist API on **8642**, nginx `/v1/` and `/health` on **18789** |
| `enable_ha_status_sensors` | `true` | MQTT + status.json |
| `enable_control_entities` | `false` | MQTT buttons/selects for backup, cleanup, restart, approval/reasoning (trusted broker only) |
| **Home Assistant** panel | — | URL, token, prefer supervisor, MCP, native platform |
| **Voice & Speech** panel | local STT / Edge TTS | Hermes STT/TTS bootstrap |
| **HA Voice Bridge** panel | speak route ON | Assist + announcement helpers |
| **Agent Behavior** panel | smart / medium / ON / 60 | Approvals + reasoning + max turns |
| **Context Compression** panel | — | Token thresholds / tail / idle compact |
| **Outbound Events** panel | OFF | Hermes → HA webhook lifecycle push |
| **Gateway Access** panel | `lan_https` | `access_mode`, `gateway_port`, trusted proxies, Assist API, etc. |
| **MQTT Status Sensors** panel | autodetect | `broker_host` / `broker_port` / `broker_username` / `broker_password`; leave host empty for Mosquitto autodetect |
| **Provider API Keys** panel | *(empty)* | Synced to `/config/.hermes/.env` (preserved on reinstall) |
| **Router SSH** panel | — | `host`, `user`, `key_path` (default `/config/keys/router_ssh`) |
| **Tool Bootstrap** panel | browser ON | Telegram / Discord / browser / Skills Hub / A2A / office |
| **Hermes Web UI** panel | ON / auto-start | `enable_web_interface`, `auto_start_with_integration` (dashboard binds a fixed internal port; not user-configurable) |
| **Advanced Settings** panel | — | `http_proxy`, `nginx_log_level`, `gateway_env_vars`, Hermes version |
| `addon_log_level` | `info` | Add-on startup log verbosity |
| `force_ipv4_dns` | `true` | Recommended on HAOS |
| `nginx_log_level` | `minimal` | Suppresses HA polling noise |
| `hermes_agent_version_preset` | `custom` | `latest` or `custom` — reconciled on restart |
| `hermes_agent_version_custom` | `v0.22.5` | GitHub release tag or Hermes version when preset is `custom` |

Provider keys live under **`provider_api_keys`** in the add-on UI (OpenAI, OpenRouter, Anthropic, Google, Ollama Cloud, MiniMax, Discord, GitHub, xAI, Firecrawl, SearXNG, ElevenLabs, Groq, DeepInfra). **Nous Portal** uses OAuth in the terminal (`hermes setup --portal`); **Ollama** in `default_provider` maps to Hermes `ollama-cloud`.

**`enable_openai_api`** maps directly to Hermes **`API_SERVER_ENABLED`** in `/config/.hermes/.env` (with `API_SERVER_HOST`, `API_SERVER_PORT`, `API_SERVER_KEY`).

## Connection tests (add-on Web UI)

Home Assistant add-on Configuration has no native **Test** buttons. Instead, open the add-on **Web UI** (Ingress landing page) and expand **Connection tests** — **one button per setting**, grouped by configuration panel:

| Panel | Tests |
|-------|-------|
| **Home Assistant Integration** | **Test URL** (`hass_url`), **Test Token** (`homeassistant_token`), **Test MCP** (`auto_configure_mcp`) |
| **MQTT Status Sensors** | **Test Broker** (`broker_host` / autodetect), **Test Auth** (`broker_username` / `broker_password`) |
| **Hermes Web UI** | **Test Dashboard** (loopback process), **Test Web UI HTTPS** (`gateway_port` in `lan_https`) |
| **Gateway Access** | **Test Gateway** (local process), **Test Remote** (`gateway_remote_url` when `gateway_mode=remote`), **Test Assist API** (`enable_openai_api`) |
| **Web Terminal** | **Test Terminal** (`enable_terminal` / `terminal_port`) |
| **Run all** | Every test above (skipped entries count as OK) |

Results appear inline on the landing page. Configuration field descriptions reference the matching test name.

## Persistence

| Path | Contents |
|------|----------|
| `/config/.hermes/` | `hermes.json`, `config.yaml`, skills, `state.db` |
| `/config/hermesd/` | Workspace |
| `/config/secrets/` | `homeassistant.token`, `webhook.secret` |
| `/config/keys/` | Router SSH private keys (default `router_ssh`) |
| `/config/secrets/mqtt.password` | Persisted MQTT broker password (when set in add-on config) |
| `/config/certs/` | TLS certs (`lan_https`) |
| `/share/hermes/backups/` | `hermes-backup-share` archives |
| `/share/hermes/ha/` | Importable HA usage package + Lovelace dashboard YAML |

Hermes binary in the image is replaced on update; `/config/` data persists. When the add-on reconciles a different Hermes GitHub tag, logs show **`Update progress [1/3]`…`[3/3]`** lines — open the add-on **Log** tab to follow long installs on HAOS.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Install/update fails pulling `ghcr.io/jackalski/hermes-agent-addon` | Confirm the version tag exists (GitHub Actions → **Build add-on images**) and the GHCR package is **Public**. Refresh the add-on repository and retry. |
| Docker build fails with `getaddrinfo EAI_AGAIN` / `registry.npmjs.org` | Only applies when building the Dockerfile locally/CI. On HAOS **0.0.37+** the Supervisor pulls GHCR (no local build). For manual Dockerfile builds, retry and check DNS/IPv6; **0.0.36+** retries npm installs. |
| `HTTP 400: No models provided` | Set provider API key in add-on config; restart; verify model in `/config/.hermes/config.yaml` |
| OpenRouter HTTP 402 (insufficient credits) | Add credits at [openrouter.ai/settings/credits](https://openrouter.ai/settings/credits) or use a direct provider key (`google_api_key`, `anthropic_api_key`, …) |
| Owl Alpha / Stealth HTTP 400 | Upstream flake on free model; switch to `google/gemini-2.5-flash` via `hermes model` or add-on model preset |
| `no such gateway 'default'` in terminal | Use `hermes gateway run` (not `hermes-agent gateway run`); ensure `HOME=/config` and `HERMES_HOME=/config/.hermes` (ttyd sets this automatically) |
| Gateway unreachable on LAN | Check `access_mode`; install CA cert for `lan_https` (landing page download) |
| `502 Bad Gateway` on `https://<LAN-IP>:18789/` | In `lan_https`, nginx proxies to **`hermes dashboard`** on a fixed loopback port (**9120**). 502 means the dashboard is not listening — check `enable_web_interface`, `hermes-agent[web]`, and add-on logs. |
| `/api/status` 404 on HTTPS `gateway_port` | Fixed in **0.0.27+** — Assist API no longer steals `/api/*`. Dashboard `/api/*` is served on `gateway_port`; Assist uses `/v1/` (HTTPS) or `http://LAN:8642/v1` (HA Core). |
| `/api/sessions` 401 from curl | Expected without auth — pass `Authorization: Bearer <gateway token>`. Browser Chat uses dashboard session tokens from the Web UI, not the gateway token. |
| Chat WebSocket `CONNECTION_REFUSED` / PTY **1006** | Fixed in **0.0.30+** — browser `Origin` (LAN IP or tunnel hostname) was forwarded to the loopback dashboard, which rejects non-loopback origins on WebSocket upgrades. Add-on nginx clears `Origin` on the upstream hop; REST was unaffected. Update add-on and restart. |
| Chat PTY WebSocket 403 | Fixed in **0.0.27+** when caused by `/api/pty` routed to Assist API; fixed in **0.0.30+** when caused by Origin mismatch behind nginx. Open **Hermes Web UI** via the landing button; use Chat from the UI. |
| MCP tools missing | Set token, enable MCP, restart, run `/reload-mcp` |
| `mcp.client.streamable_http is not available` / HTTP MCP (HA, …) fails | Add-on **0.0.45+** pins MCP SDK `>=1.26,<2` (Hermes 0.19). Update the add-on and restart; startup repairs a wrongly-installed mcp 2.x. |
| `HA (http) — failed` in MCP Servers | Add HA **Model Context Protocol Server** integration; verify token; leave `hass_url` empty on HAOS; run probe below |
| `trusted_proxy_user_missing` | Use token auth (`lan_https`) or configure proxy `X-Forwarded-User` |
| HA URL / MCP failures | Set explicit `hass_url`; check add-on log for autodetection line |
| Low disk | Run `hermes-cleanup` in terminal |
| `Method Not Allowed` on `/v1/chat/completions` | Fixed in **0.0.12+** — enable `enable_openai_api` and restart; use `http://<LAN-IP>:8642/v1` from HA Core (not HTTPS 18789) |
| `Connection error` in Extended OpenAI Conversation | HA Core rejects self-signed HTTPS on 18789 — use Base URL `http://<LAN-IP>:8642/v1` (fixed in **0.0.13+**; API binds `0.0.0.0:8642`, bearer token required) |
| MQTT status sensors missing / "MQTT broker not available" | Install and start **Mosquitto broker** add-on; use **Connection tests → Test Broker** / **Test Auth** on the Web UI after saving broker settings; fixed in **0.0.15+** (Supervisor API + retry) |
| `MQTT publish timed out` for many topics (broker resolved) | TCP connect worked but QoS1 PUBACK never arrived — check Mosquitto ACL allows write to `homeassistant/#` and your state prefix (`hermes/#` by default), and that broker username/password can publish. Use **Connection tests → Test Auth**. |
| Hermes entities show **Unavailable** while the add-on is stopped | Expected from **0.0.43+** — the MQTT client registers a Last Will so entities stop reporting stale values on crash/shutdown. They return to normal within one poll interval after the add-on starts. |
| MQTT auth fails although Mosquitto autodetection succeeds | Update to **0.0.43+** — autodetection now prefers the Supervisor API, which also supplies broker credentials (bashio reports host/port only). |
| Usage dashboard shows unavailable / wrong entities (`hermes_agent_integration_hermes_*`) | Add-on **0.0.47+** publishes `default_entity_id` (HA 2026.4+ ignores `object_id`). Rename entity IDs, or delete the MQTT device **Hermes Agent Integration** and restart the add-on so discovery recreates short IDs. |
| Usage dashboard “Configuration error” on conditional cards | Re-import `/share/hermes/ha/dashboards/hermes_usage.yaml` from **0.0.47+** (uses state conditions, not `condition: template`). |
| Budget gauge / `sensor.hermes_cost_today` missing | Install package `hermes_usage.yaml` under `packages:` and restart Home Assistant Core. |
| `ModuleNotFoundError: No module named 'hermes_cli.dashboard_auth'` | Add-on **0.0.11+** auto-patches missing wheel subpackages on startup; update to **0.0.14+** with Hermes **0.16.0** |
| `EEXIST: file already exists` at `/usr/local/bin/hermes` during npm reconcile | Fixed in 0.0.9+; update add-on. Harmless on 0.0.8 — startup continues with image-baked `hermes` |
| `externally-managed-environment` during Hermes install | Fixed in 0.0.8+; rebuild/update add-on. Image-baked `hermes` is used if reconcile fails. To stop retries: `echo v2026.8.3 > /config/.hermes/.addon-managed-hermes-version` |
| Hermes GitHub tag install fails on restart | Startup keeps the previous CLI and logs a tip. Set `hermes_agent_version_custom` to a known tag (e.g. `v0.22.5` or `0.22.5`) and restart. |
| `[raft] raft CLI not found in PATH` in gateway logs | Fixed in **0.0.29+** — add-on installs `@botiverse/raft` globally. Only needed if you use Raft messaging (`RAFT_PROFILE` in `/config/.hermes/.env`); see [Hermes Raft docs](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/raft). |
| Mosquitto log spam (`New connection` / `disconnected` every minute) | Fixed in **0.0.19+** — persistent MQTT client + one-shot discovery. Optional: Mosquitto `connection_messages false` in customize |
| Expected wake word / barge-in inside the add-on | The container has **no microphone** — use HA Voice PE / ESPHome Assist satellites for wake word + STT/TTS. Hermes is the conversation agent via Assist API (`enable_openai_api`). |
| Node version warning after upgrade | Hermes 0.20+ requires **Node 26** (baked in the image). Update/rebuild the add-on; `/config/.node_global` cannot raise the system Node major. |

Gateway token (if CLI redacts secrets):

```sh
jq -r '.gateway.auth.token' /config/.hermes/hermes.json
```

Gateway + Web UI upstream probe (`lan_https` — add-on terminal):

```sh
ss -tlnp | grep -E ':18789|:18790|:9120|:8642'
curl -sS -m 5 -o /dev/null -w "Web UI HTTPS: HTTP %{http_code}\n" -k "https://127.0.0.1:18789/"
curl -sS -m 5 -o /dev/null -w "dashboard loopback /api/status: HTTP %{http_code}\n" "http://127.0.0.1:9120/api/status"
curl -sS -m 5 -o /dev/null -w "Assist API /health: HTTP %{http_code}\n" "http://127.0.0.1:8642/health"
jq '{port:.gateway.port,bind:.gateway.bind,mode:.gateway.mode}' /config/.hermes/hermes.json
```

Dashboard REST API (requires bearer token):

```sh
TOKEN="$(jq -r '.gateway.auth.token' /config/.hermes/hermes.json)"
curl -sk -H "Authorization: Bearer $TOKEN" "https://<LAN-IP>:18789/api/sessions?limit=50"
```

| Check | Healthy |
|-------|---------|
| `:18789` listener | nginx TLS proxy → Hermes Web UI (`hermes dashboard`) |
| `:9120` listener | Hermes Web UI loopback upstream (`hermes dashboard`) |
| Loopback `/api/status` on `:9120` | HTTP 200 |
| Messaging gateway | `hermes gateway run` + `${HERMES_HOME}/gateway.pid` |

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
| `000` / timeout | Wrong `hass_url` or network — leave `hass_url` empty on HAOS, or set `http://homeassistant` (port 80) / `http://homeassistant:8123` |

## Hermes 0.22 upgrade notes

- **Tags**: Hermes now uses SemVer tags (`v0.22.5`); legacy `v2026.x.y` pins and `0.20.0`-style versions still resolve. `v0.22.1` is not mapped (broken upstream build).
- **Home Assistant platform** is a plugin; the add-on installs it on startup (`hermes plugins install homeassistant`).
- **Protected files**: writes to AGENTS.md, skills and memory stores always require approval regardless of `approval_mode`.
- **MCP**: stdio MCP servers no longer inherit the default profile's vault secrets; pass needed secrets explicitly in the server's `env`.
- **Sessions**: idle/daily session resets are retired. Optional pruning via `session_auto_prune` / `session_retention_days`.
- **Lazy extras**: messaging, voice and some provider backends install on first use upstream; the image pre-installs `messaging` and `tts-premium`. Other backends need network at first use.
- **`hermes update`** is not the supported upgrade path in this add-on; change `hermes_agent_version_custom` instead.

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
