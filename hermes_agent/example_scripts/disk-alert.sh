#!/usr/bin/env bash
# Example no_agent cron script: alert when root filesystem is >= 90% full.
# Empty stdout = silent tick. Schedule with:
#   hermes cron create "*/15 * * * *" --no-agent --script disk-alert.sh --deliver homeassistant --name disk-alert
THRESHOLD=90
df -P / 2>/dev/null | awk -v t="$THRESHOLD" '
  NR > 1 {
    gsub(/%/, "", $5)
    if ($5+0 >= t) {
      printf "Hermes disk alert: / is %s%% full\n", $5
    }
  }
'
