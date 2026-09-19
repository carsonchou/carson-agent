#!/bin/bash
# 只換音軌:畫面 -c:v copy 不重算(6 段串接的驗收結果依然有效)
cd /d/carson-agent/music/calm || exit 1
exec >> remux.log 2>&1
echo "=== $(date) 換音軌開始 ==="
remux () {
  local key=$1 audio=$2
  ffmpeg -y -loglevel error -i "final_${key}.mp4" -i "$audio" \
    -map 0:v -c:v copy -map 1:a -c:a aac -b:a 192k \
    -movflags +faststart -shortest "piano_${key}.mp4" \
    && echo "OK piano_${key}.mp4 $(du -m piano_${key}.mp4 | cut -f1)MB" \
    || echo "REMUX-FAILED $key"
}
remux B nightfall_piano60.wav
remux A current_piano60.wav
remux C rain_piano60.wav
echo "=== $(date) REMUX-DONE ==="
