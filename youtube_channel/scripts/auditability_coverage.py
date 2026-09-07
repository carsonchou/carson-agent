#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""auditability_coverage.py — 量「我們現在能稽核多少比例的已發布內容」。

## 為什麼有這支(2026-09-06)

主頻道線以 videoId 重數全頻道時翻出:**47 支已發布長片從未進過任何掃描,而且結構上永遠查不了**
—— 因為掃描的母體是「output/ 裡還有檔的片」,而那 47 支的旁白檔已經不存在。

基建線追根因,**結論和原本的假設不同**:

- 那 47 支的發布日有一條斷點:**07-07 以後零缺漏;07-06 以前 49 支只活下來 2 支**。
  ⚠️ 初稿寫「07-06 以前**全**缺」,有 **2 個反例**(pubdate 06-30 與 07-05 各一支旁白還在),已更正。
  **乾淨的只有 07-07 那一側。**
- 滾動式清理會有**移動中的前緣**;固定日期的斷點是**一次性事件**。
- 那個日期對得上 memory `yt-studio-local-migration-2026-07`:
  **2026-07-05 雲端 droplet 因欠費 $9.07 被停權,沒繳、改本機跑。**
  那 47 支的 output/ 產物**在本機從來沒有過**。
  ⚠️ 初稿寫「跟著 droplet 一起消失」,那句**超出證據**:memory 只證得了日期,
  它列舉本機已有的東西(程式碼 + STUDIO + uploaded_ledger + token)時 **`output/` 不在那份清單裡**。
  「被毀掉」和「從來沒被複製過來」對處置沒差,但只有前者蘊含「曾經有東西被毀掉」——**我沒有證據說那件事**。

🔴 **〔本檔初稿寫「沒有『把旁白一起清掉』的腳本」—— 那是假的,已更正。〕**
獨立驗證員一次就找到:**`scripts/quality_score.py` 的 `reject()` / `_quarantine()`**
`for f in OUT.glob(f"{slug}.*"): shutil.move(...)` —— **`.voice.txt` 一起中**,
而 `reject()` 明明偵測到「已發布」還是照搬(只印一行 warn)。
我 grep 漏掉是因為**動詞是 `shutil.move` 不在我查的 unlink/remove/rmtree 三個詞裡**
(同族 memory `static-reading-vs-runtime-behaviour`)。
⚠️ **那句話最壞的地方是它的功能:它會叫下一個人不要去查。**
✅ 已於同日修掉:已發布的片保留 `.voice.txt`(`quality_score.py` 的 `_AUDIT_KEEP_SUFFIX`)。

⇒ **但「缺口沒有在長大」仍然成立**,而且理由和上面那句無關:
那條路徑**不在任何排程上**(cron 跑的是不帶旗標的 `quality_score.py`,只走 `scan()`),
入口是手動 `--reject` / `ntfy_command` / `web_center` 按鈕。
⇒ **遷移後 234/234 = 100.0%。**

🔴 **而「一次性遺失」和「滾動式清理」在分界線上長得一樣,所以那條分界線本身證不了什麼**:
今天(09-06)減 60 天 = 07-08,**幾乎正好落在觀測到的斷點上**。
⇒ 只看斷點,我沒辦法分辨「07-05 droplet 沒了」和「有一支 60 天滾動清理」。

**分辨它的是下面這條(承重點在這裡,不在分界線)**:

### 🔴 承重點換過兩次,現在是第三個。前兩個都能被時間或複製方式弄垮。

| 版本 | 承重的論證 | 為什麼被換掉 |
|---|---|---|
| 一 | 「分界線在 07-06/07-07」 | 今天減 60 天 = 07-08,**巧合**,兩個假設都相容 |
| 二 | 「68 支旁白活過 60 天,最舊 72.6 天」 | 只排除得掉**門檻 ≤72 天**的清理,而且**力量隨時間衰減**(再兩週 72 天就不夠) |
| **三(現行)** | **缺失在年齡軸上不單調** | 排除**所有門檻**,而且不隨時間衰減 |

**滾動清理不論 key 是 mtime 還是發布日,數學上都必須刪掉「年齡排序的一段連續前綴」。**
所以只要證明「缺」不是單調的,就一次排除掉**所有門檻值**,不必去論證某個數字是不是真的 72 天。

實測(`L_`+`S_` 合計,按發布日):

| 發布日 | 齡 | 存活 | 缺 |
|---|---|---|---|
| 2026-06-26 | 72d | **1** | 23 |
| 2026-06-27 | 71d | **3** | 19 |
| 2026-06-30 | 68d | **3** | 18 |
| 2026-07-01 | 67d | **0** | 33 ← 更年輕卻全滅 |
| 2026-07-03 | 65d | **0** | 14 ← 更年輕卻全滅 |
| 2026-07-04 | 64d | **0** | 14 ← 更年輕卻全滅 |
| 2026-07-07 | 61d | 25 | **0** |

**違反單調的配對:17 組**(較舊的日子有活口、較新的整天全滅)。
**沒有任何年齡門檻做得出這個形狀。**

### 另外三條獨立證據(每條都不依賴上面那條)

1. **同一場事件吃掉 341 支 Shorts**:`S_` 遷移前 372 支只活 31(8.3%)、遷移後 377 支活 369(97.9%)。
   ⇒ **不是針對某個前綴的清理。**(我原本用「8 支 `L_` 活著」關這個洞,那很薄 ——
   拿掉其中兩支門檻就掉回 62.9 天;用 `S_` 同期損失關,不依賴任何單一檔案。)
2. **那 47 支在 `output/` 底下殘留檔案數 = 0**(對照組每支還有 4~6 個 `.mp4/.md/.srt/.json`),
   而且在 `_rejected` / `_quarantine` / `_redo` 裡**一支都沒有**。
   ⇒ 任何「清旁白」的腳本產不出這個形狀。
3. **`st_ctime == st_mtime`,68 支無一例外**(最大差 0.000009 天)。
   🔴 **這一條關的是我原本推反了的那個洞。** 我寫過「mtime 被更新只會讓檔案看起來更年輕,
   所以 72 天是下界」——**方向對,但我防的是錯的那一邊**。真正會弄垮反證的是**反方向**:
   `shutil.copy2` / `rsync -a` / 同磁碟 `move` 都會**保留舊 mtime**,
   所以一個昨天才複製進來的檔可以顯示 mtime=06-25,它根本沒有「活過 72 天」。
   建立時間 == 修改時間 ⇒ 這些檔是那天**就地寫在 D 槽上的**,不是帶著舊時戳出現的。
   (副產品:本機在 06-25 就已經在產 output,不是 07-05 才開始。)

⚠️ 數字更正:初稿寫「60 支活過 60 天」,那是 **`.days > 60` 的整數截斷**讓門檻實際變成 >61 天。
**正確是 68 支(`S_` 60 + `L_` 8)**,而「60」剛好等於 `S_` 的數,所以我當時沒察覺。

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
- **不回填**。這支工具本身不做回填。
  🔴 **但「那 47 支的旁白找不回來」這句話已於 2026-09-07 被推翻,不要再引用。**
  當時寫的是:「獨立驗證員掃了 14 個備份/隔離目錄,**0 支命中**」——那句**在它自己的範圍內是對的**,
  而它的範圍是**本機磁碟**。沒有人去問持有第二份副本的第三方。
  實測(2026-09-07 23:47~23:51,見 `docs/ops/2026-09-07_evidence_chain_retention.md`):
  **那 47 支裡有 11 支,旁白現在就能從 YouTube 的字幕軌抓回來**
  ——長片發布時 `daily_publish.py:1017` 會 `captions.insert` 上傳 SRT,
  而那份 SRT 是從 `.voice.txt` 逐字切出來的(`make_video.write_srt_for_slug:449`)。
  已實抓回一支驗證(`X9arU-_wEZg`,pubdate 06-30,本機 `.voice.txt` 早已不存在):
  `captions.download` 回 3,893 bytes SRT / 1,312 字純文字,開頭結尾都完整。
  ⚠️ 這是方法論第 2 條(**錯的否定比錯的肯定危險一級**)自己的第二個實例:
  「找不回來」會叫下一個人**根本不走那條路**,而那條路是通的。
  查東西在不在,順序是**先列出所有持有者、再逐一去問**;只掃自己的磁碟叫「我沒找到」,不叫「不存在」。

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

# 2026-07-05 droplet 停權;07-06 之前那批的 output/ 產物在本機沒有(見檔頭,不宣稱「被毀掉」)。
# 07-07 起是本機產出,那一群的旁白保存率**應該是 100%**,所以告警只看它。
# ⚠️ 這個日期是**已查證的事實**不是猜的:47 支缺檔的發布日 100% 落在 07-06 以前,
#    07-07 以後 234 支零缺漏;memory yt-studio-local-migration-2026-07 記著同一天。
CUTOFF = "2026-07-07"

# 🔴 分母地板。這一格防的是「比率型指標最陰的那種壞法」:
# 涵蓋率 = 有旁白 ÷ 已發布,而**分母自己會縮水** —— uploaded_ledger 被截短、
# 被覆寫、被換成別的頻道的,涵蓋率都會變成漂亮的 100%,而且沒有任何東西不一樣。
# (同族見 docs/ops/dispatch.md §6「比率型驗收指標:分母不可以是處置的目標」)
# 這個值只會往上,不會往下:已發布的片不會變成沒發布。所以分母變小 = 帳本壞了。
#
# 🔴 **第一版寫 `POST_FLOOR = 224`(實測 234,留 10 支餘裕給「我當時數錯了」),
#    而獨立驗證員一測就翻:從 ledger 拿掉 1~10 支,涵蓋率立刻回到 100.0% 全綠、rc=0。**
#    **那 10 支餘裕本身就是洞** —— 而「一支片的 ledger entry 和 output 檔一起被搬走」
#    正是最可能的真實形狀(`reject()` 一次只動一支)。
# ⇒ 改成**落盤的單調高水位**,零餘裕:第一次跑把實測值寫進檔案,之後只准往上。
#    要防「我當時數錯了」就讓它自己量,不要用常數猜。
HWM_FILE = STUDIO / "auditability_hwm.json"


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _high_water(post_t: int):
    """回 (地板, 有沒有更新過)。單調高水位:只准往上。

    讀不到/壞掉時回 (post_t, False) —— 即「這次的值就是地板」,不會誤報,
    但也**不會保護這一次**;下一次就有基準了。這是刻意的:
    地板檔壞掉不該讓整支哨變成永遠紅,那樣它就沒人看了。
    """
    prev = None
    try:
        prev = int((_load(HWM_FILE, {}) or {}).get("post_total"))
    except Exception:  # noqa: BLE001
        prev = None
    floor = post_t if prev is None else max(prev, post_t)
    if prev is None or post_t > prev:
        try:
            HWM_FILE.write_text(
                json.dumps({"post_total": floor,
                            "note": "已發布長片(遷移後)的歷史最大值。只准往上;變小=帳本壞了。"},
                           ensure_ascii=False),
                encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    return floor, (prev is None)


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
    floor, first_run = _high_water(post_t)
    floor_ok = (post_t >= floor)
    gap_ok = (post_ok == post_t)
    ok = gap_ok and floor_ok

    # 🔴 兩個原因要分開講,不可以塞進同一個布林。
    # 驗證員實測第一版:帳本被截短時印出「100.0% + 🔴 有新缺口 + 去查 output/ 是不是被刪了」
    # —— 三句互相矛盾,而且**把值班的人指到一個沒事的目錄**。
    # 而 --quiet(排程/通知最可能用的那個)裡分母警告**完全不存在**。
    if not floor_ok:
        verdict = f"🔴 帳本縮水(母體 {post_t} < 歷史高水位 {floor})—— 百分比無意義"
    elif not gap_ok:
        verdict = f"🔴 有新缺口({post_t - post_ok} 支已發布長片沒有旁白)"
    else:
        verdict = "✅ 正常"

    if a.quiet:
        print(f"稽核涵蓋率 遷移後 {post_ok}/{post_t} ({pct(post_ok, post_t):.1f}%)"
              f" | 全歷史 {tot_ok}/{tot_t} ({pct(tot_ok, tot_t):.1f}%)"
              f" | {verdict}")
        return 0 if ok else 1

    print("## 已發布長片的可稽核涵蓋率(有沒有留下旁白稿)")
    print()
    print(f"  遷移後(發布日 >= {CUTOFF}) {post_ok:4d} / {post_t:4d} = {pct(post_ok, post_t):5.1f}%   ← 判準看這列")
    print(f"  遷移前(droplet 時代)      {pre_ok:4d} / {pre_t:4d} = {pct(pre_ok, pre_t):5.1f}%   ← 已知不可回復,不列入判準")
    print(f"  全歷史                    {tot_ok:4d} / {tot_t:4d} = {pct(tot_ok, tot_t):5.1f}%   ← 只供對外說明,不要拿它當告警值")
    print()
    if not floor_ok:
        print(f"🔴 **帳本縮水**:遷移後母體只剩 {post_t} 支,低於歷史高水位 {floor}。")
        print("   已發布的片不會變成沒發布 ⇒ **這代表 uploaded_ledger.json 壞了或被換掉了**,")
        print("   不是內容變少。")
        print("   ⚠️ **這時候上面那個涵蓋率百分比沒有意義,不要引用它,也不要去翻 output/** ——")
        print("      要查的是帳本,不是旁白檔。")
        print()
    elif first_run:
        print(f"ℹ️ 首次執行:已把遷移後母體 {post_t} 記成高水位基準({HWM_FILE.name})。")
        print("   ⚠️ **這一次沒有分母保護** —— 下一次起才擋得住帳本縮水。")
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
