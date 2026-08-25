#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/batch.log 2>&1
echo "=== $(date) 批次產片(新佇列 19 集)==="
for i in 0 1 2 3 4 5; do
  youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row $i
  echo "--- row $i rc=$? ---"
done
echo "=== $(date) BATCH-DONE ==="
