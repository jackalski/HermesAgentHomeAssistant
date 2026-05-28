# Changelog

All notable changes to the Hermes Agent Home Assistant Add-on are documented in this file.

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

### Attribution And Recognition
- This project is based on the original and excellent work from:
  - **techartdev/OpenClawHomeAssistant**
  - Repository: <https://github.com/techartdev/OpenClawHomeAssistant>
  - Commit history: <https://github.com/techartdev/OpenClawHomeAssistant/commits/main>
- Full recognition and thanks to the original maintainers and contributors for building and open-sourcing the foundation this project extends.
