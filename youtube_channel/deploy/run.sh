#!/usr/bin/env bash
# Carson Quant 雲端 cron 環境包裝：載入 .env 後以 venv python 執行指定腳本。
# 用法：/root/yt/run.sh scripts/xxx.py [args...]
cd /root/yt || exit 3
set -a
. ./.env 2>/dev/null
set +a
export PYTHONIOENCODING=utf-8
# 確保 logs/ 目錄存在（cron 第一次跑時若目錄不存在，輸出會消失而非寫入檔案）
mkdir -p /root/yt/logs
exec .venv/bin/python "$@"
