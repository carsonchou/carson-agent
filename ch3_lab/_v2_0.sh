#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/render_v2_0.log 2>&1
echo "=== $(date) v2 worker 0(加紀錄幕)==="
rm -rf ch3_lab/eps/ep005
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 5
echo "--- row 5 rc=$? ---"
rm -rf ch3_lab/eps/ep006
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 6
echo "--- row 6 rc=$? ---"
rm -rf ch3_lab/eps/ep007
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 7
echo "--- row 7 rc=$? ---"
rm -rf ch3_lab/eps/ep008
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 8
echo "--- row 8 rc=$? ---"
rm -rf ch3_lab/eps/ep009
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 9
echo "--- row 9 rc=$? ---"
echo "=== $(date) V2-0-DONE ==="
