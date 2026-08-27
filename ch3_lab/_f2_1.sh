#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/render_f2_1.log 2>&1
echo "=== $(date) 名案重產 worker 1 ==="
rm -rf ch3_lab/eps_famous/bystander_effect
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_famous.py --slug bystander_effect
echo "--- bystander_effect rc=$? ---"
rm -rf ch3_lab/eps_famous/sleep_memory
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_famous.py --slug sleep_memory
echo "--- sleep_memory rc=$? ---"
echo "=== $(date) F2-1-DONE ==="
