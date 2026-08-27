#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/shorts_w0.log 2>&1
echo "=== $(date) shorts worker 0 ==="
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_short.py --row 0
echo "--- row 0 rc=$? ---"
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_short.py --row 3
echo "--- row 3 rc=$? ---"
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_short.py --row 6
echo "--- row 6 rc=$? ---"
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_short.py --row 9
echo "--- row 9 rc=$? ---"
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_short.py --row 12
echo "--- row 12 rc=$? ---"
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_short.py --row 15
echo "--- row 15 rc=$? ---"
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_short.py --row 18
echo "--- row 18 rc=$? ---"
echo "=== $(date) S0-DONE ==="
