#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/render_r1.log 2>&1
echo "=== $(date) resume worker 1 ==="
rm -rf ch3_lab/eps/ep015
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 15
echo "--- row 15 rc=$? ---"
rm -rf ch3_lab/eps/ep016
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 16
echo "--- row 16 rc=$? ---"
rm -rf ch3_lab/eps_famous/bystander_effect
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_famous.py --slug bystander_effect
echo "--- bystander_effect rc=$? ---"
rm -rf ch3_lab/eps_famous/sleep_memory
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_famous.py --slug sleep_memory
echo "--- sleep_memory rc=$? ---"
echo "=== $(date) R1-DONE ==="
