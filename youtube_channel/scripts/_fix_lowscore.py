#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_fix_lowscore.py — 把倉庫低於門檻的未發布片退件重做(Carson 按 ! 跑)。
讀本機 STUDIO/quality_scores.json 找 score<門檻 的 pending，逐支在雲端 reject --remake。
用法： python scripts/_fix_lowscore.py
"""
import json, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
d = json.load(open("STUDIO/quality_scores.json", encoding="utf-8"))
mn = d.get("min_score", 75)
low = [(p["slug"], p.get("score")) for p in d["pending"]
       if p.get("score") is not None and p["score"] < mn]
if not low:
    print(f"沒有低於門檻 {mn} 的片，不用處理。"); sys.exit(0)
print(f"門檻 {mn}，要退件重做 {len(low)} 支：", [(s[:24], sc) for s, sc in low])
cfg = json.load(open("cloud.json", encoding="utf-8"))
env = dict(os.environ)
env.update(DROPLET_IP=cfg["ip"], DROPLET_PW=cfg["password"],
           DROPLET_USER=cfg.get("user", "root"), PYTHONIOENCODING="utf-8")
CS = "scripts/cloud_ssh.py"; rr = cfg["remote_root"]

def cs(*a, timeout=60):
    p = subprocess.run([sys.executable, CS, *a], env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return (p.stdout or "") + (p.stderr or "")

slugs = [s for s, _ in low]
cmds = " ; ".join(f"./run.sh scripts/quality_score.py --reject {json.dumps(s)} --remake" for s in slugs)
cs("run", f"cd {rr} && mkdir -p logs && : > logs/lowfix.log")
cs("detached", f"cd {rr} && ({cmds}) >> logs/lowfix.log 2>&1")
print(f"已背景啟動退件重做 {len(slugs)} 支(用 DeepSeek 重寫+雲哲配音)。")
print("進度看雲端 logs/lowfix.log；跑完倉庫會補回昇華版。")
