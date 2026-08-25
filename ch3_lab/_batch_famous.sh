#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/batch_famous.log 2>&1
echo "=== $(date) 名案 5 集 ==="
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_famous.py --all
echo "=== $(date) FAMOUS-DONE ==="
