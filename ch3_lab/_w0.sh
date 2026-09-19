#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/render_w0.log 2>&1
echo "=== $(date) worker 0 ==="
for r in $(seq 0 3 18); do
  youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row $r
  echo "--- row $r rc=$? ---"
done
for s in ego_depletion romantic_red; do
  youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_famous.py --slug $s
  echo "--- $s rc=$? ---"
done
echo "=== $(date) W0-DONE ==="
