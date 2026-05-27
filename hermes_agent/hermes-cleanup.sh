#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# hermes-cleanup — Disk space monitor & cleanup helper for Hermes Agent
# Run from the add-on terminal:  hermes-cleanup
# ──────────────────────────────────────────────────────────────
set -euo pipefail

BOLD="\033[1m"
RED="\033[91m"
GREEN="\033[92m"
YELLOW="\033[93m"
CYAN="\033[96m"
RESET="\033[0m"

echo -e "${BOLD}${CYAN}═══════════════════════════════════════════${RESET}"
echo -e "${BOLD}${CYAN}  Hermes Agent Disk Space Monitor & Cleanup${RESET}"
echo -e "${BOLD}${CYAN}═══════════════════════════════════════════${RESET}"
echo ""

DATA_MOUNT="/config"
if df -h "$DATA_MOUNT" >/dev/null 2>&1; then
  DISK_TOTAL=$(df -h "$DATA_MOUNT" | awk 'NR==2{print $2}')
  DISK_USED=$(df -h "$DATA_MOUNT" | awk 'NR==2{print $3}')
  DISK_AVAIL=$(df -h "$DATA_MOUNT" | awk 'NR==2{print $4}')
  DISK_PCT=$(df -h "$DATA_MOUNT" | awk 'NR==2{print $5}')
  DISK_PCT_NUM=${DISK_PCT//%/}

  echo -e "${BOLD}Disk usage (data partition):${RESET}"
  echo -e "  Total:     ${DISK_TOTAL}"
  echo -e "  Used:      ${DISK_USED} (${DISK_PCT})"
  echo -e "  Available: ${DISK_AVAIL}"
  echo ""

  if [ "$DISK_PCT_NUM" -ge 90 ]; then
    echo -e "${RED}${BOLD}⚠  CRITICAL: Disk is ${DISK_PCT} full!${RESET}"
    echo -e "${RED}   Add-on updates and Docker builds may fail.${RESET}"
    echo ""
  elif [ "$DISK_PCT_NUM" -ge 75 ]; then
    echo -e "${YELLOW}${BOLD}⚠  WARNING: Disk is ${DISK_PCT} full.${RESET}"
    echo -e "${YELLOW}   Consider cleaning up to avoid future build failures.${RESET}"
    echo ""
  else
    echo -e "${GREEN}✓ Disk usage looks healthy.${RESET}"
    echo ""
  fi
fi

echo -e "${BOLD}Add-on cache sizes:${RESET}"

show_size() {
  local label="$1" path="$2"
  if [ -d "$path" ]; then
    local size
    size=$(du -sh "$path" 2>/dev/null | cut -f1)
    printf "  %-30s %s\n" "$label" "$size"
  fi
}

show_size "npm cache" "/config/.npm"
show_size "npm global packages" "/config/.node_global"
show_size "pnpm store" "/config/.node_global/pnpm"
show_size "Hermes config + skills" "/config/.hermes"
show_size "Homebrew" "/config/.linuxbrew"
show_size "Agent workspace" "/config/hermesd"
show_size "Python __pycache__" "/config/.hermes/__pycache__"
show_size "Temp files (/tmp)" "/tmp"
echo ""

echo -e "${BOLD}What can be cleaned from inside the add-on:${RESET}"
echo "  1) npm cache              (safe — rebuilds on demand)"
echo "  2) pnpm store cache       (safe — rebuilds on demand)"
echo "  3) Python __pycache__     (safe — regenerated automatically)"
echo "  4) /tmp files             (safe — transient data)"
echo "  5) All of the above"
echo "  6) Show Docker prune commands (must run from HA host SSH)"
echo "  q) Quit"
echo ""
read -r -p "Choose [1-6/q]: " choice

cleanup_npm() { npm cache clean --force 2>/dev/null || true; rm -rf /config/.npm/_cacache 2>/dev/null || true; }
cleanup_pnpm() { pnpm store prune 2>/dev/null || true; }
cleanup_pycache() { find /config -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true; }
cleanup_tmp() { rm -rf /tmp/* 2>/dev/null || true; }
show_docker_commands() {
  echo "docker image prune -a"
  echo "docker builder prune -a"
  echo "docker system df"
}

case "${choice:-q}" in
  1) cleanup_npm ;;
  2) cleanup_pnpm ;;
  3) cleanup_pycache ;;
  4) cleanup_tmp ;;
  5) cleanup_npm; cleanup_pnpm; cleanup_pycache; cleanup_tmp ;;
  6) show_docker_commands ;;
  q|Q) echo "Bye." ;;
  *) echo "Unknown option." ;;
esac

echo ""
if df -h "$DATA_MOUNT" >/dev/null 2>&1; then
  DISK_AVAIL_NOW=$(df -h "$DATA_MOUNT" | awk 'NR==2{print $4}')
  DISK_PCT_NOW=$(df -h "$DATA_MOUNT" | awk 'NR==2{print $5}')
  echo -e "${BOLD}Disk now: ${DISK_PCT_NOW} used, ${DISK_AVAIL_NOW} available${RESET}"
fi
