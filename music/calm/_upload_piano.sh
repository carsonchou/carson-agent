#!/bin/bash
cd /d/carson-agent/music/calm || exit 1
exec >> upload.log 2>&1
echo "=== $(date) 鋼琴版三支上傳(unlisted)==="
for k in B A C; do
  python -u upload3.py $k unlisted
  echo "--- $k 結束 rc=$? ---"
done
echo "=== $(date) PIANO-UPLOAD-DONE ==="
