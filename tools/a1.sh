#!/usr/bin/env bash
# PinkiSaanp vs built-in bots, plus variant copies for asymmetric self-play.
cd ~/cw
python3 /mnt/e/Projects/Agent_Showdown/tools/arena.py --sync \
  --variant 'PinkiB={"seed": 2, "max_leg": 30}' \
  --variant 'PinkiC={"seed": 3, "max_leg": 22}' \
  --variant 'PinkiD={"seed": 4, "max_leg": 40}' \
  "$@"
