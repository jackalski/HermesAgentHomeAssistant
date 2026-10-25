#!/usr/bin/env bash
# Shared Hermes Agent GitHub-source install helpers (Dockerfile + run.sh).
# Safe under set -euo pipefail when sourced.

HERMES_SOURCE_REPO="${HERMES_SOURCE_REPO:-https://github.com/NousResearch/hermes-agent}"
HERMES_SOURCE_ROOT="${HERMES_SOURCE_ROOT:-/opt/hermes-agent}"
HERMES_BAKED_WEB_DIST="${HERMES_BAKED_WEB_DIST:-/opt/hermes-agent/web_dist}"
HERMES_IMAGE_SKILLS_DIR="${HERMES_IMAGE_SKILLS_DIR:-/opt/hermes-agent/skills}"
HERMES_BAKED_TAG_FILE="${HERMES_BAKED_TAG_FILE:-/opt/hermes-agent/.baked-tag}"
HERMES_VERSION_TAGS_FILE="${HERMES_VERSION_TAGS_FILE:-/opt/hermes-agent/version-tags.tsv}"
# Hermes 0.22+ gates nearly every core dependency on python_version >= 3.14 (3.11 is only an
# updater bridge), so it must run in a uv-managed 3.14 venv, never the Debian system Python.
HERMES_VENV="${HERMES_VENV:-/opt/hermes-venv}"
HERMES_PYTHON_VERSION="${HERMES_PYTHON_VERSION:-3.14}"
HERMES_PYTHON="${HERMES_VENV}/bin/python"

# Fallback logging when addon_log.sh is not sourced (Docker build).
if ! command -v log_info >/dev/null 2>&1; then
  log_info() { printf 'INFO: %s\n' "$*" >&2; }
fi
if ! command -v log_warn >/dev/null 2>&1; then
  log_warn() { printf 'WARN: %s\n' "$*" >&2; }
fi
if ! command -v log_error >/dev/null 2>&1; then
  log_error() { printf 'ERROR: %s\n' "$*" >&2; }
fi

hermes_map_version_to_tag() {
  local value="$1"
  local map_file line semver tag

  if [ -z "$value" ]; then
    return 1
  fi

  # Already a GitHub release tag: legacy CalVer (v2026.8.3) or SemVer since 0.21.x (v0.22.5).
  if printf '%s' "$value" | grep -Eq '^v(20[0-9]{2}|[0-9]{1,2})\.[0-9]+\.[0-9]+$'; then
    printf '%s\n' "$value"
    return 0
  fi

  map_file="$HERMES_VERSION_TAGS_FILE"
  if [ ! -f "$map_file" ]; then
    # Build-context / local checkout fallback.
    if [ -f "/version-tags.tsv" ]; then
      map_file="/version-tags.tsv"
    elif [ -f "$(dirname "${BASH_SOURCE[0]}")/version-tags.tsv" ]; then
      map_file="$(dirname "${BASH_SOURCE[0]}")/version-tags.tsv"
    else
      return 1
    fi
  fi

  while IFS= read -r line || [ -n "$line" ]; do
    [ -z "$line" ] && continue
    case "$line" in
      \#*) continue ;;
    esac
    semver="$(printf '%s' "$line" | awk -F'\t' '{print $1}')"
    tag="$(printf '%s' "$line" | awk -F'\t' '{print $2}')"
    if [ "$semver" = "$value" ] && [ -n "$tag" ]; then
      printf '%s\n' "$tag"
      return 0
    fi
  done < "$map_file"
  return 1
}

hermes_resolve_latest_tag() {
  local tag
  tag="$(
    curl -fsSL "https://api.github.com/repos/NousResearch/hermes-agent/releases/latest" \
      | jq -r '.tag_name // empty' 2>/dev/null || true
  )"
  if [ -z "$tag" ] || [ "$tag" = "null" ]; then
    return 1
  fi
  printf '%s\n' "$tag"
  return 0
}

hermes_download_source() {
  local tag="$1"
  local dest_dir="$2"
  local tag_sans_v archive tmp extract_root top

  if [ -z "$tag" ] || [ -z "$dest_dir" ]; then
    return 1
  fi

  tag_sans_v="${tag#v}"
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/hermes-src.XXXXXX")"
  archive="${tmp}/src.tar.gz"
  extract_root="${tmp}/extract"
  mkdir -p "$extract_root"

  if ! curl -fsSL "${HERMES_SOURCE_REPO}/archive/refs/tags/${tag}.tar.gz" -o "$archive"; then
    rm -rf "$tmp"
    return 1
  fi
  if ! tar -xzf "$archive" -C "$extract_root"; then
    rm -rf "$tmp"
    return 1
  fi

  top="${extract_root}/hermes-agent-${tag_sans_v}"
  if [ ! -d "$top" ]; then
    # Fallback: first directory under extract_root.
    top="$(find "$extract_root" -mindepth 1 -maxdepth 1 -type d | head -1 || true)"
  fi
  if [ -z "$top" ] || [ ! -d "$top" ]; then
    rm -rf "$tmp"
    return 1
  fi

  rm -rf "$dest_dir"
  mkdir -p "$(dirname "$dest_dir")"
  mv "$top" "$dest_dir"
  rm -rf "$tmp"
  return 0
}

# Create (or reuse) the uv-managed Python 3.14 venv that hosts Hermes.
hermes_ensure_venv() {
  if [ -x "$HERMES_PYTHON" ] \
    && "$HERMES_PYTHON" -c "import sys; sys.exit(0 if sys.version_info[:2] == tuple(map(int, '${HERMES_PYTHON_VERSION}'.split('.'))) else 1)" 2>/dev/null; then
    return 0
  fi
  log_info "Creating Python ${HERMES_PYTHON_VERSION} venv at ${HERMES_VENV} ..."
  rm -rf "$HERMES_VENV"
  UV_SYSTEM_PYTHON=0 uv venv --python "$HERMES_PYTHON_VERSION" "$HERMES_VENV" >&2
}

hermes_install_from_source() {
  local tag="$1"
  local src_dir="${HERMES_SOURCE_ROOT}/src"

  if [ -z "$tag" ]; then
    log_error "Failed to install Hermes Agent from GitHub tag (empty tag)."
    return 1
  fi

  log_info "Installing Hermes Agent from GitHub tag ${tag} ..."

  # Clear prior npm-bridge binaries so console scripts land cleanly.
  rm -rf /usr/local/lib/node_modules/hermes-agent 2>/dev/null || true
  rm -f /usr/local/bin/hermes /usr/local/bin/hermes-agent 2>/dev/null || true
  rm -rf /config/.node_global/lib/node_modules/hermes-agent 2>/dev/null || true
  rm -f /config/.node_global/bin/hermes /config/.node_global/bin/hermes-agent 2>/dev/null || true

  mkdir -p "$HERMES_SOURCE_ROOT"

  if ! hermes_download_source "$tag" "$src_dir"; then
    log_error "Failed to install Hermes Agent from GitHub tag ${tag}."
    return 1
  fi

  if [ ! -f "${src_dir}/pyproject.toml" ]; then
    log_error "Failed to install Hermes Agent from GitHub tag ${tag}."
    rm -rf "$src_dir"
    return 1
  fi

  # [all] no longer bundles messaging/TTS (lazy-installed upstream since 0.22); request them
  # up front so the read-only image does not depend on first-use installs. Older tags
  # lack some extras, so fall back to plain [all].
  if ! hermes_ensure_venv; then
    log_error "Failed to install Hermes Agent from GitHub tag ${tag} (no Python ${HERMES_PYTHON_VERSION} venv)."
    rm -rf "$src_dir"
    return 1
  fi

  # [all] no longer bundles messaging/TTS (lazy-installed upstream since 0.22); request them
  # up front so the image does not depend on first-use installs. Older tags
  # lack some extras, so fall back to plain [all].
  # Upstream resolves with [tool.uv] override-dependencies (e.g. Pillow 13 over browser-harness'
  # exact pillow==12.3.0 pin). `uv pip` ignores that table, so replay it as an overrides file.
  local overrides_file="${src_dir}/.addon-uv-overrides.txt"
  python3 - "${src_dir}/pyproject.toml" > "$overrides_file" <<'PY' || : > "$overrides_file"
import sys, tomllib
with open(sys.argv[1], "rb") as fh:
    data = tomllib.load(fh)
for line in data.get("tool", {}).get("uv", {}).get("override-dependencies", []):
    print(line)
PY
  if ! uv pip install --python "$HERMES_PYTHON" --no-cache --overrides "$overrides_file" -e "${src_dir}[all,messaging,tts-premium]" \
    && ! uv pip install --python "$HERMES_PYTHON" --no-cache --overrides "$overrides_file" -e "${src_dir}[all]"; then
    log_error "Failed to install Hermes Agent from GitHub tag ${tag}."
    rm -rf "$src_dir"
    return 1
  fi

  # Extras the add-on exposes that are not exact-pinned by Hermes (installed after so
  # Hermes pins win). Best-effort.
  uv pip install --python "$HERMES_PYTHON" --no-cache \
    "python-telegram-bot[webhooks]>=22.7" edge-tts ddgs "discord.py[voice]>=2.7.1" \
    "brotlicffi>=1.2.0.1" >/dev/null 2>&1 \
    || log_warn "Optional Python extras (telegram/discord/edge-tts/ddgs) failed to install."

  # Expose the venv console scripts on the default PATH (ttyd, s6 and cron shells).
  local script
  for script in hermes hermes-agent hermes-acp; do
    if [ -x "${HERMES_VENV}/bin/${script}" ]; then
      ln -sf "${HERMES_VENV}/bin/${script}" "/usr/local/bin/${script}"
    fi
  done

  if [ -d "${src_dir}/skills" ]; then
    rm -rf "${HERMES_IMAGE_SKILLS_DIR}"
    mkdir -p "$(dirname "${HERMES_IMAGE_SKILLS_DIR}")"
    cp -a "${src_dir}/skills" "${HERMES_IMAGE_SKILLS_DIR}"
  else
    log_warn "Source tree for ${tag} has no skills/ directory."
  fi

  # Keep ${src_dir}: upstream forbids non-editable wheels, so the install is
  # editable and must retain the GitHub checkout on disk.

  if ! hermes --version >/dev/null 2>&1; then
    log_error "Hermes Agent ${tag} installed but 'hermes --version' fails:"
    hermes --version 2>&1 | tail -5 >&2 || true
    return 1
  fi

  log_info "Hermes Agent installed from source (${tag})."
  return 0
}

# Hermes 0.22+ ships the Home Assistant gateway platform as a catalog plugin (the
# hermes-agent[homeassistant] extra was removed). Plugins live in HERMES_HOME, which is
# the persistent /config volume, so this runs at startup rather than at image build.
hermes_ensure_homeassistant_plugin() {
  if ! hermes plugins --help >/dev/null 2>&1; then
    return 0
  fi
  if hermes plugins list 2>/dev/null | grep -qi 'homeassistant'; then
    return 0
  fi
  log_info "Installing Hermes homeassistant plugin (required for the HA gateway platform) ..."
  if timeout 180 hermes plugins install homeassistant </dev/null >/dev/null 2>&1; then
    log_info "Hermes homeassistant plugin installed."
  else
    log_warn "Could not install the Hermes homeassistant plugin; run 'hermes plugins install homeassistant' in the terminal."
  fi
  return 0
}
