#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_landing.py — 產 bio landing 轉換樞紐(IG/TikTok bio 連這頁·三方同步營利入口)。

暗色·手機優先·自足 HTML。讀 channel_config.affiliates 動態產(只列 url 有填的聯盟)。
區塊:YT訂閱 / 免費檢核表(TG) / 多聯盟(誠實揭露) / 產品階梯(私訊索取·不放帳號) / 打賞 / 接案詢價 / 風險聲明。
誠信:零保證收益、零逼單;聯盟附「不增加你成本+可能虧+抽手續費%」揭露。
輸出完整 HTML 文件(含 charset+viewport,手機優先)。已托管 GitHub Pages:
https://carsonchou.github.io/carson-quant-link/(公開 repo carsonchou/carson-quant-link 只含此 index.html)。
更新:重跑本腳本後,把 assets/landing/index.html 覆蓋到該 repo clone 再 git push 即重新部署。
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "assets" / "landing" / "index.html"
CFG = ROOT / "channel_config.json"
YT = "https://www.youtube.com/@carson-quant"
TG = "https://t.me/CarsonQuant_message_bot"


def _cfg():
    try:
        return json.loads(CFG.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _btn(href, main, sub="", accent="#FFD166"):
    sub_html = f'<span class="sub">{sub}</span>' if sub else ""
    return (f'<a class="btn" href="{href}" target="_blank" rel="noopener" '
            f'style="border-color:{accent}33">{main}{sub_html}</a>')


def build() -> Path:
    c = _cfg()
    affs = c.get("affiliates", {}) or {}
    tips = c.get("tips_url", "")
    rows = [_btn(YT, "▶️ 訂閱 YouTube「量化阿森」", "完整版+每日更新", "#c83232")]
    rows.append(_btn(TG, "🎯 免費領「新手回測避雷檢核表」", "私訊打「回測」", "#4a9"))
    # 聯盟(只列 url 有填的·誠實揭露)
    for k, a in affs.items():
        if k == "_note" or not isinstance(a, dict) or not a.get("url"):
            continue
        rows.append(_btn(a["url"], f'🔗 {a.get("label", k)}', a.get("rate", a.get("note", "")), "#FFD166"))
    # 產品(私訊索取·不放帳號/金流)
    rows.append(_btn(TG, "📊 回測不騙人 試算表(NT$149)", "私訊「試算表」索取", "#FFD166"))
    rows.append(_btn(TG, "📮 避雷雷達 付費電子報", "私訊「電子報」了解", "#FFD166"))
    rows.append(_btn(TG, "🤝 合作/接案詢價", "自動化AI頻道·量化系統搭建", "#8a8"))
    if tips:
        rows.append(_btn(tips, "☕ 請我喝杯咖啡(打賞)", "", "#c9a"))

    html = f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>量化阿森｜Carson Quant · 連結中心</title>
<meta name="description" content="量化阿森 Carson Quant：不喊單、只認數據、幫你避雷。訂閱 YouTube、免費領回測避雷檢核表、實測工具。">
<style>
  :root{{color-scheme:dark}}
  body{{margin:0;background:#0a0c10;color:#eee;font-family:-apple-system,"Noto Sans TC",sans-serif}}
  .wrap{{max-width:520px;margin:0 auto;padding:32px 20px 48px}}
  header{{text-align:center;margin-bottom:28px}}
  .logo{{font-size:34px;font-weight:800;color:#FFD166;letter-spacing:2px}}
  .tag{{color:#8a8a90;font-size:15px;margin-top:6px}}
  main{{display:flex;flex-direction:column;gap:14px}}
  .btn{{display:flex;flex-direction:column;align-items:center;gap:3px;padding:16px 18px;
    background:#14171d;border:1px solid #2a2d35;border-radius:16px;color:#eee;text-decoration:none;
    font-size:17px;font-weight:600;transition:transform .1s}}
  .btn:active{{transform:scale(.98)}}
  .btn .sub{{font-size:12.5px;color:#9a9aa0;font-weight:400}}
  footer{{margin-top:30px;text-align:center;color:#6a6a70;font-size:11.5px;line-height:1.7}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="logo">量化阿森</div>
    <p class="tag">不喊單 · 只認數據 · 幫你避雷</p>
  </header>
  <main>
    {"".join(rows)}
  </main>
  <footer>投資有風險,本頁內容為教學/資訊,不構成投資建議、不保證收益。聯盟連結:透過它註冊不增加你的成本,也支持頻道做真數據內容。</footer>
</div>
</body>
</html>"""
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(html, encoding="utf-8")
    return DEST


if __name__ == "__main__":
    p = build()
    print(f"[landing] 產出 {p}（{p.stat().st_size // 1024} KB）· 托管到 Carrd/Netlify 後設 IG/TikTok bio")
