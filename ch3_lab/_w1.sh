#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/render_w1.log 2>&1
echo "=== $(date) worker 1 ==="
for r in $(seq 1 3 18); do
  youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row $r
  echo "--- row $r rc=$? ---"
done
for s in bystander_effect sleep_memory; do
  youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_famous.py --slug $s
  echo "--- $s rc=$? ---"
done
echo "=== $(date) W1-DONE ==="
