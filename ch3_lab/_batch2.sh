#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/batch.log 2>&1
echo "=== $(date) 佇列 row 6-18 ==="
for i in 6 7 8 9 10 11 12 13 14 15 16 17 18; do
  youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row $i
  echo "--- row $i rc=$? ---"
done
echo "=== $(date) BATCH2-DONE ==="
