#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_deploy_llm_shim.py — 一鍵把 LLM shim 部署上雲端(Carson 按 ! 跑)。
把 _llm_shim.py 推到 scripts/、sitecustomize.py 推到 venv site-packages，
讓所有部門腳本的 Anthropic 請求自動改道 OpenRouter。跑完會自我測試。
用法： python scripts/_deploy_llm_shim.py
"""
import json, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
cfg = json.load(open("cloud.json", encoding="utf-8"))
env = dict(os.environ)
env.update(DROPLET_IP=cfg["ip"], DROPLET_PW=cfg["password"],
           DROPLET_USER=cfg.get("user", "root"), PYTHONIOENCODING="utf-8")
CS = "scripts/cloud_ssh.py"; rr = cfg["remote_root"]

def cs(*a, timeout=120):
    p = subprocess.run([sys.executable, CS, *a], env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return (p.stdout or "") + (p.stderr or "")

sp = cs("run", f"cd {rr} && .venv/bin/python -c 'import site;print(site.getsitepackages()[0])'").strip().splitlines()[-1].strip()
print("site-packages:", sp)
print("[put _llm_shim]", cs("put", "scripts/_llm_shim.py", f"{rr}/scripts/_llm_shim.py")[-70:])
# .pth 比 sitecustomize 可靠(site.py 會執行每一個 .pth 的 import 行,不會被系統 sitecustomize 蓋掉)
print("[put .pth]", cs("put", "scripts/_llm_shim.pth", f"{sp}/_llm_shim.pth")[-70:])
test = ('import requests; r=requests.post("https://api.anthropic.com/v1/messages",'
        'headers={"anthropic-version":"2023-06-01"},'
        'json={"model":"claude-haiku-4-5-20251001","max_tokens":40,'
        '"messages":[{"role":"user","content":"用繁體中文回一句話證明路由可用"}]}); '
        'print("status",r.status_code); print("resp",r.json()["content"][0]["text"][:80])')
print("[自測改道]", cs("run", f"cd {rr} && ./run.sh -c {json.dumps(test)}")[-400:])
print("\n完成。若上面 resp 有繁體中文回應=全部部門腳本已改道 OpenRouter。")
