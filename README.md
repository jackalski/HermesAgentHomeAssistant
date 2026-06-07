# Hermes Agent Integration – Home Assistant Add-on

### Hermes Agent Home Assistant integration is available now!  https://github.com/jackalski/HermesAgentHomeAssistantIntegration

This repository contains the **Hermes Agent Integration** Home Assistant add-on, which runs **Hermes Agent** (upstream AI platform) inside **Home Assistant OS (HAOS)**. The add-on is currently marked **Experimental** in the HA add-on store.

> Upstream rename history (FYI): clawdbot → moltbot → **hermes-agent**.

## Key Features

- **AI Gateway** — Hermes Agent server with chat, skills, and automation capabilities
- **Web Terminal** — browser-based terminal embedded in Home Assistant
- **Assist Pipeline** — use Hermes Agent as a conversation agent via the OpenAI-compatible API
- **HA Status Sensors** — MQTT discovery (with Mosquitto) plus Ingress `/status.json` for model, provider, usage, and gateway health
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
| armv7 (RPi 3) | ✅ |

## Documentation

- **[Full documentation →](DOCS.md)** — installation, configuration, use cases, troubleshooting, and more
- **[Security Risks & Disclaimer →](SECURITY.md)** — important risks to understand before using this add-on

## Credits

- This project is based on the original `techartdev/OpenClawHomeAssistant` work.
- Original repository: [https://github.com/techartdev/OpenClawHomeAssistant](https://github.com/techartdev/OpenClawHomeAssistant)
- Original commit history: [https://github.com/techartdev/OpenClawHomeAssistant/commits/main](https://github.com/techartdev/OpenClawHomeAssistant/commits/main)
- Full recognition and thanks to the original maintainers and contributors.

## Install

1. Home Assistant → **Settings → Add-ons → Add-on store**
2. **⋮ → Repositories**
3. Add this repo:
   - `https://github.com/jackalski/HermesAgentHomeAssistant`
4. Install **Hermes Agent Integration**

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=jackalski/HermesAgentHomeAssistant&type=date&legend=top-left)](https://www.star-history.com/#jackalski/HermesAgentHomeAssistant&type=date&legend=top-left)
