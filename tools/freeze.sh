#!/usr/bin/env bash
# freeze.sh NAME SEED : snapshot the current submission as a frozen opponent.
cd ~/cw
name="$1"; seed="${2:-7}"
rm -rf "my_bots/$name"
cp -r /mnt/e/Projects/Agent_Showdown/submission/PinkiSaanp "my_bots/$name"
rm -rf "my_bots/$name/pinki/__pycache__"
echo "{\"seed\": $seed}" > "my_bots/$name/variant.json"
echo "frozen my_bots/$name"; cat "my_bots/$name/variant.json"
