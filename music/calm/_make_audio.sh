#!/bin/bash
cd /d/carson-agent/music/calm || exit 1
exec >> audio_build.log 2>&1
echo "=== $(date) 產三首 12 分鐘鋼琴曲(平鋪 5 次 = 60 分)==="
python -u piano_perf.py full
echo "=== $(date) AUDIO-DONE rc=$? ==="
