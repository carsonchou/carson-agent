#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/render_w2.log 2>&1
echo "=== $(date) worker 2 ==="
for r in $(seq 2 3 18); do
  youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row $r
  echo "--- row $r rc=$? ---"
done
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_famous.py --slug implicit_bias_test
echo "--- implicit_bias_test rc=$? ---"
echo "=== $(date) W2-DONE ==="
