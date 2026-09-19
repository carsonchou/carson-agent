#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/shorts_w2.log 2>&1
echo "=== $(date) shorts worker 2 ==="
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_short.py --row 2
echo "--- row 2 rc=$? ---"
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_short.py --row 5
echo "--- row 5 rc=$? ---"
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_short.py --row 8
echo "--- row 8 rc=$? ---"
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_short.py --row 11
echo "--- row 11 rc=$? ---"
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_short.py --row 14
echo "--- row 14 rc=$? ---"
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_short.py --row 17
echo "--- row 17 rc=$? ---"
echo "=== $(date) S2-DONE ==="
