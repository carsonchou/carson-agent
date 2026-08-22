#!/bin/bash
# 三支氛圍正片渲染:流體視覺(6 段 checkpoint 續算)→ 合併 → 混音
# 🔴 單實例執行;啟動前由 PowerShell 端檢查沒有同名行程(08-21 雙實例互洗教訓)。
# 順序:slate(睡眠)優先——審核建議先發這支;ink 次之;tea 最後。
cd /d/carson-agent/music/calm || exit 1
LOG=render_all.log
exec >> "$LOG" 2>&1

echo "=== $(date) 開始 ==="

# 音樂:已生成過就跳過(三首 60 分鐘 WAV 各 635MB,重跑要 7 分鐘且結果相同)
if [ -f current_60min.wav ] && [ -f nightfall_60min.wav ] && [ -f rain_60min.wav ]; then
  echo "音樂已存在,跳過生成"
else
  python ambient3.py full || { echo "MUSIC-FAILED"; exit 1; }
fi

render_video () {
  local name=$1 theme=$2 seed=$3 audio=$4
  if [ -f "final_$name.mp4" ]; then
    echo "=== [$name] final 已存在,跳過 ==="; return 0
  fi
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
  rm -f "seg_${name}"_*.mp4 "ckpt_$name.npz" "list_$name.txt"   # 段檔佔 500MB/支
}

# 🔴 平行:剖析顯示模擬是單執行緒瓶頸(16 核只用 10%),三支互不相依
#    (各自 checkpoint 鏈)→ 同時跑,wall time 從 ~21hr 降到 ~5hr。
render_video B slate  202 nightfall_60min.wav || echo "VIDEO-B-FAILED" &
PB=$!
render_video A ink    101 current_60min.wav   || echo "VIDEO-A-FAILED" &
PA=$!
render_video C tea    303 rain_60min.wav      || echo "VIDEO-C-FAILED" &
PC=$!
wait $PB $PA $PC

echo "=== $(date) ALL-DONE ==="
