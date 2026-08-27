#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/render_f3.log 2>&1
rm -rf ch3_lab/eps_famous/bystander_effect
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_famous.py --slug bystander_effect
echo "--- rc=$? ---"
