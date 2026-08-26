#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""caption_ab.py — 「精準字幕到底有沒有在幫搜尋」的對照實驗。

## 為什麼要做這個實驗
每支長片上傳一軌精準字幕要 **400 units**(5 支/天 = 2,000/天,佔實測上限 11,222 的 17%,
一年 73 萬)。而存量 133 支有 2~5 秒漂移要修,重傳要 **59,850 units = 5.3 個完整配額日**;
若字幕其實不影響搜尋,直接刪掉只要 6,650(便宜 9 倍),還順帶解決 Carson 聽到的不同步。

問題是**沒有人知道字幕有沒有用**。程式碼裡的說法是「精準字幕幫演算法判主題」,
那是推論不是量測,而且**結構上量不到**:所有長片都有字幕(沒有對照組),
Shorts 沒有但 Shorts 不吃搜尋。這支就是去造出那個對照組。

## 設計
- 接下來 20 支新長片,**交替分派**(不是亂數):A 傳字幕、B 不傳,保證剛好 10/10。
  交替是照**發布順序**,所以兩組的發布日期分布幾乎相同 —— 片齡是這個頻道最強的
  混淆變數(memory: 品質分 vs 觀看 r=-0.084,但片齡 r=+0.584)。
- 只收長片。Shorts 本來就不傳字幕,收進來只會稀釋。
- 至少四週後才看結果:體檢片是**常青**的搜尋佔位(不是 feed 驅動的 4 天壽命),
  搜尋排名要時間長出來。

## 誠實邊界
- n=20(每組 10)只能看出**大的**差異。若真實效果是 ±10%,這個樣本量看不出來,
  到時要說「看不出差異」而不是「沒有差異」。
- 個股本身的搜尋量差異很大(台積電 vs 冷門股),交替分派無法平衡這一點 ——
  分析時要**同時看中位數與逐支配對**,不是只看平均。

## 用法
  python scripts/caption_ab.py --status      # 看目前分派到第幾支、兩組各幾支
  python scripts/caption_ab.py --report      # 四週後看結果(走 Analytics,不吃 Data API 配額)
  python scripts/caption_ab.py --stop        # 中止實驗(之後一律照舊傳字幕)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STATE = ROOT / "STUDIO" / "caption_ab.json"
TARGET_PER_ARM = 10          # 每組 10 支 = 共 20 支


def _load():
    try:
        d = json.loads(STATE.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            return d
    except Exception:  # noqa: BLE001
        pass
    return {"active": True, "assigned": {}, "note": "A=傳字幕(對照) / B=不傳(實驗)"}


def _save(d):
    try:
        import studio_common as sc
        sc.save_json_atomic(STATE, d)
    except Exception:  # noqa: BLE001
        try:
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass          # 實驗記錄失敗絕不能反過來害到發布


def should_upload(slug: str, vid: str) -> bool:
    """發布端呼叫:這支要不要傳字幕?

    **fail-open**:實驗檔壞掉、額滿、或任何例外 → 一律回 True(照舊傳字幕)。
    一個觀測用的實驗,不該有能力讓產線少做事。"""
    try:
        if not slug.startswith("L_"):
            return True                      # Shorts 本來就不傳,不進實驗
        d = _load()
        if not d.get("active"):
            return True
        a = d.get("assigned") or {}
        if slug in a:                        # 冪等:重跑同一支不改組別
            return a[slug]["arm"] == "A"
        n_a = sum(1 for v in a.values() if v.get("arm") == "A")
        n_b = len(a) - n_a
        if n_a >= TARGET_PER_ARM and n_b >= TARGET_PER_ARM:
            d["active"] = False              # 收滿了,自動停止
            d["closed_at"] = time.strftime("%F %T")
            _save(d)
            return True
        # 交替分派:少的那組先拿,兩組一樣多時給 A
        arm = "A" if n_a <= n_b else "B"
        if n_a >= TARGET_PER_ARM:
            arm = "B"
        elif n_b >= TARGET_PER_ARM:
            arm = "A"
        a[slug] = {"arm": arm, "vid": vid, "at": time.strftime("%F %T")}
        d["assigned"] = a
        _save(d)
        return arm == "A"
    except Exception:  # noqa: BLE001
        return True


def _status():
    d = _load()
    a = d.get("assigned") or {}
    n_a = sum(1 for v in a.values() if v.get("arm") == "A")
    print(f"實驗{'進行中' if d.get('active') else '已結束'};"
          f"已分派 {len(a)} 支(A 傳字幕 {n_a} / B 不傳 {len(a)-n_a},各收滿 {TARGET_PER_ARM} 支)")
    for slug, v in sorted(a.items(), key=lambda kv: kv[1].get("at", "")):
        print(f"   [{v['arm']}] {v.get('at','')[:16]}  {v.get('vid')}  {slug[6:40]}")
    return 0


def _report():
    """四週後比兩組的搜尋表現。走 Analytics(**獨立配額**,不吃 Data API)。"""
    d = _load()
    a = d.get("assigned") or {}
    if len(a) < 4:
        print(f"樣本還太少({len(a)} 支),再等等。")
        return 0
    import statistics as st
    from datetime import date, timedelta
    import yt_analytics as ya
    s = ya._service()
    end = date.today() - timedelta(days=4)          # Analytics 延遲 2~4 天,錨在 today 會拿短比長
    start = end - timedelta(days=27)
    print(f"期間 {start} ~ {end}(已扣 Analytics 延遲)")
    rows = s.reports().query(
        ids="channel==MINE", startDate=str(start), endDate=str(end),
        metrics="views,estimatedMinutesWatched,averageViewDuration",
        dimensions="video", sort="-estimatedMinutesWatched", maxResults=200
    ).execute().get("rows", [])
    m = {r[0]: r for r in rows}
    g = {"A": [], "B": []}
    for slug, v in a.items():
        r = m.get(v.get("vid"))
        if r:
            g[v["arm"]].append((slug, r[1], r[2], r[3]))
    print(f"\n{'組別':<6}{'支數':>4}{'中位觀看':>10}{'中位時數分':>12}{'中位每次觀看':>14}")
    for arm, lbl in (("A", "A 傳字幕"), ("B", "B 不傳")):
        x = g[arm]
        if not x:
            print(f"{lbl:<6}{0:>4}  (無資料)")
            continue
        print(f"{lbl:<6}{len(x):>4}{st.median(i[1] for i in x):>10.0f}"
              f"{st.median(i[2] for i in x):>12.0f}{st.median(i[3] for i in x):>14.0f}")
    if g["A"] and g["B"]:
        da = st.median(i[1] for i in g["A"])
        db = st.median(i[1] for i in g["B"])
        print(f"\n中位觀看差:{(da-db)/max(db,1)*100:+.0f}%(正=傳字幕比較好)")
        print("⚠️ n 小,只能看出大的差異;若差距在 ±10% 內,結論是「看不出差異」不是「沒有差異」。")
        print("⚠️ 個股本身的搜尋量差很大,別只看中位數 —— 逐支列出來人眼再掃一次:")
        for arm in ("A", "B"):
            for slug, vw, mins, avg in sorted(g[arm], key=lambda x: -x[1]):
                print(f"   [{arm}] 觀看{vw:>5} 時數{mins:>5}分 每次{avg:>4}s  {slug[6:38]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--stop", action="store_true")
    args = ap.parse_args()
    if args.stop:
        d = _load()
        d["active"] = False
        d["closed_at"] = time.strftime("%F %T")
        _save(d)
        print("已中止;之後一律照舊傳字幕。")
        return 0
    if args.report:
        return _report()
    return _status()


if __name__ == "__main__":
    raise SystemExit(main())
