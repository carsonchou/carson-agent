#!/bin/bash
# 三支測試片總渲染:音樂 → 流體視覺(6 段 checkpoint 續算)→ 合併 → 混音
# 🔴 單實例執行。啟動前 runner 會檢查沒有同名行程(08-21 雙實例互洗教訓)。
cd /d/carson-agent/music/calm || exit 1
LOG=render_all.log
exec >> "$LOG" 2>&1

echo "=== $(date) 開始:三首 60 分鐘音樂 ==="
python ambient3.py full || { echo "MUSIC-FAILED"; exit 1; }

render_video () {
  local name=$1 theme=$2 seed=$3 audio=$4
  echo "=== $(date) [$name] 視覺渲染 theme=$theme seed=$seed ==="
  rm -f "ckpt_$name.npz" "list_$name.txt"
  for s in 0 1 2 3 4 5; do
    echo "--- $(date) [$name] 段 $s/5 ---"
    python fluid.py --secs 600 --theme "$theme" --seed "$seed" --look rich \
      --resume "ckpt_$name.npz" --out "seg_${name}_${s}.mp4" \
      || { echo "SEG-FAILED $name $s"; return 1; }
    echo "file 'seg_${name}_${s}.mp4'" >> "list_$name.txt"
  done
  echo "--- $(date) [$name] 合併+混音 ---"
  ffmpeg -y -loglevel error -f concat -safe 0 -i "list_$name.txt" -i "$audio" \
    -map 0:v -map 1:a -c:v copy -c:a aac -b:a 192k \
    -movflags +faststart -shortest "final_$name.mp4" \
    || { echo "MUX-FAILED $name"; return 1; }
  echo "OK final_$name.mp4 $(du -m "final_$name.mp4" | cut -f1)MB"
}

# 🔴 B(睡眠)必須用 slate(暗底亮墨):睡眠場景螢幕常整晚開著,
#    亮底主題等於在臥室開一盞白燈——使用場景直接毀掉(22:25 啟動後抓到,重排)
render_video A ink    101 current_60min.wav   || echo "VIDEO-A-FAILED"
render_video B slate  202 nightfall_60min.wav || echo "VIDEO-B-FAILED"
render_video C tea    303 rain_60min.wav      || echo "VIDEO-C-FAILED"

echo "=== $(date) ALL-DONE ==="
