#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""auditability_coverage.py — 量「我們現在能稽核多少比例的已發布內容」。

## 為什麼有這支(2026-09-06)

主頻道線以 videoId 重數全頻道時翻出:**47 支已發布長片從未進過任何掃描,而且結構上永遠查不了**
—— 因為掃描的母體是「output/ 裡還有檔的片」,而那 47 支的旁白檔已經不存在。

基建線追根因,**結論和原本的假設不同**:

- 那 47 支的發布日有一條**乾淨的分界線**:2026-07-06 以前全缺、07-07 以後全在。
- 滾動式清理會有**移動中的前緣**;固定日期的斷點是**一次性事件**。
- 那個日期對得上 memory `yt-studio-local-migration-2026-07`:
  **2026-07-05 雲端 droplet 因欠費 $9.07 被停權,沒繳、改本機跑。**
  那 47 支的 output/ 產物是**跟著 droplet 一起消失的**。

⇒ **沒有「把旁白一起清掉」的腳本**(scripts/ 裡 grep unlink/remove/rmtree 也找不到這種路徑)。
⇒ **遷移後 234/234 = 100.0%,缺口沒有在長大。**

那為什麼還要這支?因為**沒有任何人在量這個數字**。
今天(2026-09-05~06)這條線一整天在對付的就是這一族:
**「一個查不了的過去」和「一個沒出過事的過去」,在紀錄上長得一樣。**
哪天旁白開始掉(新腳本、磁碟清理、搬目錄搬錯),**現在不會有任何東西不一樣**。

## 這支的設計判準(兩條,都是今天付過學費的)

1. 🔴 **告警的母體是「應該 100% 的那一群」,不是全歷史。**
   全歷史涵蓋率是 83.4%,而那 16.6% 是**已知且不可回復**的 droplet 遺失。
   拿 83.4% 當告警值 ⇒ 它永遠是紅的 ⇒ **沒人會再看它**。
   所以 PASS/FAIL 只看 `CUTOFF` 之後的片,那一群的正確值是 100%。
2. 🔴 **每次都印出數字(正向輸出),不是「有事才響」。**
   見 docs/ops/dispatch.md「規則要嘛是檢查,要嘛是期望」:
   只在出事時才產生輸出的檢查,和從來沒被呼叫過的檢查,在 log 上長得一樣。

## 已知不涵蓋的(不要以為這支查了)

- **只看長片(`L_` 前綴)**。Shorts 的旁白保存狀況我沒查。
- **只看 `.voice.txt` 存不存在**,不看內容對不對、不看是不是那支片真正用的那一版
  (稿子被改寫後音檔沒重配這種事,這支看不出來)。
- **不回填**。那 47 支已經找過 output_recover_bak / _archive / STUDIO,真的沒有。

用法:
  python scripts/auditability_coverage.py           # 印報告,遷移後不是 100% 就 exit 1
  python scripts/auditability_coverage.py --quiet   # 只印一行摘要
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO, OUT = ROOT / "STUDIO", ROOT / "output"

# 2026-07-05 droplet 停權,07-06 之前產出的 output/ 產物隨機器消失。
# 07-07 起是本機產出,那一群的旁白保存率**應該是 100%**,所以告警只看它。
# ⚠️ 這個日期是**已查證的事實**不是猜的:47 支缺檔的發布日 100% 落在 07-06 以前,
#    07-07 以後 234 支零缺漏;memory yt-studio-local-migration-2026-07 記著同一天。
CUTOFF = "2026-07-07"

# 🔴 分母地板。這一格防的是「比率型指標最陰的那種壞法」:
# 涵蓋率 = 有旁白 ÷ 已發布,而**分母自己會縮水** —— uploaded_ledger 被截短、
# 被覆寫、被換成別的頻道的,涵蓋率都會變成漂亮的 100%,而且沒有任何東西不一樣。
# (同族見 docs/ops/dispatch.md §6「比率型驗收指標:分母不可以是處置的目標」)
# 這個值只會往上,不會往下:已發布的片不會變成沒發布。所以分母變小 = 帳本壞了。
# 2026-09-06 實測遷移後母體 = 234;留 10 支餘裕給「我當時數錯了」。
POST_FLOOR = 224


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def measure():
    """回 (post, pre, missing_post) —— post/pre 各是 (總數, 有旁白數)。"""
    ledger = _load(STUDIO / "uploaded_ledger.json", {}) or {}
    pubdate = (_load(STUDIO / "zombie_sweep_pubdate_cache.json", {}) or {}).get("pubdate", {}) or {}
    if not ledger:
        raise RuntimeError("uploaded_ledger.json 讀不到或是空的 —— 這支沒有母體可以量")

    pre_t = pre_ok = post_t = post_ok = 0
    missing_post = []
    for slug, vid in ledger.items():
        if not slug.startswith("L_"):
            continue
        # 查不到發布日的一律當「遷移後」:那是保守的一側(它必須有旁白)。
        d = pubdate.get(vid) or "9999-99-99"
        has = (OUT / f"{slug}.voice.txt").exists()
        if d < CUTOFF:
            pre_t += 1
            pre_ok += has
        else:
            post_t += 1
            post_ok += has
            if not has:
                missing_post.append((d, slug))
    return (post_t, post_ok), (pre_t, pre_ok), sorted(missing_post)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    try:
        (post_t, post_ok), (pre_t, pre_ok), missing = measure()
    except Exception as e:  # noqa: BLE001
        # 🔴 讀不到母體是「壞了」不是「沒事」,必須回非零。
        # 見 docs/ops/2026-09-05_four_states_of_observation.md:失敗路徑與正常路徑
        # 回同一個值,是這個 repo 最常犯的那一族。
        print(f"[FAIL] 稽核涵蓋率量不出來:{e}")
        return 2

    tot_t, tot_ok = post_t + pre_t, post_ok + pre_ok
    pct = lambda ok, t: (100.0 * ok / t) if t else float("nan")
    floor_ok = (post_t >= POST_FLOOR)
    ok = (post_ok == post_t) and floor_ok

    if a.quiet:
        print(f"稽核涵蓋率 遷移後 {post_ok}/{post_t} ({pct(post_ok, post_t):.1f}%)"
              f" | 全歷史 {tot_ok}/{tot_t} ({pct(tot_ok, tot_t):.1f}%)"
              f" | {'✅ 正常' if ok else '🔴 有新缺口'}")
        return 0 if ok else 1

    print("## 已發布長片的可稽核涵蓋率(有沒有留下旁白稿)")
    print()
    print(f"  遷移後(發布日 >= {CUTOFF}) {post_ok:4d} / {post_t:4d} = {pct(post_ok, post_t):5.1f}%   ← 判準看這列")
    print(f"  遷移前(droplet 時代)      {pre_ok:4d} / {pre_t:4d} = {pct(pre_ok, pre_t):5.1f}%   ← 已知不可回復,不列入判準")
    print(f"  全歷史                    {tot_ok:4d} / {tot_t:4d} = {pct(tot_ok, tot_t):5.1f}%   ← 只供對外說明,不要拿它當告警值")
    print()
    if not floor_ok:
        print(f"🔴 **分母縮水**:遷移後母體只剩 {post_t} 支,低於地板 {POST_FLOOR}。")
        print("   已發布的片不會變成沒發布 ⇒ **這代表 uploaded_ledger.json 壞了或被換掉了**,")
        print("   不是內容變少。⚠️ **這時候上面那個涵蓋率百分比沒有意義,不要引用它。**")
        print()

    if ok:
        print("✅ 正常:遷移後產出的片,旁白 100% 都還在 —— 這些片將來出事查得清楚。")
        print(f"   ⚠️ 遷移前那 {pre_t - pre_ok} 支是 2026-07-05 droplet 停權時一起沒的,**找過了,真的沒有**,")
        print("      不要每次看到全歷史那個百分比就再去找一次。")
    else:
        print(f"🔴 有新缺口:遷移後有 {post_t - post_ok} 支已發布長片沒有旁白稿。")
        print("   這不是歷史遺留 —— 這些片是本機產的,旁白**應該在**。")
        print("   ⇒ 去查是什麼把它刪掉/搬走了,並在補上之前不要清任何 output/ 的檔。")
        for d, slug in missing[:20]:
            print(f"     {d}  {slug}")
        if len(missing) > 20:
            print(f"     …另外 {len(missing) - 20} 支")
    print()
    print("量的是什麼:uploaded_ledger.json 裡 L_ 開頭的已發布長片,對上 output/<slug>.voice.txt 存不存在。")
    print("不涵蓋:Shorts、旁白內容對不對、是不是該片真正用的那一版。")

    try:
        import studio_common as sc  # noqa: E402
        sc.log_ops("稽核涵蓋", f"遷移後 {post_ok}/{post_t}({pct(post_ok, post_t):.1f}%)"
                               f"｜{'正常' if ok else '🔴 有新缺口'}")
    except Exception:  # noqa: BLE001
        pass  # 落 ops_log 失敗不影響判準(判準是 exit code 與上面的輸出)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
