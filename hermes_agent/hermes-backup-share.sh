#!/usr/bin/env bash
# Backup Hermes HERMES_HOME into /share/hermes/backups (visible from HAOS share).
set -euo pipefail

BACKUP_DIR="${HERMES_BACKUP_DIR:-/share/hermes/backups}"
HERMES_HOME_DIR="${HERMES_HOME:-/config/.hermes}"
mkdir -p "$BACKUP_DIR"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
mode="full"
if [ "${1:-}" = "--quick" ] || [ "${1:-}" = "-q" ]; then
  mode="quick"
fi

if ! command -v hermes >/dev/null 2>&1; then
  echo "ERROR: hermes CLI not found" >&2
  exit 1
fi

if [ "$mode" = "quick" ]; then
  out="${BACKUP_DIR}/hermes-quick-${ts}.zip"
  echo "Creating quick Hermes backup → ${out}"
  # Prefer upstream --quick when available; fall back to full with -o.
  if hermes backup --help 2>&1 | grep -q -- '--quick'; then
    hermes backup --quick -o "$out"
  else
    hermes backup -o "$out"
  fi
else
  out="${BACKUP_DIR}/hermes-backup-${ts}.zip"
  echo "Creating full Hermes backup → ${out}"
  hermes backup -o "$out"
fi

echo "Backup written: ${out}"
echo "Restore: hermes import ${out} --force"
ls -lh "$out" 2>/dev/null || true
