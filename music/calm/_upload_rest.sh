#!/bin/bash
# 上傳剩餘兩支(A/C)並補設 B 的縮圖。
# 🔴 用完全脫離的行程跑:Bash tool 的背景任務會被砍(B 就是在輪詢階段被砍的,
#    所幸檔案已傳完)。三支各約 1GB,依序跑避免搶上行頻寬。
cd /d/carson-agent/music/calm || exit 1
LOG=upload.log
exec >> "$LOG" 2>&1

echo "=== $(date) 開始 ==="
python -u upload3.py A unlisted
echo "--- A 結束 rc=$? ---"
python -u upload3.py C unlisted
echo "--- C 結束 rc=$? ---"
python -u _set_thumb.py B 4C3CTKI1BFM
echo "=== $(date) UPLOAD-ALL-DONE ==="
