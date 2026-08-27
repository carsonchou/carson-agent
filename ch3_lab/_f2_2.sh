#!/bin/bash
cd /d/carson-agent || exit 1
exec >> ch3_lab/render_f2_2.log 2>&1
echo "=== $(date) 名案重產 worker 2 ==="
rm -rf ch3_lab/eps_famous/implicit_bias_test
youtube_channel/.venv/Scripts/python.exe -u ch3_lab/make_famous.py --slug implicit_bias_test
echo "--- implicit_bias_test rc=$? ---"
echo "=== $(date) F2-2-DONE ==="
