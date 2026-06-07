# Repository Guidelines

## Project Scope

This repository builds the **Hermes Agent Integration** Home Assistant add-on.
The add-on packages upstream Hermes Agent + nginx + ttyd and manages startup/configuration glue.

## Architecture at a Glance

- Add-on root metadata/docs:
  - `README.md`
  - `DOCS.md`
  - `SECURITY.md`
  - `repository.yaml`
- Runtime implementation (all add-on behavior lives here):
  - `hermes_agent/run.sh` (PID 1 orchestrator)
  - `hermes_agent/hermes_config_helper.py` (safe JSON config edits)
  - `hermes_agent/render_nginx.py` (template rendering)
  - `hermes_agent/nginx.conf.tpl`
  - `hermes_agent/landing.html.tpl`
  - `hermes_agent/config.yaml` (HA options + schema)
  - `hermes_agent/translations/*.yaml` (all locale UI strings)
  - `hermes_agent/Dockerfile`
  - `hermes_agent/CHANGELOG.md`

## Core Rules

- Fix root causes, not symptoms.
- Keep edits surgical; do not refactor unrelated code.
- Never introduce insecure defaults.
- Never log secrets or auth tokens.
- Keep behavior backward-compatible unless the change explicitly requires a migration.

## Add-on Config Coupling Rules (Critical)

When adding/changing any add-on option, update **all** of the following in one change:

1. `hermes_agent/config.yaml`
   - `options:` default
   - `schema:` validation entry
   - comments/help text
2. `hermes_agent/translations/en.yaml`
3. `hermes_agent/translations/bg.yaml`
4. `hermes_agent/translations/de.yaml`
5. `hermes_agent/translations/es.yaml`
6. `hermes_agent/translations/pl.yaml`
7. `hermes_agent/translations/pt-BR.yaml`
8. `DOCS.md` configuration reference / troubleshooting if user-facing
9. `hermes_agent/CHANGELOG.md`

If any of these are skipped, the UX becomes inconsistent in HA.

## Runtime Safety Rules

- `run.sh` runs with `set -euo pipefail`; avoid constructs that fail unexpectedly under `set -e`.
- Validate all user-provided values from `/data/options.json` before injecting into shell/nginx/hermes-agent config.
- Keep `run.sh` idempotent on restart (multiple starts must not corrupt state).
- Treat `/config/` as persistent state; never wipe user data unless explicitly requested.

## Gateway/Auth/Security Rules

- Hermes Agent v2026.2.22+ redacts sensitive values in `hermes config show`.
  - For token retrieval guidance, prefer: `jq -r '.gateway.auth.token' /config/.hermes/hermes.json`.
- `trusted-proxy` mode may reject direct local CLI WS calls (`trusted_proxy_user_missing`); document this clearly instead of hiding it.
- For `lan_https` certificate logic, keep SAN generation deterministic and regeneration-triggered on SAN/IP changes.

## Template Coupling Rules

- If adding placeholders in `landing.html.tpl` or `nginx.conf.tpl`, update `render_nginx.py` in the same change.
- If landing-page guidance changes (commands/errors), sync corresponding troubleshooting text in `DOCS.md`.

## Versioning and Changelog

- User-visible changes should update:
  - `hermes_agent/CHANGELOG.md`
  - `hermes_agent/config.yaml` version
- Keep changelog entries user-facing and action-oriented.

## Coding Style

- Shell: POSIX-friendly Bash, explicit quoting, descriptive variable names.
- Python: small focused helpers, explicit error handling, no hidden side effects.
- YAML/Markdown: preserve existing style and structure.
- Avoid adding dependencies unless necessary.

## Validation Checklist (Run After Relevant Changes)

From repo root:

```sh
bash -n hermes_agent/run.sh
python3 -m py_compile hermes_agent/hermes_config_helper.py
python3 -m py_compile hermes_agent/render_nginx.py
```

For option changes:
- verify `config.yaml` option + schema + all translations exist
- verify `DOCS.md` matches current behavior

For startup/auth/proxy/cert changes:
- verify log messages remain clear and actionable
- verify `landing.html.tpl` instructions match actual commands

## Commit Scope

- Group related changes only.
- Do not include unrelated formatting churn.
- Do not edit generated/cache folders (`__pycache__`, temporary outputs).
