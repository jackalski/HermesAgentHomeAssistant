# Changelog

All notable changes to the Hermes Agent Home Assistant Add-on are documented in this file.

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
