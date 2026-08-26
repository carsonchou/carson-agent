#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/render_r1.log 2>&1
echo "=== $(date) 補 ep015 ==="
rm -rf ch3_lab/eps/ep015
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 15
echo "--- row 15 rc=$? ---"
