#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/render_rr.log 2>&1
echo "=== $(date) 重產 romantic_red(DOI 修正)==="
rm -rf ch3_lab/eps_famous/romantic_red
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_famous.py --slug romantic_red
echo "--- rc=$? ---"
