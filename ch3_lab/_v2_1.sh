#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/render_v2_1.log 2>&1
echo "=== $(date) v2 worker 1(加紀錄幕)==="
rm -rf ch3_lab/eps/ep010
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 10
echo "--- row 10 rc=$? ---"
rm -rf ch3_lab/eps/ep011
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 11
echo "--- row 11 rc=$? ---"
rm -rf ch3_lab/eps/ep012
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 12
echo "--- row 12 rc=$? ---"
rm -rf ch3_lab/eps/ep013
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 13
echo "--- row 13 rc=$? ---"
rm -rf ch3_lab/eps/ep014
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 14
echo "--- row 14 rc=$? ---"
echo "=== $(date) V2-1-DONE ==="
