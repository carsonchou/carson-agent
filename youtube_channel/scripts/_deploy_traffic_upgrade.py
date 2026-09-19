#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_deploy_traffic_upgrade.py — 一鍵部署「流量產線升級」到雲端（作戰表落地）。
Carson 用 ! 跑（他本人動作才放行寫雲端）：
  ! /d/carson-agent/youtube_channel/.venv/Scripts/python.exe /d/carson-agent/youtube_channel/scripts/_deploy_traffic_upgrade.py

做：① 每支目標檔先備份雲端現況→.bak_seo（只備一次，不覆蓋既有備份）
    ② 上傳本機(已在雲端真實版上重套編輯、零 drift 風險)版本
    ③ 建 assets/pionex_shots/ + README（你之後丟 Pionex 截圖進去縮圖自動套）
    ④ 雲端 py_compile 全檔煙霧測試，印結果
不動 production_orders.json（部門系統每天自動重生，主題收斂改由 decision_dept 持久注入）。
升級內容：長尾搜尋標題 / Intro三步框架 / 說明欄關鍵字 / SRT字幕生成+上傳 / 短→長導流 / 主題收斂 / outlier搶首發 / 縮圖真實截圖框架。
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_LOCAL = os.path.dirname(HERE)
CLOUD_JSON = os.path.join(ROOT_LOCAL, "cloud.json")

# 要部署的程式檔（皆已在雲端真實版上重套編輯）
SCRIPTS = [
    "scripts/produce_batch.py",     # A 長尾標題 + B Intro長片規則 + C 說明欄關鍵字
    "scripts/generate_script.py",   # B Intro 三步框架
    "scripts/topic_bank.py",        # A 生題長尾搜尋
    "scripts/make_video.py",        # D 產 .srt
    "scripts/upload_youtube.py",    # D upload_captions
    "scripts/daily_publish.py",     # D 觸發字幕上傳 + E 短→長連結
    "scripts/parasite_titles.py",   # F outlier 搶首發 front=True
    "scripts/make_thumbnails.py",   # G 真實截圖框架
    "scripts/decision_dept.py",     # F 主題收斂鐵律(持久注入自動 orders)
]
EXTRA = [
    "assets/pionex_shots/README.md",      # G 截圖素材夾說明（選用，截圖優先於回測卡）
    "STUDIO/backtest_cards.json",         # G 多幣真實回測數據（make_thumbnails 自動套真數字卡，免截圖）
]

import paramiko  # noqa: E402
c = json.load(open(CLOUD_JSON, encoding="utf-8"))
root = c.get("remote_root", "/root/yt")
cli = paramiko.SSHClient(); cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(c["ip"], port=22, username=c.get("user", "root"), password=c["password"], timeout=30)


def run(cmd, t=120):
    i, o, e = cli.exec_command(cmd, timeout=t)
    return o.read().decode("utf-8", "replace"), e.read().decode("utf-8", "replace")


sf = cli.open_sftp()


def remote_exists(path):
    try:
        sf.stat(path)
        return True
    except IOError:
        return False


print("① 備份雲端現況 → .bak_seo（只備一次）")
for f in SCRIPTS:
    rp = f"{root}/{f}"
    bak = rp + ".bak_seo"
    if remote_exists(rp) and not remote_exists(bak):
        data = sf.open(rp, "rb").read()
        with sf.open(bak, "wb") as fh:
            fh.write(data)
        print(f"   備份 {f} → .bak_seo（{len(data)} bytes）")
    elif remote_exists(bak):
        print(f"   略過備份 {f}（.bak_seo 已存在）")

print("② 上傳升級版")
for f in SCRIPTS:
    sf.put(os.path.join(ROOT_LOCAL, f), f"{root}/{f}")
    print(f"   uploaded {f}")

print("③ 建 assets/pionex_shots/ + README")
run(f"mkdir -p {root}/assets/pionex_shots")
for f in EXTRA:
    lp = os.path.join(ROOT_LOCAL, f)
    if os.path.exists(lp):
        sf.put(lp, f"{root}/{f}")
        print(f"   uploaded {f}")
sf.close()

print("④ 雲端 py_compile 煙霧測試")
files = " ".join(SCRIPTS)
out, err = run(f"cd {root} && .venv/bin/python -m py_compile {files} && echo COMPILE_OK")
tail = (out + err).strip()
print("  ", tail[-600:] if tail else "(無輸出)")
cli.close()

print("\n部署完成。")
print("回滾：把雲端 <檔>.bak_seo 覆蓋回 <檔> 即可。")
print("下一步（你來）：")
print("  · 丟 Pionex 後台/回測截圖進 assets/pionex_shots/（縮圖自動改用真截圖+紅框）")
print("  · 設 upload-post.com 自動發：見 STUDIO/upload_post_setup.md（設 UPLOAD_POST_API_KEY）")
print("  · 下批 produce_batch 自動套新規則；新片上架時自動生+傳 SRT 字幕、Shorts 自動掛長片連結")
