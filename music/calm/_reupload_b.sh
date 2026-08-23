#!/bin/bash
# SLEEP 重傳:原本那支(4C3CTKI1BFM)YouTube 端卡死 UNPLAYABLE、時長 0、無任何格式,
# 本機檔案已完整解碼驗證無誤 → 重傳。舊的等新的處理完成後再刪。
cd /d/carson-agent/music/calm || exit 1
exec >> upload.log 2>&1
echo "=== $(date) SLEEP 重傳開始(舊 4C3CTKI1BFM 卡死)==="
python -u upload3.py B unlisted
echo "=== $(date) REUPLOAD-DONE rc=$? ==="
