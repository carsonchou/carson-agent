#!/bin/bash
cd /d/carson-agent || exit 1
exec > ch3_lab/render_demo.log 2>&1
rm -rf ch3_lab/eps/ep016
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row 16
echo "--- rc=$? ---"
