#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/shorts_w1.log 2>&1
echo "=== $(date) shorts worker 1 ==="
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_short.py --row 1
echo "--- row 1 rc=$? ---"
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_short.py --row 4
echo "--- row 4 rc=$? ---"
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_short.py --row 7
echo "--- row 7 rc=$? ---"
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_short.py --row 10
echo "--- row 10 rc=$? ---"
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_short.py --row 13
echo "--- row 13 rc=$? ---"
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_short.py --row 16
echo "--- row 16 rc=$? ---"
echo "=== $(date) S1-DONE ==="
