#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_binge_split_disclaimer.py — 一次性:把 38 支「誠信加註被追劇區塊劈成兩半」的描述修回來。

## 缺陷實況(2026-08-22 獨立審核指出,已用 desc_backup 離線蓋棺)
2026-08-21 的順序是:先跑 fix_period_disclaimer.py 把 📌 誠信加註 **prepend** 到描述最上面
(第 0 行是標題「📌 關於片中與 0050 的比較」,第 1~3 行是說明正文),接著 15:01~15:04 跑
binge_chain.py。當時 binge 的插入規則是「插在第一個非空行**之後**」——於是追劇區塊
不偏不倚插進了 📌 的標題與正文之間:

    📌 關於片中與 0050 的比較        ← 標題
    ━━━━━━━━━━━
    ▶ 接著看下一集:…               ← 追劇區塊硬生生插在中間
    ━━━━━━━━━━━
    片中提到「同期 0050」的報酬…      ← 正文被推到區塊下面,跟標題斷開

讀者看到的是「📌 關於片中與 0050 的比較」後面接著別的東西——誠信加註是為了認錯而寫的,
被劈開等於認錯認一半,比不加還糟。**證據**:38 支的 desc_backup(📌 插入前的原文)
零支含追劇區塊 → 證明 binge 是後到的那個。

## 為什麼不會自癒
binge state 的 done[vid].next == 目前鏈上的 next → 每日 17:05 重跑時直接跳過;
就算重觸,走的也是 replaced 路徑(原地換內容、不搬位置)。結構上不會自己好,只能一次性修。
根因已在 binge_chain.py:240 堵掉(第一行是 📌 就改插在它**前面**),本腳本只清歷史。

## 修法(insertion-only 原則的逆操作,一樣保守)
1. videos.list 取現況描述(38 支一次 list = 1 unit)。
2. 用 binge_chain 自己的 BLOCK_RE/STRICT_BLOCK_RE 定位區塊——**被人改過的區塊一律跳過**
   (fullmatch 不符 = 不是我們插的那個標準區塊,不碰)。
3. 拿掉區塊 → 檢查「📌 標題的下一個非空行必須是 📌 的說明正文」(真的接回去了才算修好)。
4. 用 binge_chain.apply_block() 現行(已修好的)規則重新插入 → 區塊會落在 📌 整段之前。
5. 還原檢查:新描述拿掉區塊後,必須逐字等於舊描述拿掉區塊後。不等就跳過該支。
6. videos.update(50 units/支)。全程 snippet 完整回填(update 是全欄覆蓋,漏欄=清空)。

備份:每支的改前 snippet 寫進 STUDIO/desc_backup_bingesplit/<vid>.json(與既有備份區分開,
不覆蓋 fix_period_disclaimer 的那份原始備份)。

用法:
  python scripts/fix_binge_split_disclaimer.py            # dry-run,印前後對照,不寫
  python scripts/fix_binge_split_disclaimer.py --limit 1 --apply   # 先修 1 支上線目視
  python scripts/fix_binge_split_disclaimer.py --apply    # 全批(~1,900 units)
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

STUDIO = ROOT / "STUDIO"
BK = STUDIO / "desc_backup_bingesplit"
MARK = "📌 關於片中與 0050 的比較"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    import binge_chain as bc
    import daily_publish as dp

    vids = json.loads((STUDIO / "period_disclaimer_done.json").read_text(encoding="utf-8"))
    if args.limit:
        vids = vids[:args.limit]
    if not vids:
        print("沒有待修影片")
        return 0

    yt = dp.get_service()
    # 取現況(50 支一批 = 1 unit)
    items = []
    for i in range(0, len(vids), 50):
        r = yt.videos().list(part="snippet", id=",".join(vids[i:i + 50])).execute()
        items += r.get("items", [])
    print(f"取回 {len(items)}/{len(vids)} 支現況\n")

    stats = {"fixed": 0, "skip_no_block": 0, "skip_not_split": 0,
             "skip_malformed": 0, "skip_restore": 0, "err": 0}
    for it in items:
        vid = it["id"]
        sn = it["snippet"]
        desc = sn.get("description") or ""
        title = (sn.get("title") or "")[:30]

        if MARK not in desc:
            stats["skip_no_block"] += 1
            continue
        m = bc.BLOCK_RE.search(desc)
        if not m:
            print(f"[skip] {vid} 找不到追劇區塊(可能還沒插) {title}")
            stats["skip_no_block"] += 1
            continue
        if not bc.STRICT_BLOCK_RE.fullmatch(m.group(0)):
            # 被人手動改過的區塊不碰——同 binge_chain 的既有防線,避免吞掉使用者原文
            print(f"[skip] {vid} 區塊不符標準模板(被改過?) {title}")
            stats["skip_malformed"] += 1
            continue

        block = m.group(0)
        # 判定「真的被劈開」:區塊出現在 📌 標題之後、而 📌 說明正文又在區塊之後
        i_mark = desc.index(MARK)
        if not (m.start() > i_mark and m.end() < len(desc)):
            stats["skip_not_split"] += 1
            continue
        head_after_mark = desc[i_mark + len(MARK):m.start()].strip()
        if head_after_mark:
            # 標題與區塊之間還有正文 = 沒被劈開(📌 整段完整),不動
            print(f"[skip] {vid} 加註未被劈開,不動 {title}")
            stats["skip_not_split"] += 1
            continue

        # 拿掉區塊 → 應還原成「📌 整段連續」的樣子。
        # 🔴 獨立驗證員實測抓到:第一版寫 `naked.replace("\n\n\n","\n\n")` 是**全域**替換,
        #    會順手收掉描述後段**使用者自己文案裡**的空行(38 支中 6 支中招,有一支被收掉 2 處);
        #    而下面的還原檢查用 `.replace("\n","")` 把所有換行都刪掉再比,**結構上看不見**這種改動。
        #    改成只正規化「📌 標題後面那個接縫」,其餘一個字元都不碰。
        naked = bc.BLOCK_RE.sub("", desc, count=1)
        _i = naked.index(MARK) + len(MARK)
        _j = _i
        while _j < len(naked) and naked[_j] == "\n":
            _j += 1
        naked = naked[:_i] + "\n" + naked[_j:]
        after = naked[_i:].lstrip("\n")
        if not after.strip():
            print(f"[skip] {vid} 拿掉區塊後 📌 沒有正文,異常不碰 {title}")
            stats["skip_restore"] += 1
            continue

        new_desc, action = bc.apply_block(naked, block)
        if not new_desc:
            print(f"[skip] {vid} 重新插入失敗({action}) {title}")
            stats["skip_restore"] += 1
            continue
        # 還原檢查:兩邊各自拿掉區塊後必須一致(只容忍空行差異)
        a = bc.BLOCK_RE.sub("", new_desc, count=1).replace("\n", "").strip()
        b = bc.BLOCK_RE.sub("", desc, count=1).replace("\n", "").strip()
        if a != b:
            print(f"[skip] {vid} 還原檢查不過(內容會被改動) {title}")
            stats["skip_restore"] += 1
            continue
        if len(new_desc) > 4990:
            print(f"[skip] {vid} 描述超長 {title}")
            stats["skip_restore"] += 1
            continue

        if not args.apply:
            # 🔴 只印前 3 行是不夠的:驗證員抓到的空行誤傷正好在描述後段,前 3 行完全看不到。
            #    改印**逐行 diff**(含空行,用 repr 讓看不見的字元現形)。
            import difflib
            print(f"[dry] {vid} {title}")
            d = [l for l in difflib.unified_diff(
                desc.split("\n"), new_desc.split("\n"), lineterm="", n=1)][2:]
            if not d:
                print("      (無差異)")
            for l in d[:14]:
                print("      " + (repr(l) if l.strip() in ("+", "-") else l[:96]))
            if len(d) > 14:
                print(f"      …(共 {len(d)} 行差異)")
            stats["fixed"] += 1
            continue

        try:
            BK.mkdir(parents=True, exist_ok=True)
            (BK / f"{vid}.json").write_text(json.dumps(sn, ensure_ascii=False), encoding="utf-8")
            # 🔴 fail-closed:categoryId 原本寫 sn.get("categoryId","22") ——一旦哪支缺這欄,
            #    就會**靜默**把影片分類改成 22(People & Blogs)。這 38 支實際都是 27(教育),
            #    但預設值本身是地雷。缺欄就直接跳過該支,不猜。
            if not sn.get("categoryId"):
                print(f"[skip] {vid} 缺 categoryId,不猜分類 {title}")
                stats["skip_restore"] += 1
                continue
            body = {
                "id": vid,
                "snippet": {
                    "title": sn.get("title"), "description": new_desc,
                    "categoryId": sn.get("categoryId"),
                    "tags": sn.get("tags"),
                    "defaultLanguage": sn.get("defaultLanguage"),
                },
            }
            # tags 是 None(API 沒回)就不送,讓 YouTube 保留原值;是 [] 代表本來就沒有,照送。
            body["snippet"] = {k: v for k, v in body["snippet"].items() if v is not None}
            yt.videos().update(part="snippet", body=body).execute()
            stats["fixed"] += 1
            print(f"✅ {vid} 已修 {title}")
        except Exception as exc:  # noqa: BLE001
            stats["err"] += 1
            print(f"[err] {vid} {str(exc)[:120]}")
            if "quota" in str(exc).lower():
                print("配額用盡,停止(已修的不受影響,剩下的下次跑)")
                break

    print(f"\n結果:{stats}")
    if args.apply and stats["fixed"]:
        try:
            from ops import log_ops
            log_ops("加註劈開修復", f"修好 {stats['fixed']} 支(追劇區塊移出 📌 段落)")
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
