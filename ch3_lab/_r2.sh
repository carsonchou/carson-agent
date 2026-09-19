#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/render_r2.log 2>&1
echo "=== $(date) resume worker 2 ==="
rm -rf ch3_lab/eps/ep017
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 17
echo "--- row 17 rc=$? ---"
rm -rf ch3_lab/eps/ep018
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 18
echo "--- row 18 rc=$? ---"
rm -rf ch3_lab/eps_famous/implicit_bias_test
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_famous.py --slug implicit_bias_test
echo "--- implicit_bias_test rc=$? ---"
echo "=== $(date) R2-DONE ==="
