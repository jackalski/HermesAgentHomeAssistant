# Hermes Agent Integration – Home Assistant Add-on

Run **Hermes Agent** (upstream AI platform) inside **Home Assistant OS (HAOS)** via this add-on. Marked **Experimental** in the HA add-on store — expect breaking changes between releases.

Companion custom integration (chat card / voice): [HermesAgentHomeAssistantIntegration](https://github.com/jackalski/HermesAgentHomeAssistantIntegration)

Releases ship as **prebuilt multi-arch Docker images** on GHCR (`ghcr.io/jackalski/hermes-agent-addon`) — HAOS pulls the image instead of compiling on the device.

> Upstream rename history (FYI): clawdbot → moltbot → **hermes-agent**.

## Install

Click the button to open the add add-on repository dialog on your Home Assistant instance:

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fjackalski%2FHermesAgentHomeAssistant)

Or add the repository manually:

1. Home Assistant → **Settings → Add-ons → Add-on store**
2. **⋮ → Repositories**
3. Add `https://github.com/jackalski/HermesAgentHomeAssistant`
4. Install **Hermes Agent Integration** and start it

### After install (minimum config)

In **Settings → Add-ons → Hermes Agent Integration → Configuration**:

- `setup_profile`: `home_assistant` (default)
- A provider API key (e.g. OpenRouter)
- `homeassistant_token`: long-lived HA token (for MCP)
- Leave `hass_url` empty on HAOS (autodetected)

Restart the add-on. Full walkthrough: [Quick start in DOCS.md](DOCS.md#quick-start-recommended). Read [SECURITY.md](SECURITY.md) before enabling remote access.

### Optional next steps

- **MQTT status sensors** + importable usage dashboard under `/share/hermes/ha/` (requires Mosquitto; dashboard needs HACS **Mushroom**, **card-mod**, and **apexcharts-card** — see [DOCS.md](DOCS.md#usage-dashboard-home-assistant))
- **Assist / chat**: companion [Hermes Agent integration](https://github.com/jackalski/HermesAgentHomeAssistantIntegration) via HACS, or [Extended OpenAI Conversation](https://github.com/jekalmin/extended_openai_conversation)

## Key Features

- **AI Gateway** — Hermes Agent server with chat, skills, and automation capabilities
- **Web Terminal** — browser-based terminal embedded in Home Assistant
- **Assist Pipeline** — use Hermes Agent as a conversation agent via the OpenAI-compatible API
- **HA Status Sensors** — MQTT discovery (with Mosquitto) plus Ingress `/status.json` for model, provider, usage/cost breakdowns, overhead proxies, and gateway health; optional importable Lovelace usage dashboard under `/share/hermes/ha/`
- **Browser Automation** — Chromium included for web scraping and automation skills
- **Proxy Support** — optional outbound `http_proxy` setting for HTTP/HTTPS traffic
- **Cloudflare Tunnel Ready** — works with Home Assistant `Cloudflared` add-on for secure remote HTTPS access
- **Persistent Storage** — skills, config, and workspace survive add-on updates
- **Bundled Tools** — git, vim, nano, bat, fd, ripgrep, curl, jq, python3, pnpm, Homebrew

## Supported Architectures

| Architecture | Supported |
|---|---|
| amd64 | ✅ |
| aarch64 (RPi 4/5) | ✅ |
| armv7 (RPi 3) | ❌ (dropped in 0.1.0 — Hermes 0.20 requires Node 26) |

## Documentation

- **[Full documentation →](DOCS.md)** — installation, configuration, use cases, troubleshooting, and more
- **[Security Risks & Disclaimer →](SECURITY.md)** — important risks to understand before using this add-on

## Credits

- This project is based on the original `techartdev/OpenClawHomeAssistant` work.
- Original repository: [https://github.com/techartdev/OpenClawHomeAssistant](https://github.com/techartdev/OpenClawHomeAssistant)
- Original commit history: [https://github.com/techartdev/OpenClawHomeAssistant/commits/main](https://github.com/techartdev/OpenClawHomeAssistant/commits/main)
- Full recognition and thanks to the original maintainers and contributors.
