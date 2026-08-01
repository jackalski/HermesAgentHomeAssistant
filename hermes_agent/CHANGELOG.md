# Changelog

All notable changes to the Hermes Agent Integration Home Assistant Add-on are documented in this file.

## [0.0.46] - 2026-08-01

### Added
- **MQTT control entities** (opt-in, default **OFF**): `mqtt_settings.enable_control_entities` publishes buttons (refresh status, backup, cleanup, restart gateway) and selects (approval mode, reasoning effort). Scripts run from the status exporter; gateway restart goes through `/var/run/hermes-control/` watched by `run.sh`.
- **Budget helpers** in the HA package: `input_number.hermes_monthly_budget_usd`, daily/monthly `utility_meter` over `sensor.hermes_estimated_cost_usd`, plus budget-% and projected month-end template sensors.
- **Automation blueprints** under `/share/hermes/ha/blueprints/automation/` (budget, gateway offline, disk) using `persistent_notification`.
- **Timestamp sensors**: `sensor.hermes_updated_at`, `hermes_last_session_at`, `hermes_gateway_health_probe_at`.
- Ingress serves `/share/hermes/ha/` at `./ha/` with a **Copy dashboard YAML** button on the landing page.
- Dockerfile now copies `ha_dashboard/` into the image so share sync works at runtime.

### Changed
- **Usage dashboard** redesigned as two multi-column views (**Operations** / **Analysis**) with Hermes accent styling (re-import the dashboard YAML).
- **`binary_sensor.hermes_assist_api_enabled`** reflects a live probe on port 8642 (not only the `enable_openai_api` option).
- Monetary MQTT sensors advertise `suggested_display_precision: 4`.
- Status exporter add-on version fallback aligned to **0.0.46** (forces MQTT discovery republish).

### Fixed
- **`sensor.hermes_last_error`**: state truncated for HA’s 255-character limit; full redacted line published as a JSON attribute.
- Status exporter crash recovery via the control watcher (respawn if the process exits).

## [0.0.45] - 2026-08-01

### Fixed
- **HTTP MCP servers broken after mcp 2.0**: the image installed unpinned `mcp`, which resolved to 2.x and dropped `streamablehttp_client`. Hermes 0.19 then logged `mcp.client.streamable_http is not available` for every HTTP MCP server (Home Assistant, custom URLs). The add-on now pins `mcp>=1.26.0,<2` (Hermes' declared line) and repairs the SDK at startup if the HTTP transport symbol is missing.
- **MQTT timeout log spam**: when the broker never PUBACKs (ACL / credentials / unreachable), status export now emits one summary warning instead of one line per topic (~50). Local publish rejects (`rc != 0`) are reported immediately.

### Changed
- Status exporter add-on version fallback aligned to **0.0.45**.

## [0.0.44] - 2026-08-01

### Fixed
- **armv7 Node install**: NodeSource `node_24.x` has no `nodejs` package for armhf (only `nsolid`), so the 0.0.43 image build fell back to Debian Node 18 and failed the version guard. armv7 now installs **Node 22 LTS**; amd64/aarch64 stay on **Node 24 LTS**.
- Status exporter add-on version fallback aligned to **0.0.44**.

## [0.0.43] - 2026-08-01

### Fixed
- **MQTT broker probing**: status exporter no longer re-resolves the broker (and TCP-probes it) on every poll while the MQTT session is already connected. Resolve once, reuse the live connection; retry discovery only after disconnect or missing host.
- **Host-network TCP fallback**: reachability probes (`core-mosquitto` → `127.0.0.1`) run only for auto-detected Supervisor/bashio endpoints, not for explicit `mqtt_settings` / env hosts.
- **MQTT broker credentials**: the Supervisor API is now queried before bashio when autodetecting Mosquitto. bashio only reports host/port, so on brokers that require authentication the add-on could resolve an endpoint without username/password and fail to connect.
- **Entity availability after a crash**: the MQTT client registers a Last Will (`<prefix>/status/availability` → `offline`, retained) and publishes `offline` on shutdown. Previously all Hermes entities stayed "available" with frozen values if the add-on stopped unexpectedly.
- **Invalid broker port**: a non-numeric `port` no longer raises on every poll cycle; the exporter warns once per cycle and falls back to `1883`.
- **MQTT discovery marker**: only written after the broker acknowledges the full discovery batch, so a failed publish is retried on the next poll instead of being marked done.

### Changed
- **Node.js 24 LTS "Krypton"** replaces Node 22 "Jod" on amd64/aarch64. armv7 remains on Node 22 (see 0.0.44).
- **Status publishing is batched**: the ~50 state topics of a poll cycle are handed to the broker together and awaited in one shared timeout window instead of blocking on a QoS 1 round-trip per topic. Cuts a typical cycle from seconds to tens of milliseconds on slower or remote brokers.
- **Hermes version lookup cached**: `hermes --version` runs once per process rather than spawning a subprocess (15 s timeout) on every poll.
- **Poll interval no longer drifts**: the sleep subtracts the cycle duration, so `status_poll_interval_seconds` is the actual period.
- Connection tests resolve the broker once per run; `mqtt_broker` and `mqtt_auth` no longer repeat autodetection (bashio subprocess, Supervisor requests, TCP probes).
- Status exporter add-on version fallback aligned to **0.0.43**.

## [0.0.42] - 2026-07-30

### Fixed
- **MQTT discovery entity IDs**: publish an explicit `object_id` (`hermes_*`) so Home Assistant does not create device-prefixed IDs like `sensor.hermes_agent_integration_hermes_last_error`. Matches the usage dashboard/package (`sensor.hermes_*`, `binary_sensor.hermes_*`).
  - Already-discovered entities keep their old entity IDs until you rename them or delete the **Hermes Agent Integration** MQTT device and let discovery recreate it after updating.

### Changed
- Removed the duplicate repo tree `homeassistant/`. Source of truth remains `hermes_agent/ha_dashboard/`; CI builds the `homeassistant/{packages,dashboards}` layout and uploads it as the **HA dashboard artifact** workflow artifact.
- **Usage package/dashboard**: dropped redundant `*_attr` template sensors that duplicated MQTT scalars; dashboard uses MQTT entities directly. Package keeps only helpers MQTT does not publish (`cost_7d`, `tokens_7d`, `failed_session_cost`, `compression_splits`, top spender / breakdown markdown).
- **ApexCharts breakdown cards**: replaced unsupported `chart_type: bar` + categorical `[label, value]` `data_generator` (RomRider card only allows `line`/`scatter`/`pie`/`donut`/`radialBar`, and generators must return `[timestamp_ms, value]`) with `series.type: column` charts. Labels remain in the markdown tables.
- Status exporter add-on version fallback aligned to **0.0.42** (forces one-shot MQTT discovery republish).

## [0.0.41] - 2026-07-30

### Changed
- **Usage dashboard** now uses HACS **Mushroom**, **card-mod**, and **apexcharts-card** (health/provider chips, KPI tiles, dual-axis trends, breakdown bars, overhead donut). Install those cards before importing `/share/hermes/ha/dashboards/hermes_usage.yaml`.
- **README**: My Home Assistant “add repository” badge, clearer post-install config path; removed Star History.
- Status exporter add-on version fallback aligned to **0.0.41** (forces one-shot MQTT discovery republish).

## [0.0.40] - 2026-07-30

### Added
- **Usage / cost MQTT metrics** (`schema_version: 2`): lifetime + 24h/7d windows, cache/reasoning/actual cost scalars, and `usage_attributes` breakdowns (`by_provider`, `by_model`, `by_task`, `overhead` proxies) from `state.db` / `session_model_usage`.
- **Home Assistant package + Lovelace dashboard**: synced on start to `/share/hermes/ha/` (also under repo `homeassistant/`) for template sensors and an Overview / Cost / Breakdown / Overhead dashboard (built-in cards only).

### Changed
- Status exporter add-on version fallback aligned to **0.0.40** (forces one-shot MQTT discovery republish).

## [0.0.39] - 2026-07-23

### Removed
- **`dashboard_port` option**: removed from the Hermes Web UI panel. The hermes dashboard now always binds a fixed internal loopback port (9119/9120); this was never externally reachable on its own and had been deprecated as a second LAN port since 0.0.27.
- **Legacy flat-key options fallback** in `run.sh` (pre-0.0.16 compatibility) and the one-time `/data` → `/config` router SSH key migration: no longer needed since all configuration has used nested option panels since 0.0.16.
- **Legacy curated model presets** (`gemini_flash`/`claude_sonnet`/`gpt_mini`) in the add-on's config helper: the schema has only accepted `custom` since 0.0.18.

### Changed
- `router_ssh.*` (`host`, `user`, `key_path`) schema fields are now correctly optional, matching the panel's "Optional router SSH" description.
- `gateway_bind_mode`/`gateway_auth_mode` descriptions now explicitly state they only take effect when `access_mode` is `custom`.
- Status exporter add-on version fallback aligned to **0.0.39**.

### Added
- **`tool_discord_enabled`** toggle in Tool Bootstrap (default on), matching the existing Telegram toggle — lets you keep a saved Discord bot token without installing/running the bot.

## [0.0.38] - 2026-07-23

### Fixed
- **armv7 CI build**: dropped the GitHub Actions cache export (`cache-to: type=gha`) from the add-on image build. It was failing with `ERROR: not_found` on the long-running armv7 leg (QEMU-emulated compile, ~1h), which canceled the whole buildx solve — including the already-successful image push — and skipped the multi-arch manifest merge. Cache reads (`cache-from`) are kept.
- Status exporter add-on version fallback aligned to **0.0.38**.

## [0.0.37] - 2026-07-23

### Changed
- **Prebuilt images on GHCR**: installs/updates **pull** `ghcr.io/jackalski/hermes-agent-addon:<version>` instead of building the Dockerfile on HAOS (avoids long local builds and npm DNS failures during Supervisor `docker build`).
- Status exporter add-on version fallback aligned to **0.0.37**.

### Fixed
- Dockerfile includes `python3-dev` + native libs (`libffi-dev`, JPEG/zlib) so armv7 CI builds can compile Hermes Python wheels under QEMU (prebuilt wheels cover amd64/aarch64).

### Notes
- First successful GitHub Actions run must publish the package; the GHCR package **`hermes-agent-addon`** must be set to **Public** (Package settings) for anonymous Supervisor pulls.
- Dockerfile remains in-repo and is built by CI (`.github/workflows/build-addon.yml`).

## [0.0.36] - 2026-07-22

### Fixed
- **HAOS Docker build resilience**: npm global installs (`hermes-agent`, raft, agent-browser) now retry on transient DNS failures (`getaddrinfo EAI_AGAIN` against `registry.npmjs.org`) with npm fetch-retries + up to 5 install attempts.
- Dockerfile `BUILD_ARCH` default (`amd64`) to silence `InvalidDefaultArgInFrom` lint (Supervisor still passes the real arch).

### Changed
- Status exporter add-on version fallback aligned to **0.0.36**.

## [0.0.35] - 2026-07-22

### Added
- **Status sensors**: MQTT/`status.json` now expose `gateway_ready` and redacted `last_error`.
- **ntfy panel** (opt-in): sync `NTFY_*` env for push/cron delivery (`ntfy_publish_only` default ON).
- **`lm_studio` provider**: first-run bootstrap as Hermes `custom` + `lm_studio_base_url`.
- **Example no_agent scripts** (`disk-alert.sh`, `morning-heartbeat.sh`) seeded into `/config/.hermes/scripts/` when `seed_example_scripts` is ON.
- DOCS: Assist `X-Hermes-Session-Key`, no_agent cron recipes, Chronos scale-to-zero note (Nous-hosted only — not for HAOS).

### Changed
- Status exporter add-on version fallback aligned to **0.0.35**.

## [0.0.34] - 2026-07-22

### Added
- **Webhooks panel** (opt-in): `WEBHOOK_*` env + `platforms.webhook` bootstrap; optional `ha-alert` **direct-delivery** route to Home Assistant persistent notifications (zero LLM).
- **`hermes-backup-share`**: backup Hermes home to `/share/hermes/backups` (optional `auto_backup_on_start`).
- **`fallback_providers`** bootstrap (entries like `openrouter` or `openrouter/model`) when the Hermes key is missing.
- **`nous_tool_gateway`**: opt-in seed of `use_gateway: true` on web / image_gen / tts / browser.
- **Gateway drain** on stop (`gateway_drain_seconds`, default 15) with best-effort `hermes gateway stop --drain`.
- **Update progress logging**: npm hermes-agent reconcile streams `Update progress [n/3]` lines into add-on logs.

### Changed
- Status exporter add-on version fallback aligned to **0.0.34**.

## [0.0.33] - 2026-07-22

### Added
- **`prefer_supervisor_token`** (default ON): use `SUPERVISOR_TOKEN` for HA API/MCP when no long-lived token is pasted (`hassio_api` + `homeassistant_api` enabled). Supervisor tokens are never written to `/config/secrets/`.
- **`agent_behavior` panel**: bootstrap `approvals.mode`, `agent.reasoning_effort`, and `display.show_reasoning` only when those keys are missing (headless-friendly defaults: smart / medium / ON).
- **`enable_native_ha_platform`** (default OFF): opt-in seed of `platforms.homeassistant` with safe event filters; documents MCP tools vs native gateway events.
- Optional **`ha_system_prompt_hint`** stored with the native HA platform block when platform bootstrap runs.

### Changed
- Timezone default is **`auto`** (detect from Home Assistant Core via Supervisor; fallback `Etc/UTC`) instead of hard-coded `Europe/Sofia`.
- Status exporter add-on version fallback aligned to **0.0.33**.

## [0.0.32] - 2026-07-22

### Changed
- Default upstream **Hermes Agent** pin updated from **0.18.0** to **0.19.0** ([v2026.7.20](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.7.20), "The Quicksilver Release"): Docker image bake, `hermes_agent_version_custom` default, runtime reconcile fallback, and all locale translations.
- Status exporter add-on version fallback aligned to **0.0.32**.

### Notes
- Roadmap remaining: Piper TTS packaging, Automation Blueprints store, privacy.redact_pii UI.

## [0.0.31] - 2026-07-05

### Changed
- Default upstream **Hermes Agent** pin updated from **0.17.0** to **0.18.0** (`v2026.7.1`, "The Judgment Release"): Docker image bake, `hermes_agent_version_custom` default, runtime reconcile fallback, and all locale translations.

## [0.0.30] - 2026-06-22

### Fixed
- **Chat WebSocket failures** (`CONNECTION_REFUSED`, PTY code **1006**): nginx now clears `Origin` when proxying WebSocket upgrades to the loopback `hermes dashboard`. Browsers send the public entry URL as Origin (LAN IP, tunnel hostname, etc.) but the dashboard rejects non-loopback origins on `/api/ws`, `/api/events`, and `/api/pty`. REST `/api/*` was unaffected. Uses standard `$connection_upgrade` map for WebSocket proxying.
- **Open Hermes Web UI link**: removed misleading `?token=` query (gateway auth token ≠ dashboard session token).

## [0.0.29] - 2026-06-14

### Fixed
- **`[raft] raft CLI not found in PATH` log spam** (Hermes 0.17+): image and startup bootstrap now install the canonical **`@botiverse/raft`** npm package (`raft` / `slock` CLI on PATH). Also ensures **`aiohttp`** is available for the optional Raft platform adapter.

## [0.0.28] - 2026-06-14

### Changed
- Default upstream **Hermes Agent** pin updated from **0.16.0** to **0.17.0** (Docker image bake, `hermes_agent_version_custom` default, runtime reconcile fallback).

## [0.0.27] - 2026-06-14

### Fixed
- **Dashboard API routing**: nginx no longer sends all `/api/*` to the Assist API server when `enable_openai_api` is enabled. Dashboard routes (`/api/status`, `/api/sessions`, `/api/pty`, WebSocket chat) now reach the loopback `hermes dashboard` on HTTPS `gateway_port`. Assist API remains on `/v1/` and `/health` (and direct `http://LAN:8642/v1` from HA Core).
- **Status exporter health probe**: probes `/api/status` on `dashboard_internal_port` (loopback dashboard) instead of the gateway WebSocket internal port.

### Changed
- **Single HTTPS Web UI entry**: external TLS is published only on `gateway_port` (default 18789). The second listener on `dashboard_port` (9119) is removed; `dashboard_port` is deprecated as an external alias and only controls the loopback bind offset (`dashboard_port + 1`).
- **Unified naming**: landing page **Open Hermes Web UI**; configuration panel renamed to **Hermes Web UI**; Connection tests regrouped (Test Web UI HTTPS on `gateway_port`).
- Landing page gateway health uses Ingress `./status.json` instead of LAN `/api/status`.

## [0.0.25] - 2026-06-14

### Fixed
- **Add-on version reporting**: the status exporter now reads the live add-on version from `config.yaml` (baked into the image as `/addon_config.yaml`) instead of a hard-coded constant that was stuck at `0.0.19`. The MQTT **Add-on Version** sensor and `status.json` `addon_version` now match the installed version, and MQTT discovery re-publishes once per real version bump (marker `<version>:<prefix>`).
- **Landing page dashboard banner**: in `lan_https` mode with `dashboard_port` equal to `gateway_port`, the page no longer shows the misleading "dashboard is loopback-only" warning — the dashboard is reached via the unified **Open Web UI** button on `gateway_port`. The loopback-only banner now appears only when `access_mode` is not `lan_https`.

## [0.0.24] - 2026-06-14

### Changed
- **Connection tests** are now **one test per Configuration entry** (URL, token, MCP, MQTT broker/auth, dashboard loopback/HTTPS, gateway/remote/HTTPS, Assist API, terminal). The Ingress Web UI groups buttons by configuration panel.

## [0.0.23] - 2026-06-14

### Added
- **Connection tests** on the add-on Web UI (Ingress landing page): buttons for MQTT, HA/MCP, gateway, dashboard, Assist API, and **Run all**. Served via `/test/<name>` (no add-on restart needed for MQTT/HA probes after saving Configuration).
- Configuration panel descriptions now point to Connection tests where applicable (Home Assistant, MQTT, Gateway Access, Hermes Dashboard).

### Changed
- Merged duplicate **HTTPS nginx server blocks** into one `lan_https` listener on `gateway_port` and optional `dashboard_port`.
- Simplified Ingress landing page: unified **Open Web UI** button, optional second port link only when `dashboard_port` differs from `gateway_port`, and trimmed redundant dashboard help text.

### Removed
- Misleading gateway HTTP port check in `gateway_running()` (Hermes 0.16+ gateway has no HTTP listener on `gateway.port`).
- Unused `enable_web_interface` field from status exporter payload.

## [0.0.22] - 2026-06-14

### Added
- **`dashboard_port`** (default **9119**) in the **Hermes Dashboard** panel — the separate `hermes dashboard` admin UI (config, API keys, sessions, logs, skills) now runs on its own configurable port instead of sharing the gateway port.
- Dedicated **HTTPS proxy block** for the dashboard in `lan_https` mode: nginx terminates TLS on `dashboard_port` and proxies to the loopback dashboard. A new **Open Hermes Dashboard** button appears on the Ingress landing page.
- **Dashboard Chat tab:** image installs `ptyprocess` (Hermes `[pty]` extra) and starts `hermes dashboard --tui` when supported, enabling the embedded TUI chat pane over PTY/WebSocket (Node 22 is already in the image for TUI bundle builds).

### Changed
- The `web_interface` panel controls **`hermes dashboard`** auto-start and `dashboard_port` (default 9119). Renamed to **Hermes Dashboard** in all translations.
- In `lan_https`, **both** `gateway_port` (18789) and `dashboard_port` (9119) are nginx HTTPS entry points to the same dashboard loopback process; messaging stays in `hermes gateway run` (no HTTP on `gateway.port`).
- `gateway_running` status detection now probes the gateway over HTTP with a process-check fallback, so it no longer depends on the dashboard.

### Fixed
- Dropped the invalid **`--skip-build`** flag from the `hermes dashboard` launch (not supported by current Hermes), which could prevent the dashboard from starting on 0.16.0.
- **`Invalid Host header` on `dashboard_port`:** nginx now forwards `Host: 127.0.0.1:<internal>` (not the client LAN IP) and omits `X-Forwarded-For` so the dashboard accepts proxied requests and WebSocket chat works.
- **`502 Bad Gateway` on `gateway_port` (18789):** port 18789 again proxies `/` to **`hermes dashboard`** (not `gateway.port`, which has no HTTP listener in Hermes 0.16+). Port **9119** is a second HTTPS entry to the same dashboard.

### Security
- Documented that the Hermes dashboard has **no built-in authentication**; in `lan_https` it is TLS-encrypted on the LAN but still unauthenticated. Disable it or front it with an authenticating proxy if not needed. See `SECURITY.md`.

## [0.0.21] - 2026-06-10

### Added
- **Web Interface** configuration panel: `enable_web_interface` and `auto_start_with_integration` (default **ON**) — starts `hermes dashboard` automatically when the add-on starts in local gateway mode.

## [0.0.20] - 2026-06-10

### Fixed
- MQTT status exporter uses **paho-mqtt Callback API v2** (avoids `DeprecationWarning: Callback API version 1 is deprecated` on paho-mqtt 2.x).

## [0.0.19] - 2026-06-07

### Fixed
- Add-on startup now stamps `/config/.hermes/.install_method` as **docker** so Hermes CLI no longer mis-detects the npm/wheel layout as an unsupported `pip install`.
- MQTT sensor **Auxiliary Title Model** now mirrors the configured **main** `model.provider` / `model.default` as `provider/model` (ignores bootstrapped `auxiliary.title_generation` defaults).

### Changed
- MQTT status exporter uses a **persistent `paho-mqtt` client** (one broker connection per poll cycle instead of one `mosquitto_pub` per message).
- **MQTT discovery is one-shot** — published once per add-on version + topic prefix (marker: `/config/.hermes/.mqtt_discovery_published`). Delete that file to force re-discovery.

## [0.0.18] - 2026-06-07

### Added
- **`default_provider`** dropdown for first-run model bootstrap: Nous Portal, OpenRouter, Google, Anthropic, Ollama Cloud, MiniMax, xAI, OpenAI.
- **`ollama_api_key`** in Provider API Keys (synced as `OLLAMA_API_KEY`).

### Changed
- **`default_model_preset`** is now **custom** only; set your model ID in **`default_model`**.
- Legacy curated presets (`auto`, `gemini_flash`, etc.) are still honored if present in saved options until you save configuration again.

## [0.0.17] - 2026-06-07

### Changed
- User-facing add-on name is now **Hermes Agent Integration** (HA store, Ingress, MQTT device, docs) to distinguish this add-on from upstream Hermes Agent and the separate HA custom integration.

## [0.0.16] - 2026-06-07

### Added
- **`mqtt_settings`** expansion panel: manual **broker host, port, username, password** plus all status-sensor options (enable sensors, discovery, poll interval, topic prefix). Empty host autodetects Mosquitto.
- Logical configuration groups: **`home_assistant`**, **`gateway_access`**, **`mqtt_settings`**, **`router_ssh`**, **`tools_bootstrap`**, **`advanced_settings`**.
- **`addon_log_level`** option (error / warn / info / debug) with unified startup logging (colors + emojis on TTY).
- **`provider_api_keys`** expansion panel in add-on configuration — groups all provider/tool tokens.
- **List-style UI** for `gateway_trusted_proxies` and `gateway_additional_allowed_origins` (add-row like Gateway Environment Variables); trusted proxies validated as IP/CIDR.
- **`hermes_mqtt_resolver.py`** — improved Mosquitto detection (env, supervisor, bashio, host-network loopback fallback).

### Changed
- Expanded **Gateway Trusted Proxies** and **Additional Allowed Origins** configuration help (panel descriptions + per-row `value` field labels, all locales).
- Router SSH keys default to **`/config/keys/router_ssh`** (persistent); legacy `/data/keys/router_ssh` migrated on startup.
- Add-on API keys and HA token **preserve existing `/config/.hermes/.env` values** when options are empty after reinstall (HA secret redaction).
- `terminal_port` and `gateway_port` use **`port`** schema for clearer HA UI defaults.
- Startup logs use **`addon_log.sh`** helpers instead of raw `echo INFO/WARN/ERROR`.
- MQTT broker password persisted under `/config/secrets/mqtt.password` when HA redacts the password field after save.
- `run.sh` reads nested panels with **legacy flat-key fallback** for existing `options.json` files.

### Fixed
- MQTT status sensors retry broker resolution each poll when Mosquitto starts after the add-on.

## [0.0.15] - 2026-06-06

### Fixed
- **Mosquitto / MQTT detection** for HA status sensors: resolve broker via bashio, injected `MQTT_*` env vars, and Supervisor `GET /services/mqtt`; status exporter retries each poll instead of giving up at startup.
- **Docker build** on Debian Bookworm: set `UV_BREAK_SYSTEM_PACKAGES=1` so `uv pip install --system` works with PEP 668 externally-managed Python.

## [0.0.14] - 2026-06-06

### Changed
- **Hermes Agent 0.16.0** ([v2026.6.5](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.6.5)) baked into the image; default add-on config pins **0.16.0** via `hermes_agent_version_preset: custom`.
- Version selector simplified to **`latest`** or **`custom`** (removed legacy 0.15.x / 0.14.0 presets).
- Docker image pins **`starlette>=1.0.1`** (CVE-2026-48710) alongside dashboard deps.
- Docker image runs **`apt-get upgrade`** before installing packages.
- **`uv`** and **`mcp`** (MCP Python SDK) installed **system-wide** at build time; runtime tool bootstrap uses `uv pip install --system` with pip fallback.
- User-installed npm skills persist under **`/config/.node_global`** (`PERSISTENT_NODE_GLOBAL`); add-on bootstrap npm targets **`/usr/local`**.

## [0.0.13] - 2026-06-06

### Fixed
- **Assist API** now binds **`0.0.0.0:8642`** (was loopback-only) so Home Assistant Core can reach it for Extended OpenAI Conversation without trusting the self-signed HTTPS cert on port 18789.

### Changed
- Extended OpenAI Base URL guidance: use **`http://<LAN-IP>:8642/v1`** from HA Core (bearer token still required).

## [0.0.12] - 2026-06-06

### Fixed
- **`enable_openai_api`** now syncs Hermes **`API_SERVER_*`** env vars (`API_SERVER_ENABLED`, `API_SERVER_KEY`, `API_SERVER_PORT`, `API_SERVER_HOST`) so the Assist API server actually starts on port **8642**.
- **`lan_https` nginx** routes `/v1/`, `/health`, and `/api/` to the API server instead of the dashboard (fixes `Method Not Allowed` on `/v1/chat/completions`).

### Changed
- Startup logs Assist API bind status and Extended OpenAI Base URL hint (`https://<LAN-IP>:18789/v1`).

## [0.0.11] - 2026-06-06

### Fixed
- Docker build no longer uses Dockerfile heredocs (unsupported on some Home Assistant Supervisor builders); wheel repair runs via `repair_hermes_wheel.py` instead.

## [0.0.10] - 2026-06-06

### Fixed
- Startup repairs broken **hermes-agent 0.15.2** Python wheel (missing `hermes_cli/dashboard_auth` and `hermes_cli/proxy`; upstream [#34701](https://github.com/NousResearch/hermes-agent/issues/34701)) by copying subpackages from the matching GitHub source tag before starting the dashboard.
- Docker image applies the same wheel repair at build time so `hermes dashboard` works without a first-boot download.

## [0.0.9] - 2026-06-06

### Fixed
- Runtime npm reconcile removes existing image-global `hermes`/`hermes-agent` binaries before reinstall (fixes `EEXIST: file already exists` at `/usr/local/bin/hermes` when pinning a version preset).

## [0.0.8] - 2026-06-05

### Changed
- Gateway runtime now uses the modern **`hermes gateway run`** CLI (with `HERMES_HOME` and `HERMES_GATEWAY_NO_SUPERVISE`) instead of legacy `hermes-agent gateway run`.
- Skills Hub bootstrap uses `hermes skills list`; process detection uses `gateway.pid`, port bind, and `hermes` gateway process patterns.

### Added
- **`hermes_agent_version_preset`** add-on option (`latest`, pinned `0.15.2` / `0.15.1` / `0.14.0`, or `custom`) with runtime npm reconcile on startup.
- Terminal profile exports `HERMES_HOME` for manual `hermes` commands.

### Fixed
- Runtime `hermes-agent` npm reconcile no longer installs into `/config/.node_global` (postinstall pip failed with PEP 668 `externally-managed-environment`); installs use image-global `/usr/local` with `PIP_BREAK_SYSTEM_PACKAGES=1`.
- First boot with `latest` preset seeds the version marker when the image-baked `hermes` CLI is already present (avoids pointless reinstall attempts).
- MCP auto-configure now re-runs when the resolved MCP URL changes (fixes stale `http://127.0.0.1:8123/api/mcp` entries on HAOS; target is `http://supervisor/core/api/mcp`).
- Hermes npm reconcile runs before `/config/.node_global` prefix redirect; uses isolated `NPM_CONFIG_PREFIX=/usr/local` so postinstall pip no longer targets persistent prefix. Failed installs no longer retry every boot when image-baked `hermes` is present.
- Built-in skills sync resolves the real `hermes-agent` npm package path (`/usr/local/lib/node_modules` vs stale `npm root -g` under `/usr/lib`).
- Startup logs an explicit error when `lan_https` dashboard fails to bind the internal port (nginx 502 on the external HTTPS port).
- **`lan_https` 502 fix:** modern Hermes splits messaging (`hermes gateway run`) from the Web UI (`hermes dashboard`); the add-on now starts the dashboard on the internal port nginx proxies to. Image installs `fastapi` + `uvicorn` for dashboard startup.
- HA status exporter probes `/api/status` (dashboard) instead of nonexistent `/api/health`.

## [0.0.7] - 2026-06-05

### Fixed
- Restored **Home Assistant Token** in add-on Configuration UI (`homeassistant_token` was missing from `options` since 0.0.5; schema now uses `password?` for masked input).
- Bootstrap core Hermes tool prerequisites on startup: `HASS_TOKEN`/`HASS_URL` aliases, gateway session env for cronjob/messaging, free `ddgs` web search backend, `edge-tts` for TTS, optional Discord deps, and local Chromium CDP for `browser-cdp`.

## [0.0.6] - 2026-06-05

### Fixed
- Removed deprecated `build.yaml`; base images are set in `Dockerfile` via `BUILD_ARCH` (resolves Supervisor `build.yaml is deprecated` warning).
- Aligned `claude_sonnet` model preset with Anthropic provider default (`claude-sonnet-4-6`).
- Setup readiness and `api_key_configured` status now require a main LLM provider key (not auxiliary tokens such as Discord/GitHub).
- Removed stray DEBUG startup log lines for terminal options.
- Status exporter process is stopped cleanly on add-on shutdown (no orphaned background loop).

### Changed
- Add-on marked **Experimental** (`stage: experimental`) in the Home Assistant add-on store.

## [0.0.5] - 2026-06-05

### Added
- First-run bootstrap: sync API keys to `/config/.hermes/.env`, auto-configure main model, Docker-safe browser settings, timezone, and Home Assistant URL/token env vars.
- `setup_profile` preset (`home_assistant`, `general`, `advanced`) with centralized profile manifest for access mode and MCP behavior.
- `default_model_preset` curated dropdown (`auto`, `gemini_flash`, `claude_sonnet`, `gpt_mini`, `custom`) plus optional `default_model` for custom IDs.
- Auxiliary `title_generation` bootstrap (cheap flash model) for `home_assistant` and `general` profiles on first run.
- Router SSH env sync (`TERMINAL_SSH_HOST`, `TERMINAL_SSH_USER`, `TERMINAL_SSH_KEY`) when router options are set.
- Optional web search env sync: `firecrawl_api_key`, `searxng_url`.
- Landing page **Setup status** checklist (API key, model, MCP, Assist API).
- Web terminal sources `/config/.hermes/.env` automatically for `hermes onboard` / `hermes model`.
- `hass_url` added to configuration schema.
- **Home Assistant status sensors**: background exporter publishes gateway health, model/provider, setup readiness, token usage, and disk metrics via MQTT discovery (when Mosquitto is installed) and a safe `/status.json` snapshot on Ingress (`/share/hermes/status.json`).
- New options: `enable_ha_status_sensors`, `publish_mqtt_discovery`, `status_poll_interval_seconds`, `mqtt_state_prefix`.
- Home Assistant instance autodetection: empty/local `hass_url` resolves to supervisor MCP + loopback API on HAOS; optional reachability check when a token is set.
- Cloudflared: default `gateway_trusted_proxies` when using `lan_reverse_proxy`; startup hints recommend `lan_https` + `noTLSVerify` for Cloudflare Tunnel.
- Documentation consolidated into a single streamlined `DOCS.md`.

### Changed
- Default `access_mode` is now `lan_https` (was `custom`).
- `setup_profile: home_assistant` auto-enables MCP when `homeassistant_token` is set.
- MCP URL respects `hass_url` when not running under the HA supervisor proxy.
- Gateway LAN URL hint logged and shown on landing page when `gateway_public_url` is empty.

## [0.0.4] - 2026-05-28

### Fixed
- Auto-configure MCP now writes Home Assistant into Hermes built-in `mcp_servers` (`/config/.hermes/config.yaml`) instead of using `mcporter`.

### Changed
- MCP token for auto-configure is stored in `/config/.hermes/.env` as `HOMEASSISTANT_TOKEN` and referenced from MCP headers.

## [0.0.3] - 2026-05-28

### Changed
- Replaced `DOCS.md` with a new canonical GitHub-facing documentation baseline.
- Aligned release metadata for the patch release (`0.0.3`) in add-on configuration.
- Updated MCP documentation and UI strings to use Hermes built-in MCP (`mcp_servers`, `/reload-mcp`) instead of `mcporter`.

### Notes
- This release is intended as a public-facing documentation/reset patch for repository hygiene.

## [0.0.2] - 2026-05-28

### Added
- Added add-on configuration options for optional tool bootstrap and provider/API tokens.
- Added startup bootstrap for selected tools:
  - Telegram dependency check/install (`python-telegram-bot`)
  - Browser dependency check/install (`agent-browser`)
  - Skills Hub one-time directory initialization.
- Added Cloudflare Tunnel guidance using Home Assistant `Cloudflared` add-on in docs.

### Changed
- Updated image build to install `agent-browser` globally.
- Updated user-facing command examples to prefer `hermes ...` command style in docs and landing tips.

## [0.0.1] - 2026-05-27

### Project Baseline
- Initial baseline release for this repository under the Hermes Agent naming.
