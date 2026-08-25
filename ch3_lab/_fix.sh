#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/render_fix.log 2>&1
echo "=== $(date) 重產字幕文法受影響的集數 ==="
for r in $ROWS; do
  rm -rf ch3_lab/eps/ep$(printf %03d $r)
  youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_episode.py --row $r
  echo "--- row $r rc=$? ---"
done
echo "=== $(date) FIX-DONE ==="
