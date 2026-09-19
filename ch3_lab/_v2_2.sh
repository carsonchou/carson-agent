#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/render_v2_2.log 2>&1
echo "=== $(date) v2 worker 2(加紀錄幕)==="
rm -rf ch3_lab/eps/ep015
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 15
echo "--- row 15 rc=$? ---"
rm -rf ch3_lab/eps/ep017
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 17
echo "--- row 17 rc=$? ---"
rm -rf ch3_lab/eps/ep018
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 18
echo "--- row 18 rc=$? ---"
echo "=== $(date) V2-2-DONE ==="
