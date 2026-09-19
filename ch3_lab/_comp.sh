#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/comp.log 2>&1
for b in fail mixed held; do
  echo "=== $(date) $b ==="
  youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_compilation.py --bucket $b --limit 6
  echo "--- $b rc=$? ---"
done
echo "=== $(date) COMP-DONE ==="
