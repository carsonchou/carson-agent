#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/render_f2_0.log 2>&1
echo "=== $(date) 名案重產 worker 0 ==="
rm -rf ch3_lab/eps_famous/ego_depletion
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_famous.py --slug ego_depletion
echo "--- ego_depletion rc=$? ---"
rm -rf ch3_lab/eps_famous/romantic_red
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_famous.py --slug romantic_red
echo "--- romantic_red rc=$? ---"
echo "=== $(date) F2-0-DONE ==="
