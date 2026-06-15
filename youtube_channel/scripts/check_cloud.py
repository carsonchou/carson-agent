#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_cloud.py — 一鍵確認「雲端工廠有沒有讀到最新指令(playbook)」。

跑法（在 youtube_channel 目錄）：
    .venv\\Scripts\\python.exe scripts\\check_cloud.py

它會比對三件事，全綠就代表雲端吃到你本機最新心法：
  1) 本機 vs 雲端 playbook 的 md5 是否一致（檔案有沒有到位）
  2) 雲端工廠 load_playbook() 實際讀到的字數＋最新招式日期（程式有沒有吃進去）
  3) cron.log 最近的「讀心法」指紋章＋產線紀錄（每輪製作的自動存證）
"""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
PLAYBOOK = ROOT / "STUDIO" / "competitor_playbook.md"


def local_md5():
    if not PLAYBOOK.exists():
        return None, 0
    b = PLAYBOOK.read_bytes()
    return hashlib.md5(b).hexdigest(), len(b)


def main():
    cfg = ROOT / "cloud.json"
    if not cfg.exists():
        print("✗ 找不到 cloud.json，無法連雲端。"); return 1
    try:
        import paramiko
    except Exception:
        print("✗ 沒有 paramiko（請用 .venv 的 python 跑）。"); return 1

    lmd5, lsize = local_md5()
    print(f"本機 playbook：md5={lmd5}  size={lsize}\n")

    c = json.loads(cfg.read_text(encoding="utf-8"))
    ip, user, pw = c["ip"], c.get("user", "root"), c["password"]
    rroot = c.get("remote_root", "/root/yt")

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(ip, username=user, password=pw, timeout=30)

    def run(cmd):
        _, out, err = cli.exec_command(cmd)
        return (out.read() + err.read()).decode("utf-8", "replace").strip()

    rmd5 = run(f"md5sum {rroot}/STUDIO/competitor_playbook.md | cut -d' ' -f1")
    print("【1】檔案到位？")
    print(f"    雲端 md5={rmd5}")
    print("    " + ("✅ 一致，本機檔案已成功推上雲端" if rmd5 == lmd5
                    else "⚠️ 不一致！雲端不是最新版，請重跑 intel_sync 推送"))

    print("\n【2】工廠程式吃進去了？")
    r2 = run(f"cd {rroot} && python3 -c \""
             "import sys; sys.path.insert(0,'scripts'); "
             "from produce_batch import load_playbook; "
             "import re; t=load_playbook(); "
             "d=re.findall(r'20..-..-..',t); "
             "print('字數=%d 最新招式=%s' % (len(t), max(d) if d else '無'))\"")
    print(f"    {r2}")

    print("\n【3】cron.log 最近的指紋章＋產線紀錄：")
    r3 = run(f"grep -E '讀心法|補產部門|新增' {rroot}/logs/cron.log | tail -n 6")
    print("    " + (r3.replace("\n", "\n    ") if r3 else "（還沒有紀錄，下輪 7:07 製作後會出現）"))

    cli.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
