# Changelog

All notable changes to the Hermes Agent Home Assistant Add-on are documented in this file.

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
- Add-on marked as **Experimental** (`stage: experimental`) in the Home Assistant add-on store.
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
