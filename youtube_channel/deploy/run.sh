#!/usr/bin/env bash
# Carson Quant 雲端 cron 環境包裝：載入 .env 後以 venv python 執行指定腳本。
# 用法：/root/yt/run.sh scripts/xxx.py [args...]
cd /root/yt || exit 3
set -a
. ./.env 2>/dev/null
set +a
export PYTHONIOENCODING=utf-8
exec .venv/bin/python "$@"
