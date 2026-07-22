#!/usr/bin/env bash
# Example no_agent cron script: morning heartbeat (always emits a short line).
# Prefer deliver=homeassistant or ntfy. Schedule with:
#   hermes cron create "0 8 * * *" --no-agent --script morning-heartbeat.sh --deliver homeassistant --name morning-heartbeat
echo "Hermes morning heartbeat ($(date -u +%Y-%m-%dT%H:%MZ)) — gateway is up."
