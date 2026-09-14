#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""已知未修:slug 含 `0050` 的片,兩套分類法不同調 —— **這支只記錄,不判定,exit 一律 0。**

用法:youtube_channel/.venv/Scripts/python.exe youtube_channel/tests/playlist_privacy/known_gap_0050.py

派工單(2026-09-12,dispatch_w9_private13)在修 privacyStatus 的同一則裡點名了這件事,
並且明講「**只記錄下來,不在這次修**:分桶規則是另一個問題,改它會動到公開清單的內容」。
所以本支不是測試,是一張現況快照,給下一個真的要動分桶規則的人當起點。

🔴 派工單的描述與磁碟上的東西對不上,以下是 2026-09-14 現量的值(不是轉述):
  - 派工單寫「playlists.json 裡這些片只在 etf_dca」。`etf_dca` **不在** playlists.json 裡
    (它只有三個鍵:AI×交易 / 台股量化 / EP實測)。
  - 🔴 但 `etf_dca` **是一條真的播放清單**,不是只有一個名字:它是 playlist_engine.py 的
    桶 key(在那支裡 grep `"key": "etf_dca"`,標題「0050/ETF 定期定額實驗」),
    清單 id **PLJp7y2jl2p64**、219 支,
    狀態存在 **STUDIO/playlist_engine.json**(與 build_playlists 刻意分開,理由見
    playlist_engine.py 檔頭 docstring 的「為什麼要有這支」那段)。binge_chain_plan.json 的 `series` 欄沿用同一個 key,
    那是第三套分類。
    (這一段更正本檔第一版與我 09-14 上午回報的說法 —— 當時只查到 binge_chain 那一層,
     把「它是 series 欄位值」講成了全部。)
  - 這些片也**已經在**台股量化清單裡:台股量化 125 支中 82 支 slug 含 0050;
    etf_dca 219 支中 112 支含 0050,兩邊重疊 105 支。
  - 所以三套分類法**非互斥,同一支片同時歸屬多個桶是設計**,不是「漏加進清單」。

實測交叉表(帳本 1152 支中 slug 含 0050 的 121 支,其中 19 支同時在 binge_chain_plan):
    build_playlists.classify=台股量化  ×  binge series=etf_dca            18 支
    build_playlists.classify=台股量化  ×  binge series=checkup:半導體業     1 支
    另外 4 支 slug 含 0050 的被 classify 歸到「AI×交易」——BUCKETS 是依序取第一個命中,
    而 "AI" 排在 "0050" 前面(例:S_AI選股vs0050定投5年回測誰贏…)。

要動的時候先看清楚:classify 改了會改變**公開播放清單的內容**(片會從一個清單搬到另一個),
而 playlists.json 是 binge_chain 每天 17:05 的輸入。這不是重新分桶而已,是對外的內容變更。
"""
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    spec = importlib.util.spec_from_file_location("bp", BASE / "scripts" / "build_playlists.py")
    bp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bp)

    ledger = bp.load_ledger()
    plan = json.loads((BASE / "STUDIO" / "binge_chain_plan.json").read_text(encoding="utf-8"))
    series = {r["vid"]: r["series"] for r in plan.get("rows", [])}
    state = json.loads((BASE / "STUDIO" / "playlists.json").read_text(encoding="utf-8"))
    slug_of = {v: k for k, v in ledger.items()}

    z = [(s, v) for s, v in ledger.items() if "0050" in s]
    print(f"[記錄] 帳本 {len(ledger)} 支,slug 含 0050 的 {len(z)} 支。")
    print("[記錄] classify 分桶:", dict(Counter(bp.classify(s) for s, _ in z)))
    cross = Counter((bp.classify(s), series[v]) for s, v in z if v in series)
    print(f"[記錄] 與 binge_chain_plan 的交叉表(兩邊都有的 {sum(cross.values())} 支):")
    for (b, ser), n in cross.most_common():
        print(f"         classify={b}  ×  binge series={ser}  → {n} 支")
    pe_path = BASE / "STUDIO" / "playlist_engine.json"
    pe = json.loads(pe_path.read_text(encoding="utf-8")).get("etf_dca", {})
    pe_ids = pe.get("video_ids", [])
    print(f"[記錄] playlist_engine.json 的 etf_dca:清單 {pe.get('playlist_id')},"
          f"{len(pe_ids)} 支,其中 slug 含 0050 的 "
          f"{sum(1 for v in pe_ids if '0050' in slug_of.get(v, ''))} 支。")
    for name, d in state.items():
        n = sum(1 for v in d["video_ids"] if "0050" in slug_of.get(v, ""))
        print(f"[記錄] 清單「{name}」共 {len(d['video_ids'])} 支,其中 slug 含 0050 的 {n} 支。")
        if name == "台股量化":
            print(f"[記錄] 「台股量化」與 etf_dca 重疊 "
                  f"{len(set(d['video_ids']) & set(pe_ids))} 支 —— 三套分類法非互斥,這是設計。")
    print("\n[記錄] 本次不修(派工單指示)。exit 0 —— 這支不是判準,別拿它當綠燈。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
