#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/render_r0.log 2>&1
echo "=== $(date) resume worker 0 ==="
rm -rf ch3_lab/eps/ep012
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 12
echo "--- row 12 rc=$? ---"
rm -rf ch3_lab/eps/ep013
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 13
echo "--- row 13 rc=$? ---"
rm -rf ch3_lab/eps/ep014
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 14
echo "--- row 14 rc=$? ---"
rm -rf ch3_lab/eps_famous/ego_depletion
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_famous.py --slug ego_depletion
echo "--- ego_depletion rc=$? ---"
rm -rf ch3_lab/eps_famous/romantic_red
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_famous.py --slug romantic_red
echo "--- romantic_red rc=$? ---"
echo "=== $(date) R0-DONE ==="
