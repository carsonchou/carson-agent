#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_engage_comments.py — 把線上「空頭承諾」互動留言換成該片的具體問題。

## 為什麼(2026-08-17)
daily_publish 的 _ENGAGE_QS 在 2026-07-18 和 08-12 兩度整改,砍掉承諾了產線做不到的
句子(「留言『數據』我私你」「夠多我就出深度版」「我統計結果下支公布」…)。判準當時
寫得很清楚:**句子裡承諾的後續動作,產線做不做得到?做不到=空頭支票**。
但兩次整改都**只改了產生端**——線上已經發出去的沒人回頭清。實測掃描:

    自己發的互動留言 357 則,其中 135 則仍是被砍掉的那些句型。
    「留言『數據』我私你」10 則、「留言『表』我發你」13 則——
    而 comment_dept 自己記著 tg_leads 累計 **0 筆**,交付機制從來沒運作過。

這跟同日抓到的章節問題是同一種病:修了工廠,沒回收已出廠的瑕疵品。

## 為什麼用 update 不用 delete
刪掉會連互動訊號一起丟(留言數是排序訊號),而問題出在**內容**不在留言本身。
改寫既拿掉失信、又留住訊號。comments.update 與 delete 同為 50 units,沒有成本差。

## 新文案怎麼來:從該片標題的真數據
順帶治重複——舊池只有 15 句配 357 則,單一句型重複到 28 次(「這題你站哪邊」),
那是機器人特徵,YouTube 的 spam 偵測看得到。新問題直接引用**該片標題裡的數字**
(標題數字是產線算出來、已過溯源閘門的),每則自然不同且與影片相關。
抽不出數字的片退回通用池,但至少不含承諾。

## 安全
- 原文全備份到 STUDIO/engage_backup/<commentId>.txt,可還原。
- 預設 dry-run;--max 控配額(50 units/則)。
- 只動**自己頻道自己發的**留言,且只動命中 DEAD 句型的那些。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STUDIO = ROOT / "STUDIO"
CH = "UCqP5JQXlQR5ZDLtEiBt4kLA"

# 產線已判定「產線兌現不了」的承諾句型(daily_publish._ENGAGE_QS 兩次整改的紀錄)
DEAD = ["我統計結果下支公布", "先訂閱，不然找不回來", "夠多我就出深度版", "揭曉在置頂",
        "下支我幫你回測哪個十年贏", "我出一支怎麼省的", "下支可能就拍你的問題",
        "我私你", "我發你"]

# 退路池:純討論誘導,零承諾(全部是產線不需要做任何後續動作的句子)
GENERIC = [
    "你會抱著、加碼、還是先出場？留個 A / B / C 👇",
    "這個回撤幅度，你撐得過去嗎？誠實留個數字 👇",
    "你手上有這檔嗎？留言說說你的成本區間 👇",
    "看到這個數字，你的第一反應是什麼？👇",
    "這種波動你能睡得著嗎？留言聊聊 👇",
]


def _question_for(title: str, vid: str) -> str:
    """從影片標題抽「股票識別 + 最醒目的數字」組成具體問題;抽不出退回通用池。"""
    t = re.sub(r"<[^>]+>", "", title or "")
    m = re.search(r"【([^】]{2,12})】", t)
    ident = m.group(1).strip() if m else ""
    # 兩種語序都要吃:「回撤71.8%」與「這-88.4%回撤」。只認前者會讓一半的標題
    # 抽不到代價數字,退回弱問法(旺宏「20年狂賺1496%?小心這-88.4%回撤」實測踩到)。
    # ⚠️ 誠信:**年化**報酬絕不可講成總報酬。「年化報酬24.8%」寫成「賺 24.8%」
    # 會被讀成 20 年只賺 24.8%,把一支好股講成爛股——反向的誇大一樣是失真。
    ann = re.search(r"年化(?:報酬(?:率)?)?\s*[-−]?\s*([\d.]+)\s*%", t)
    # 兩種語序都要吃:「回撤71.8%」與「這-88.4%回撤」「73%回撤」「10年套牢」。
    # 只認一種會讓一半標題抽不到代價數字,退回弱問法(旺宏／希華實測都踩到)。
    nums = (re.findall(r"(?:賺|漲|暴賺|暴漲|翻)\s*[-−]?\s*([\d.]+)\s*(%|倍)", t)
            + re.findall(r"總報酬\s*[-−]?\s*([\d.]+)\s*(%|倍)", t))
    drops = (re.findall(r"(?:回撤|暴跌|腰斬|套牢)\s*[-−]?\s*([\d.]+)\s*(%|年)", t)
             + re.findall(r"[-−]?\s*([\d.]+)\s*(%|年)\s*(?:的)?[^,，。!！?？]{0,4}?(?:回撤|暴跌|套牢)", t))
    if ident and nums and drops:
        a, au = nums[0]
        b, bu = drops[0]
        return (f"{ident}：{a}{'%' if au == '%' else '倍'}的報酬，"
                f"代價是{b}{'%' if bu == '%' else '年'}的{'回撤' if bu == '%' else '套牢'}。"
                f"這個你抱得住嗎？留言說實話 👇")
    if ident and drops:
        b, bu = drops[0]
        return (f"{ident}：{b}{'%' if bu == '%' else '年'}的"
                f"{'回撤' if bu == '%' else '套牢'}，換你抱得住嗎？留言說實話 👇")
    if ident and nums:
        a, au = nums[0]
        return f"{ident} 賺 {a}{'%' if au == '%' else '倍'}，你會現在進場還是等回檔？👇"
    if ident and ann:
        return f"{ident} 年化 {ann.group(1)}%，你覺得這是好還是普通？留言聊聊 👇"
    return GENERIC[sum(ord(c) for c in vid) % len(GENERIC)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max", type=int, default=20, help="本輪最多幾則(50 units/則)")
    args = ap.parse_args()

    import daily_publish as dp
    yt = dp.get_service()

    rows, tok, pages = [], None, 0
    while pages < 12:
        r = yt.commentThreads().list(part="snippet", allThreadsRelatedToChannelId=CH,
                                     maxResults=100, order="time", pageToken=tok).execute()
        for it in r.get("items", []):
            sn = it["snippet"]["topLevelComment"]["snippet"]
            author = sn.get("authorDisplayName", "")
            if "CarsonQuant" not in author and "量化阿森" not in author:
                continue
            txt = (sn.get("textDisplay") or "").replace("<br>", "\n")
            if any(d in txt for d in DEAD):
                rows.append((it["snippet"]["topLevelComment"]["id"],
                             it["snippet"].get("videoId"), txt))
        tok = r.get("nextPageToken")
        pages += 1
        if not tok:
            break
    print(f"命中空頭承諾句型:{len(rows)} 則")
    if not rows:
        return 0

    titles = {}
    ids = sorted({v for _, v, _ in rows if v})
    for i in range(0, len(ids), 50):
        rr = yt.videos().list(part="snippet", id=",".join(ids[i:i + 50])).execute()
        for it in rr.get("items", []):
            titles[it["id"]] = it["snippet"].get("title", "")

    bk = STUDIO / "engage_backup"
    bk.mkdir(exist_ok=True)
    n = 0
    for cid, vid, txt in rows:
        if n >= args.max:
            print(f"[quota] 達本輪上限 {args.max},其餘下次續")
            break
        # 保留原留言的「訂閱鉤/長片連結」段(那段沒有失信問題),只換問題句
        parts = txt.split("\n\n", 1)
        tail = parts[1].strip() if len(parts) > 1 else ""
        newq = _question_for(titles.get(vid, ""), vid or cid)
        new = f"{newq}\n\n{tail}".strip() if tail else newq
        if any(d in new for d in DEAD):
            print(f"  ⏭ {cid[:12]} 尾段本身含承諾,跳過待人工處理")
            continue
        print(f"\n  [{'改' if args.apply else 'dry'}] {(titles.get(vid) or vid or '')[:38]}")
        print(f"    舊:{parts[0][:56]}")
        print(f"    新:{newq[:56]}")
        if not args.apply:
            n += 1
            continue
        try:
            (bk / f"{cid}.txt").write_text(txt, encoding="utf-8")
            yt.comments().update(part="snippet",
                                 body={"id": cid, "snippet": {"textOriginal": new}}).execute()
            n += 1
        except Exception as exc:  # noqa: BLE001
            print(f"    [warn] {str(exc)[:120]}", file=sys.stderr)
    print(f"\n{'已改' if args.apply else '將改'} {n} 則(剩 {max(0, len(rows) - n)} 則下次續)")
    if args.apply:
        try:
            from ops import log_ops
            log_ops("留言整改", f"空頭承諾留言改寫 {n} 則")
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
