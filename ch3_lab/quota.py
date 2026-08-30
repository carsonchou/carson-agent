#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quota.py — ch3 三支發布器共用的配額帳。

## 為什麼需要共用一本帳
`upload.py` / `publish_shorts.py` / `publish_comp.py` 各自估自己那批要花多少,
**互相看不見**。而排程一天跑兩個時段,每個時段又跑這三支 —— 於是每一支
都覺得自己「還有 10,000 可用」。真實情況是它們共用同一個每日額度。

舊版的保護方式是把每支片一律估成最壞情況(1,691),上限因此卡在 5 支。
那個保守本身沒錯 —— **用最好情況編預算,一支處理得慢就會超,而超的
那一刻是在第 6 支的 1,600 已經燒掉之後**。但代價是永遠只能發 5 支。

正解是記帳:每支片**依型態**估、發完就記,額度不夠就停在下一支之前。
這樣 Shorts(不設縮圖、輪詢少)真的比較便宜這件事才拿得到好處。

## 配額日的邊界不是午夜
實測與記憶都指向:**台北時間 15:00~16:00 之間重置**(那是太平洋時間的
午夜)。所以帳本以 **16:00 台北**為換日點 —— 用午夜換日會讓 16:25 那一
輪的花費算到前一天,而它其實是新一天的第一筆。

## 單價(YouTube 官方表)
`videos.insert` 1,600 / `thumbnails.set` 50 / `videos.list`、`playlistItems.*`
list 1、insert 50 / `channels.list` 1。

用法(程式內):
    import quota
    if not quota.can(quota.SHORT):
        ...停下來
    quota.spend(quota.SHORT, "ep013")

用法(看帳):
    python quota.py
"""
import json
import pathlib
import sys
from datetime import datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parent
STATE = ROOT / "quota.json"
#: 每日配額上限。**這個數字是量出來的,不是預設值。**
#: 🔴 舊版寫死 10,000(Google 專案的預設值),而兩條獨立實測都推翻它:
#:    · ch3 自己:配額日 2026-08-28 實際發了 1 長 + 12 短 = **20,935 單位**
#:      (台北 08-28 16:25 ~ 08-29 03:05,那些片現在都還在線上)
#:    · memory yt-quota-budget-2026-07:2026-07-30 主頻道實測 **≥18,000**
#:    於是「一天最多 6 支」這個我一直拿來做決定的數字,其實是**我們自己
#:    設的預算**造成的,不是 API 的限制。而 memory 的原話是
#:    「真瓶頸是可發庫存不是配額」。
#: ⚠️ 獨立驗證推翻了上面第二條:memory 那個 ≥18,000 量的是**主頻道的
#:    專案**(524513894332),而 ch3 跑在 881902283633,08-20 才切過去、
#:    從來沒送過提額申請。所以只剩證據 1。
#: 🔴 而 18,000 是三個選項裡最差的:13×1600 = 20,800 > 18,000,
#:    它**重現不了它自己引用的那個觀測**。改成 20,800 ——
#:    這是這個專案唯一直接量到的數字,而且明確是**下界**。
#:    真上限如果更低,下一次 403 會免費地、大聲地告訴我們。
DAILY = 20800
#: 留給雜項的預留額度:播放清單同步、健檢、狀態查詢、失敗重試。
#: 實測一天的雜項約 60~120。留 300 而不是更多,是因為 6 支/天需要
#: 9,636,再多留就發不到 6 支 —— 但也不能不留:超額那一刻是在最後
#: 一支的 insert 已經燒掉 1,600 之後,而那 1,600 拿不回來。
RESERVE = 300

#: 各型態的**最壞情況**成本。估貴不估便宜:低估的代價是超額,
#: 而超額發生在錢已經花掉之後。
SHORT = 1600 + 6                  # insert + 最多 6 次輪詢(不設縮圖)
LONG = 1600 + 50 + 13             # insert + 縮圖 + 最多 12 次輪詢 + 回讀
COMP = 1600 + 50 + 13
MISC = 60                         # 一輪排程的雜項
#: 改**已上線**影片的兩種寫入。兩者都不便宜,而且以前**完全沒有記帳**:
#: retitle / push_thumbs 各推 12 支就是 1,200 沉在帳外,接著發布端以為
#: 額度還在,一路發到 403。這正是 memory 記的結構性超支模式
#: (yt-api-quota-structural-overrun)——不是用太多,是有人沒記帳。
TITLE = 50                        # videos.update
THUMB = 50                        # thumbnails.set


def _day():
    """配額日。台北 16:00 換日 —— 見上面的說明。"""
    now = datetime.now()
    return (now - timedelta(hours=16)).strftime("%Y-%m-%d")


def _load():
    if not STATE.exists():
        return {"day": _day(), "spent": 0, "items": []}
    try:
        st = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        return {"day": _day(), "spent": 0, "items": []}
    if st.get("day") != _day():
        # 🔴 **`history` 要跨日保留。** 舊版換日回傳全新 dict,於是
        #    `note_exhausted()` 辛苦記下來的觀測值下一次 `spend()` 就被
        #    寫掉了 —— 量到的東西活不過換日,等於沒量。
        return {"day": _day(), "spent": 0, "items": [],
                "history": st.get("history", [])}
    return st


def remaining():
    return DAILY - RESERVE - _load()["spent"]


def can(cost):
    """還發得起這一支嗎。"""
    return remaining() >= cost


def spend(cost, label=""):
    """記一筆。**上傳成功之後才呼叫** —— 記早了會讓額度虛耗,
    記晚了(例如整批跑完才記)則失去逐支停下來的能力。"""
    st = _load()
    st["spent"] += cost
    st["items"].append({"at": datetime.now().strftime("%H:%M"),
                        "cost": cost, "what": label})
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(STATE)
    return remaining()


def report():
    st = _load()
    print(f"配額日 {st['day']}(台北 16:00 換日)")
    print(f"  已用 {st['spent']:,} / 可用 {DAILY - RESERVE:,}"
          f"(總額 {DAILY:,},預留 {RESERVE})")
    print(f"  還剩 {remaining():,} → 還能發 "
          f"{remaining() // SHORT} 支 Short 或 {remaining() // LONG} 支長片")
    for it in st["items"][-12:]:
        print(f"    {it['at']}  {it['cost']:>5,}  {it['what']}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    report()


def note_exhausted(label=""):
    """真的吃到 quotaExceeded 時記一筆。**這是唯一能量到真上限的方法。**

    寫死一個 DAILY 只能猜;被 API 擋下來的那一刻,今天到底花了多少是
    **觀測值**。記進帳本,下次就有真數字可以校準,而不是繼續猜。

    呼叫端:發布器 catch 到訊息含 "quota" 的例外時呼叫它,然後停。
    """
    st = _load()
    st["exhausted_at"] = st["spent"]
    st["exhausted_label"] = label
    st.setdefault("history", []).append(
        {"day": st["day"], "spent": st["spent"], "what": label})
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(STATE)
    print(f"  📏 配額在花掉 {st['spent']:,} 之後被擋 —— 已記進帳本。"
          f"目前 DAILY 設 {DAILY:,},下次可以照這個實測值校準。")
