#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/batch_famous.log 2>&1
echo "=== $(date) 名案剩下 4 集 ==="
for s in romantic_red bystander_effect sleep_memory implicit_bias_test; do
  youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_famous.py --slug $s
  echo "--- $s rc=$? ---"
done
echo "=== $(date) FAMOUS2-DONE ==="
