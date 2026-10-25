#!/usr/bin/env bash
# slow.sh GLOB : slowest logged moves across bot logs (runs/<GLOB>/*.log)
cd ~/cw
grep -h slow runs/$1/*.log | sed -E 's/.*update=([0-9.]+)ms decide=([0-9.]+)ms (.*)/\2 \1 \3/' | sort -rn | head -${2:-25}
