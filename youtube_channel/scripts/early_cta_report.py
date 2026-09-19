#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""early_cta_report.py — 早段訂閱邀請 A/B 的結果報告。

## 實驗在測什麼
頻道最強的訂閱理由是「這個系列會把全台股1925檔一檔一檔體檢完…你手上那幾檔遲早會輪到」,
對搜自己股票進來的人精準命中。但它放在**片尾**,而實測留存曲線(近兩月觀看最高 20 支長片
加權)片尾只剩 **8%** 的觀眾:

    24秒→56%   48秒→41%   96秒→31%   168秒→24%   片尾→8%

實驗組把同一句話**搬**到約第 50 秒(不是多加一句——多加會跟片尾那句幾乎一字不差,
直接踩到整句去重與密度閘門,而且也分離不出「位置」本身的效果)。
對照組維持片尾。分組照標題雜湊,確定性。

## 判讀紀律(memory yt-analytics-lag-false-alarm / yt-quality-score-not-predictive)
- Analytics 延遲 2~4 天:兩組都只取「資料到得了」的日期,而且兩組**片齡分布要接近**。
- 主指標是 subscribersGained/views,不是觀看數。
- n 太小就明講 n 太小,不要在 10 支上宣布勝負。

用法:
  python scripts/early_cta_report.py
  python scripts/early_cta_report.py --notify    # 樣本夠了才推 ntfy
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STATE = ROOT / "STUDIO" / "early_cta_ab.json"
MIN_PER_ARM = 12          # 每組至少幾支才值得下結論


def _norm(s: str) -> str:
    return "".join(ch for ch in str(s) if ch.isalnum())[:40].lower()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--notify", action="store_true")
    args = ap.parse_args()

    if not STATE.exists():
        print("還沒有任何分組紀錄(STUDIO/early_cta_ab.json 不存在)——實驗還沒開始跑。")
        return 0
    st = json.loads(STATE.read_text(encoding="utf-8"))
    arms = {}
    for title, rec in st.items():
        a = "treat" if str(rec.get("arm", "")).startswith("treat") else "control"
        arms.setdefault(a, []).append((title, rec))
    print(f"分組紀錄:實驗 {len(arms.get('treat', []))} 支 / 對照 {len(arms.get('control', []))} 支")

    # 把分組名單對到實際已發布影片(標題正規化比對;產製標題與發布標題可能被潤飾過)
    import yt_analytics as ya
    import upload_youtube as uy

    yt = uy.get_authenticated_service(client_secrets=ROOT / "client_secrets.json",
                                      token_path=ROOT / "token.json")
    svc = ya._service()
    r = svc.reports().query(
        ids="channel==MINE", startDate="2026-08-25", endDate="2026-12-31",
        metrics="views,subscribersGained,averageViewDuration",
        dimensions="video", sort="-views", maxResults=200).execute()
    rows = r.get("rows", [])
    ids = [x[0] for x in rows]
    meta = {}
    for i in range(0, len(ids), 50):
        resp = yt.videos().list(part="snippet", id=",".join(ids[i:i + 50])).execute()
        for it in resp.get("items", []):
            meta[it["id"]] = it["snippet"]["title"]

    idx = {}
    for a, items in arms.items():
        for title, _rec in items:
            idx[_norm(title)] = a

    agg = {"treat": [0, 0, 0, 0], "control": [0, 0, 0, 0]}   # views, subs, n, avd*views
    unmatched = 0
    for vid, v, g, avd in rows:
        t = _norm(meta.get(vid, ""))
        a = None
        for k, arm in idx.items():
            if k and (k[:24] in t or t[:24] in k):
                a = arm
                break
        if not a:
            unmatched += 1
            continue
        agg[a][0] += v; agg[a][1] += g; agg[a][2] += 1; agg[a][3] += v * avd

    print(f"對得上的已發布影片:實驗 {agg['treat'][2]} / 對照 {agg['control'][2]}"
          f"(另有 {unmatched} 支不在分組名單內,多半是實驗開始前發的)")
    print()
    print(f"{'組別':<8} {'支數':>4} {'觀看':>7} {'訂閱':>5} {'轉化':>8} {'加權平均觀看':>12}")
    print("-" * 56)
    for a, label in (("treat", "實驗(第50秒)"), ("control", "對照(片尾)")):
        v, g, n, m = agg[a]
        print(f"{label:<8} {n:>4} {v:>7} {g:>5} {g/max(v,1)*100:>7.3f}% {m/max(v,1):>11.0f}秒")

    tv, tg, tn, _ = agg["treat"]
    cv, cg, cn, _ = agg["control"]
    print()
    if tn < MIN_PER_ARM or cn < MIN_PER_ARM:
        # 實測發布節奏 3 支/天,其中長片約 2.5 支;一半分到實驗組 ⇒ 每組每天約 1.25 支
        _need = max(0, MIN_PER_ARM - min(tn, cn))
        print(f"⚠️ **樣本不足**(每組至少 {MIN_PER_ARM} 支才下結論;現在 {tn}/{cn})。"
              f"照每天 2.5 支長片、一半分到實驗組(每組約 1.25 支/天),約需再等 "
              f"{_need / 1.25:.0f} 天。先不要動產線參數(memory:評估前別動發布參數)。")
    else:
        t_rate = tg / max(tv, 1); c_rate = cg / max(cv, 1)
        lift = (t_rate / c_rate - 1) * 100 if c_rate else 0
        print(f"轉化率:實驗 {t_rate*100:.3f}% vs 對照 {c_rate*100:.3f}%  →  {lift:+.0f}%")
        print("⚠️ 這只是點估計。訂閱是稀有事件(每支 0~4 個),兩組各 12 支時單一支的波動就能翻轉方向;"
              "看方向一致性(多跑幾週)勝過看單次數字。")
    if args.notify and tn >= MIN_PER_ARM and cn >= MIN_PER_ARM:
        try:
            from notify import push
            push("早段CTA實驗可判讀了",
                 f"實驗 {tg}/{tv} vs 對照 {cg}/{cv};跑 python scripts/early_cta_report.py 看細節")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 推播失敗:{str(e)[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
