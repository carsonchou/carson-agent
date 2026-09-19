#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""health.py — ch3 的每日健檢,對照主頻道的 `daily_health.py`。

## 為什麼需要
ch3 的排程 16:25 在**無人看管**下發片,而這條線先前**零監控** ——
排程壞掉、閘門把整批擋下、配額耗盡,都不會有任何人知道。主頻道有
`daily_health --notify` / `stall_watchdog` / `quota_budget --notify` 三層,
ch3 一層都沒有。

## 只在需要注意時吵你
每天照發是常態,不值得一則通知。這支只在下列情況推播:
- **有貨卻沒發**:昨天到今天帳本沒動,但庫存還有待發的
- **閘門把整批擋下**:一支都送不出去
- **產能見底**:待發不足三天
- **頻道數字倒退**:訂閱或觀看變少(通常是影片被下架或檢舉)

沒事的時候只寫一行到 stdout,不推播 —— **每天都響的警報等於沒有警報**。

用法:
  python health.py              # 檢查並在需要時推播
  python health.py --always     # 不管有沒有事都推播一次(用來驗管道)
"""
import argparse
import json
import pathlib
import sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
STATE = ROOT / "health_state.json"
EXPECT_CHANNEL = "UCbo4EytWhZ7zAGSoIPioJ5g"
LOW_STOCK_DAYS = 3          # 待發不足這麼多天就示警


def notify(title, msg):
    try:
        sys.path.insert(0, str(REPO / "youtube_channel" / "scripts"))
        import notify as n
        return bool(n.push(title, msg))
    except Exception as e:                                    # noqa: BLE001
        print(f"  (推播失敗:{str(e)[:60]})")
        return False


def led(name):
    p = ROOT / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--always", action="store_true")
    a = ap.parse_args()

    alarms, lines = [], []
    longs, shorts, comps = (led("uploaded.json"), led("uploaded_shorts.json"),
                            led("uploaded_comp.json"))
    total_pub = len(longs) + len(shorts) + len(comps)

    meta = json.loads((ROOT / "publish_meta.json").read_text(encoding="utf-8"))
    k = lambda o: o.get("slug") or o["dir"]
    # 🔴 「待發」要扣掉檔案不在的 —— 只比帳本會高估,而這個數字的用途
    #    正是判斷「產能夠不夠」,高估等於在空倉庫上做計畫。
    ready_long = [o for o in meta if k(o) not in longs
                  and (ROOT / o["video"]).exists()
                  and (not o.get("thumb") or (ROOT / o["thumb"]).exists())]
    # 🔴 `reels/` 和 `shorts/` 是**同一個發布管道** —— publish_shorts.py:607
    #    也收 reels/、:765 記進同一本 uploaded_shorts.json。只掃 shorts/ 的話,
    #    reels/ 有貨時這支會噴缺貨警報(2026-09-09 實測:7 支對健檢是隱形的)。
    #    ⚠️ 兩邊的帳本 key **不同形狀**:shorts 用裸目錄名,reels 用 `reel_` 前綴。
    #       前綴寫錯不會報錯,只會讓已發的那 7 支又被算成待發 —— 反方向的同一個病,
    #       而且從輸出上分不出來。改這裡要跑陽性對照(放一支假的進去,數字要跟著動)。
    #    口徑:這裡量的是**檔案層庫存**,不跑 reel_gate —— 與 shorts/ 同口徑。
    def _ready(sub, suffix, key):
        p = ROOT / sub
        if not p.is_dir():
            return []
        return [f"{sub}/{d.name}" for d in p.iterdir()
                if d.is_dir() and key(d.name) not in shorts
                and (d / f"{d.name}{suffix}").exists()]

    ready_short = (_ready("shorts", "_short.mp4", lambda n: n)
                   + _ready("reels", "_reel.mp4", lambda n: f"reel_{n}"))
    # 一天 1 長 + 4 短
    days_long = len(ready_long)
    days_short = len(ready_short) / 4
    lines.append(f"待發:長片 {len(ready_long)} 支(≈{days_long} 天)、"
                 f"Shorts {len(ready_short)} 支(≈{days_short:.1f} 天)")
    if min(days_long, days_short) < LOW_STOCK_DAYS:
        alarms.append(f"產能見底:長片剩 {days_long} 天、Shorts 剩 "
                      f"{days_short:.1f} 天(門檻 {LOW_STOCK_DAYS} 天)")

    prev = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    # 🔴 「有貨卻沒發」要跟**至少一個發布週期以前**的狀態比,不是跟「上次
    #    跑這支」比。排程一天發一次,而這支可能一天跑好幾次(或我手動跑)
    #    —— 拿幾分鐘前的快照當基準,就會在「兩次執行之間本來就不會發片」
    #    的正常情況下噴警報。實際踩到:改完立刻重跑,它就說有貨沒發。
    #    這跟 memory 那條「錨在 today 做週對週 = 拿 4 天比 7 天」同一個病:
    #    **比較窗口不對,兩邊的數字都是真的,結論是假的。**
    MIN_GAP_H = 20
    age_h = None
    if prev.get("when"):
        try:
            age_h = (datetime.now()
                     - datetime.fromisoformat(prev["when"])).total_seconds() / 3600
        except ValueError:
            age_h = None
    if (age_h is not None and age_h >= MIN_GAP_H
            and prev.get("total_pub") is not None
            and total_pub == prev["total_pub"]
            and (ready_long or ready_short)):
        alarms.append(f"**有貨卻沒發**:帳本自 {prev['when']} 起"
                      f"({age_h:.0f} 小時)沒有變動,仍有 "
                      f"{len(ready_long)}+{len(ready_short)} 支待發"
                      f" —— 排程可能沒跑,或閘門把整批擋下")
    elif age_h is not None and age_h < MIN_GAP_H:
        lines.append(f"(距上次檢查 {age_h:.1f} 小時,未滿 {MIN_GAP_H} 小時,"
                     f"不判斷「有貨沒發」)")

    ch = None
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        cr = Credentials.from_authorized_user_file(
            str(CH2 / "token.json"),
            ["https://www.googleapis.com/auth/youtube.readonly"])
        yt = build("youtube", "v3", credentials=cr, cache_discovery=False)
        c = yt.channels().list(part="statistics,snippet", mine=True).execute()["items"][0]
        if c["id"] != EXPECT_CHANNEL:
            alarms.append(f"頻道 ID 不符:{c['id']}")
        st = c["statistics"]
        ch = {"subs": int(st.get("subscriberCount", 0)),
              "views": int(st.get("viewCount", 0)),
              "videos": int(st.get("videoCount", 0))}
        lines.append(f"頻道:訂閱 {ch['subs']}、觀看 {ch['views']}、"
                     f"公開影片 {ch['videos']}")
        # ⚠️ **觀看數要留容差**。頻道層級的 viewCount 是彙總值,更新比
        #    逐支加總慢 —— 實測同一時刻頻道說 2、逐支加總是 6。沒有容差
        #    的話那個落差自己就會製造「觀看倒退」的假警報,而假警報會
        #    訓練人忽略真警報。
        #    訂閱與公開影片數沒有這個問題,少一個就是真的少一個
        #    (影片被下架、檢舉、或自己設成私人)。
        for key, label, tol in (("subs", "訂閱", 0), ("videos", "公開影片", 0),
                                ("views", "觀看", 3)):
            was = (prev.get("channel") or {}).get(key)
            if was is None:
                continue
            if ch[key] < was - tol:
                alarms.append(f"**{label}倒退**:{was} → {ch[key]}"
                              + (f"(容差 {tol})" if tol else ""))
            elif ch[key] > was:
                lines.append(f"  {label} +{ch[key] - was}")
    except Exception as e:                                    # noqa: BLE001
        # ⚠️ 查不到**不等於**沒問題,要說出來,不要用沉默假裝正常。
        alarms.append(f"頻道數字查不到({str(e)[:60]})—— 這不是綠燈,是沒查到")

    for ln in lines:
        print(f"  {ln}")
    for al in alarms:
        print(f"  ⚠️ {al}")

    STATE.write_text(json.dumps(
        {"when": datetime.now().isoformat(timespec="minutes"),
         "total_pub": total_pub, "channel": ch},
        ensure_ascii=False, indent=1), encoding="utf-8")

    if alarms or a.always:
        title = f"ch3 {'⚠️ ' + str(len(alarms)) + ' 項要注意' if alarms else '每日狀態'}"
        body = "\n".join(alarms + [""] + lines) if alarms else "\n".join(lines)
        ok = notify(title, body[:900])
        print(f"\n  推播{'成功' if ok else '失敗'}({len(alarms)} 項警報)")
    else:
        print("\n  一切正常,不推播(每天都響的警報等於沒有警報)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
