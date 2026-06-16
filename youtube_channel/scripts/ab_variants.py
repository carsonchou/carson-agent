#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ab_variants.py — 【封面/標題 A/B 變體產生器】為一支片產 3 組標題＋3 張封面變體。

YouTube 原生「測試與比較」最多測 3 組封面/標題、用真流量選最高 CTR，但只能在 Studio 網頁開
（沒開放 API）。本檔把『產變體』這個費工的部分自動化：給標題/主題 → Claude 產 3 個不同角度的
標題變體＋對應封面文案 → 用 make_thumbnails 渲出 3 張封面 → 你到 Studio 兩步上傳即可測。
用法：python scripts/ab_variants.py --title "原標題" [--slug S_xxx 讀片庫標題]
輸出：assets/thumbnails/ab/ 下 3 張 + 終端列出 3 個標題。
"""
from __future__ import annotations
import argparse, json, os, re, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "output"
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-sonnet-4-6"
ACCENT = {"yellow": (255, 210, 63), "green": (88, 224, 140), "red": (255, 96, 96), "blue": (90, 184, 255)}


def gen_variants(title):
    import requests
    prompt = (
        "你是量化阿森(量化/網格/派網/風控,繁中 faceless)的封面標題 A/B 設計師。"
        f"原標題：{title}\n"
        "產 3 個『角度不同』的變體來 A/B 測 CTR(守誠實鐵則,不誇大不喊單,數字用含回撤真值)："
        "①數字震撼型 ②疑問懸念型 ③痛點打臉型。每個給標題＋封面大字(l1/l2各≤5字)＋底部tag＋"
        "配色(green/red/yellow/blue)＋是否放派網回測卡(use_card)＋卡片數字(pct,如+82.4%或-40%)。\n"
        '只輸出 JSON 陣列：[{"title":"","l1":"","l2":"","tag":"","accent":"green","use_card":true,"pct":"+82.4%"}]'
    )
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                               "content-type": "application/json"},
                      json={"model": MODEL, "max_tokens": 1200, "temperature": 0.7,
                            "messages": [{"role": "user", "content": prompt}]}, timeout=120)
    r.raise_for_status()
    m = re.search(r"\[.*\]", r.json()["content"][0]["text"], re.S)
    return json.loads(m.group(0)) if m else []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default=None)
    ap.add_argument("--slug", default=None, help="從 output/<slug>.md 第一行讀標題")
    args = ap.parse_args()
    title = args.title
    if not title and args.slug:
        try:
            first = (OUT / f"{args.slug}.md").read_text(encoding="utf-8").splitlines()[0]
            title = first.replace("# 🎬", "").replace("#", "").strip()
        except Exception:
            pass
    if not title:
        print("[FATAL] 請給 --title 或 --slug", file=sys.stderr); return 2
    if not API_KEY:
        print("[FATAL] 無 ANTHROPIC_API_KEY", file=sys.stderr); return 2

    vs = [v for v in gen_variants(title) if v.get("title")][:3]
    if not vs:
        print("[FATAL] 產不出變體", file=sys.stderr); return 3

    import make_thumbnails as mt
    abdir = ROOT / "assets" / "thumbnails" / "ab"
    abdir.mkdir(parents=True, exist_ok=True)
    base = re.sub(r"[^\w]+", "", title)[:16]
    print(f"\n=== A/B 變體（原：{title[:30]}）===")
    for i, v in enumerate(vs, 1):
        accent = ACCENT.get((v.get("accent") or "yellow").lower(), ACCENT["yellow"])
        cfg = {"slug": f"AB_{base}_{i}", "l1": (v.get("l1") or "")[:6], "l2": (v.get("l2") or "")[:6],
               "tag": (v.get("tag") or "")[:18], "accent": accent, "mark": "?"}
        if v.get("use_card"):
            pct = v.get("pct", "+82.4%")
            cfg["card"] = {"strat": "網格·示意", "metric": "回測年化(示意)", "pct": pct,
                           "pct_color": "red" if str(pct).startswith("-") else "green",
                           "mdd": "最大回撤 -15.3%", "range": "區間 1774-2028", "note": "※示意，非獲利保證"}
        # 借 make_thumbnails 的繪圖，但輸出到 ab 目錄
        from PIL import ImageDraw
        img = mt.gradient_bg((14, 22, 46), (28, 44, 86))
        d = ImageDraw.Draw(img, "RGBA")
        if cfg.get("card"):
            mt.draw_backtest_card(d, cfg["card"])
        else:
            d.text((mt.W - 360, mt.H // 2), cfg["mark"], font=mt.font(420, bold=True),
                   fill=(*accent, 46), anchor="mm")
        d.rectangle([0, 0, 18, mt.H], fill=accent)
        f1 = mt.font(120 if cfg.get("card") else 150, bold=True)
        mt.draw_text_stroke(d, (66, 210), cfg["l1"], f1, fill=accent, sw=7)
        b1 = d.textbbox((66, 210), cfg["l1"], font=f1, stroke_width=7)
        mt.draw_text_stroke(d, (66, b1[3] + 30), cfg["l2"], f1, fill=(245, 248, 255), sw=7)
        tf = mt.font(54, bold=True)
        d.rectangle([0, mt.H - 96, mt.W, mt.H], fill=(*accent, 235))
        d.text((66, mt.H - 78), cfg["tag"], font=tf, fill=(12, 18, 38))
        outp = abdir / f"{cfg['slug']}.jpg"
        img.save(outp, "JPEG", quality=90)
        kind = ["數字震撼", "疑問懸念", "痛點打臉"][i - 1] if i <= 3 else f"變體{i}"
        print(f"\n[變體{i}·{kind}]")
        print(f"  標題：{v['title']}")
        print(f"  封面：{outp.name}")
    print(f"\n→ 3 張封面在 {abdir}")
    print("→ 到 YouTube Studio → 內容 → 該片 → 縮圖『測試與比較』上傳這 3 張；標題用上面 3 個輪測。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
