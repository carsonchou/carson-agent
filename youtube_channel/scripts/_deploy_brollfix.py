#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_deploy_brollfix.py — 一鍵部署「畫面治本兩修正」到雲端 + 自證。
修正內容(都在 render_ffmpeg.py):
  ① b-roll 主題對映:無視 LLM 抽象詞,改用主題偵測挑「保證有金融/加密實拍」的具體白名單→畫面不再脫題
  ② 卡片 Ken Burns 推鏡:數據/圖表卡不再靜止,緩推鏡=有影片感、又 100% 自家數據(護城河);通用實拍封頂 ~1/3 段
Carson 用 ! 跑(他本人動作才放行寫雲端):
  ! /d/carson-agent/youtube_channel/.venv/Scripts/python.exe /d/carson-agent/youtube_channel/scripts/_deploy_brollfix.py
做三件事:① 備份雲端 render_ffmpeg.py → .bak_brollq ② 上傳本機修正版 ③ 抓一支現成 S_ slug
跑真渲染(.env 帶 PEXELS),把 Pexels query 行印出來證明 b-roll 已是金融/加密素材、不再亂源。
渲到 /tmp 暫存,不覆蓋正式庫存。"""
import json
import os
import sys

try:  # Windows cp950 終端印 emoji/中文會崩,改 utf-8+replace 不中斷
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL_RF = os.path.join(HERE, "render_ffmpeg.py")
CLOUD_JSON = os.path.join(os.path.dirname(HERE), "cloud.json")

try:
    import paramiko
except ImportError:
    print("缺 paramiko,請先 pip install paramiko"); sys.exit(1)

c = json.load(open(CLOUD_JSON, encoding="utf-8"))
root = c.get("remote_root", "/root/yt")
cli = paramiko.SSHClient(); cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(c["ip"], port=22, username=c.get("user", "root"), password=c["password"], timeout=30)


def run(cmd, timeout=600):
    i, o, e = cli.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace"); err = e.read().decode("utf-8", "replace")
    return out, err


print("① 備份雲端現版 → render_ffmpeg.py.bak_brollq(已存在就不覆蓋,保住原始版)")
print(run(f"[ -f {root}/scripts/render_ffmpeg.py.bak_brollq ] && echo '已有備份,略過' || "
          f"(cp {root}/scripts/render_ffmpeg.py {root}/scripts/render_ffmpeg.py.bak_brollq && echo OK)")[0].strip())

print("② 上傳本機修正版")
sf = cli.open_sftp(); sf.put(LOCAL_RF, root + "/scripts/render_ffmpeg.py"); sf.close()
print("   uploaded:", os.path.getsize(LOCAL_RF), "bytes")

print("③ 找一支現成 S_ slug(有 mp3+md) 跑真渲染驗證")
slug, _ = run(f"cd {root}/output && for f in S_*.mp3; do b=\"${{f%.mp3}}\"; "
              f"if [ -f \"$b.md\" ]; then echo \"$b\"; break; fi; done")
slug = slug.strip()
print("   slug =", slug or "(找不到,跳過驗證)")
if slug:
    # 確認 PEXELS 有載到(只印有無,不印值)
    pk, _ = run(f"cd {root} && set -a && . ./.env 2>/dev/null && set +a && "
                f"python3 -c \"import os;print('PEXELS_API_KEY set?', bool(os.environ.get('PEXELS_API_KEY')))\"")
    print("  ", pk.strip())
    # 用正式 venv 包裝 run.sh(載 .env+有 PIL);渲到 /tmp 不動正式庫存;全輸出寫 log,不 grep
    rcmd = (f"cd {root} && bash run.sh scripts/render_ffmpeg.py --slug '{slug}' "
            f"--out /tmp/_brolltest.mp4 --width 1080 --height 1920 --fps 15 "
            f"> /tmp/_brollrender.log 2>&1; echo \"RC=$?\" >> /tmp/_brollrender.log")
    print("   渲染中(最多 ~15 分)…")
    run(rcmd, timeout=1000)
    # 不論成敗,讀回 log 尾 + 產物(log 已持久化,SSH 斷也讀得到)
    tail, _ = run("tail -50 /tmp/_brollrender.log 2>&1")
    print("---- 渲染完整輸出(尾 50 行) ----"); print(tail or "(log 空)")
    pf, _ = run("ls -la /tmp/_brolltest.mp4 2>/dev/null && "
                "ffprobe -v error -show_entries format=duration -of csv=p=0 /tmp/_brolltest.mp4 2>/dev/null")
    print("---- 產物 ----"); print(pf.strip() or "(沒產出 mp4 → 看上面 log 尾的錯誤)")
    run("rm -f /tmp/_brolltest.mp4 /tmp/_brollrender.log")

cli.close()
print("\n完成。要回滾: cp render_ffmpeg.py.bak_brollq render_ffmpeg.py")
print("要讓既有庫存也吃到新 b-roll,需重渲(那批是舊 b-roll);新排隊的片渲染時會自動套用。")
