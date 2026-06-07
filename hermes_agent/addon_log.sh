#!/usr/bin/env bash
# Unified add-on logging (colors + emojis when stderr is a TTY).
# Levels: error < warn < info < debug

ADDON_LOG_LEVEL="${ADDON_LOG_LEVEL:-info}"

_addon_log_level_num() {
  case "${1,,}" in
    error) echo 0 ;;
    warn|warning) echo 1 ;;
    info) echo 2 ;;
    debug|trace) echo 3 ;;
    *) echo 2 ;;
  esac
}

_addon_log_should_emit() {
  local want="$1"
  local current
  current="$(_addon_log_level_num "$ADDON_LOG_LEVEL")"
  want="$(_addon_log_level_num "$want")"
  [ "$want" -le "$current" ]
}

_addon_log_emit() {
  local level="$1"
  local emoji="$2"
  local color="$3"
  shift 3
  if ! _addon_log_should_emit "$level"; then
    return 0
  fi
  if [ -t 2 ]; then
    printf '%b%s %s%b\n' "$color" "$emoji" "$*" '\033[0m' >&2
  else
    printf '%s %s\n' "$emoji" "$*" >&2
  fi
}

log_error() { _addon_log_emit error '❌' '\033[1;31m' "$@"; }
log_warn()  { _addon_log_emit warn  '⚠️ ' '\033[1;33m' "$@"; }
log_info()  { _addon_log_emit info  'ℹ️ ' '\033[1;36m' "$@"; }
log_ok()    { _addon_log_emit info  '✅' '\033[1;32m' "$@"; }
log_debug() { _addon_log_emit debug '🔍' '\033[0;90m' "$@"; }
