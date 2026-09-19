#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一次性:把 2026-08-31 被配額擋掉的那則回覆補發出去。

## 為什麼需要一支腳本

觀眾 @憂鬱-z4v 在雙鴻 3324 那支片下面留了「完全沒內容,不推薦」,來回幾輪之後
提出對整個產品的批評(「大家想要看的是公司的前景、未來的爆發力,你一直在過去股價
多少…到底要幹嘛??」)。我寫好回覆送出時撞上 403 配額用盡(當天已花 25,999),
**沒有發出去** —— 而從他那邊看,就是他丟出批評之後我就沒聲音了。

配額在台北 15:00 重置。這支排在 15:20 跑一次,補發完就把自己從 crontab 移除
(ONESHOT 標記)。不靠「我記得要發」。

## 回覆的內容為什麼是這樣

他要的是**預測**(前景/未來爆發力),那是這條線不能跨的:memory
youtube-ai-inauthentic-redline 與「介紹≠推薦」是生死線,而且我們也真的沒有預測能力。
所以第一段直說不做,並給出理由,不含糊。

但他講對一半:只放股價歷史確實薄。而基本面(營收/EPS/毛利率/本益比位置)是
「公司現在的狀況」不是預測,那條線我們可以走 —— 而且 2026-08-31 剛好把
「事實使用率 55% → 91%」那個瓶頸修掉(每檔 11 組事實原本只有一半進得了片子)。
所以第二段是有實質內容的回應,不是安撫。

## 冪等

發之前先讀該討論串,若已存在同開頭的回覆就跳過(避免我或排程重複發)。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

PARENT = "UgwhGB8o8ecuSqv2GgJ4AaABAg"      # @憂鬱-z4v 於 雙鴻3324(SMRvbJ3Jt1g)
MARK = "「未來的爆發力」我不會做"            # 冪等判準:這句開頭出現過就別再發

TEXT = (
    "你這句我收下。老實回你兩件事。\n\n"
    "「未來的爆發力」我不會做。那是預測,我沒有那個能力;真的說得準的人,"
    "也不會在 YouTube 上免費講。這條線跨過去,這頻道就沒有存在的理由了。\n\n"
    "但你講對一半:只放股價歷史確實太薄。每一檔我手上其實有 11 組資料,"
    "包含營收、EPS、毛利率、還有本益比現在落在自己歷史區間的哪個位置——"
    "那是公司「現在」的狀況,不是預測。問題是實測只有一半進得了片子,"
    "我這兩天剛把那個瓶頸修掉,現在會用到九成。\n\n"
    "你要的跟我能給的中間有一段距離,這我知道。謝謝你講得這麼直,比按讚有用。"
)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import daily_publish as dp
    yt = dp.get_service()

    # 冪等:先看這串裡有沒有已經發過
    try:
        r = yt.comments().list(part="snippet", parentId=PARENT,
                               maxResults=50, textFormat="plainText").execute()
        for it in r.get("items", []):
            if MARK in (it["snippet"].get("textDisplay") or ""):
                print("[skip] 這則回覆已經在串上了,不重複發。")
                return 0
    except Exception as exc:  # noqa: BLE001
        # 讀不到就別硬發 —— 寧可下次再試,也不要因為讀失敗而重複發一次
        print(f"[abort] 讀不到討論串,本次不發(下個排程再試):{str(exc)[:120]}",
              file=sys.stderr)
        return 1

    try:
        res = yt.comments().insert(
            part="snippet",
            body={"snippet": {"parentId": PARENT, "textOriginal": TEXT}},
        ).execute()
    except Exception as exc:  # noqa: BLE001
        # 不要噴 traceback 就算了:這支是**每天重試**的(見 crontab 說明),
        # 失敗只要說清楚原因、回非零,明天同一時間再試。
        _q = "配額" if "quota" in str(exc).lower() else "其他錯誤"
        print(f"[retry] 送出失敗({_q}),明天 15:20 再試:{str(exc)[:120]}", file=sys.stderr)
        return 1
    print("✅ 已補發,id:", res.get("id"))
    try:
        from ops import log_ops
        log_ops("留言部門", "已補發 08-31 被配額擋下的回覆(@憂鬱-z4v / 雙鴻3324)")
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
