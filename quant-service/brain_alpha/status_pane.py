#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""status_pane.py — BRAIN 一眼看得完的狀態板（給 herdr 窗格常駐用）。

## 為什麼
這條線的狀態散在四個地方：平台分數、當日提交數、挖礦有沒有在動、
還剩幾條能交。要回答「現在怎樣」我每次都得跑四段查詢。
一個常駐窗格把它們併成一屏，Carson 掃一眼就知道，我也不用再查。

只讀不寫：兩個 GET，不佔那 2 個模擬併發槽。預設 5 分鐘刷一次。

## 時區（實測）
計分日分界 = ET 00:00 = 台北中午 12:00；結算落帳台北 15:54~16:00。

## 用法
    python -u status_pane.py            # 常駐
    python -u status_pane.py --once     # 印一次就結束
    python -u status_pane.py --every 120
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

ET = timezone(timedelta(hours=-4))
TPE = timezone(timedelta(hours=8))
TARGET = 2                      # 每日 2,000 分上限 ≈ 2 條
GOLD = 10000


def _bar(cur: float, top: float, width: int = 28) -> str:
    n = max(0, min(width, int(round(width * (cur / top)))))
    return "█" * n + "·" * (width - n)


def snapshot(B, s) -> dict:
    out = {"err": []}
    try:
        r = s.get(f"{B.API}/users/self/competitions", timeout=30)
        lb = ((r.json().get("results") or [{}])[0] or {}).get("leaderboard") or {}
        out["score"] = lb.get("score")
        out["rank"] = lb.get("rank")
    except Exception as e:                        # noqa: BLE001
        out["err"].append(f"competitions {e}")
    try:
        r = s.get(f"{B.API}/users/self/activities/submissions", timeout=30)
        out["records"] = (r.json().get("records") or {}).get("records") or []
    except Exception as e:                        # noqa: BLE001
        out["err"].append(f"submissions {e}")
    return out


def render(B, s) -> str:
    now_et = datetime.now(timezone.utc).astimezone(ET)
    now_tpe = datetime.now(TPE)
    today = now_et.strftime("%Y-%m-%d")
    eod = (now_et + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    left_h = (eod - now_et).total_seconds() / 3600

    d = snapshot(B, s)
    score = d.get("score")
    recs = d.get("records") or []
    done = sum(int(n) for x, n in recs if x == today)

    L = []
    L.append(f"  BRAIN   台北 {now_tpe:%m-%d %H:%M}   ET {now_et:%m-%d %H:%M}")
    L.append("  " + "─" * 46)
    if score is None:
        # fail-closed：查不到就講「查不到」，不要留一個看起來正常的舊數字
        L.append("  分數    ⚠️ 查不到（見下方錯誤）")
    else:
        L.append(f"  分數    {score:,.0f} / {GOLD:,}   rank {d.get('rank') or '?':,}")
        L.append(f"          {_bar(score, GOLD)}")
        if score >= GOLD:
            L.append("          🏆 GOLD 已達標")
        else:
            need = (GOLD - score) / 2000
            L.append(f"          還差 {GOLD - score:,.0f} 分 ≈ {need:.1f} 天")

    mark = "✅" if done >= TARGET else ("🚨" if left_h <= 4 else "⚠️")
    L.append(f"  今天    {mark} ET {today} 已交 {done}/{TARGET}"
             f"   換日剩 {left_h:.1f}h")
    L.append("  最近    " + "  ".join(f"{x[5:]}:{n}" for x, n in recs[-5:]))

    # 挖礦：帳本行數當進度計，比去掃程序列表便宜也不會誤判
    try:
        n = sum(1 for _ in open(B.LEDGER, encoding="utf-8", errors="ignore"))
        L.append(f"  帳本    {n:,} 行")
    except Exception:                             # noqa: BLE001
        pass
    for e in d["err"]:
        L.append(f"  ⚠️ {e}")
    return "\n".join(L)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                             # noqa: BLE001
        pass
    import brain_auto as B
    every = 300
    if "--every" in sys.argv:
        every = int(sys.argv[sys.argv.index("--every") + 1])
    once = "--once" in sys.argv
    s = B.auth()
    while True:
        try:
            body = render(B, s)
        except Exception as e:                    # noqa: BLE001
            body = f"  ⚠️ 取狀態失敗：{e}"
            try:
                s = B.auth()                      # token 過期就換一張
            except Exception:                     # noqa: BLE001
                pass
        print("\033[2J\033[H" + body, flush=True)
        if once:
            return 0
        time.sleep(every)


if __name__ == "__main__":
    raise SystemExit(main())
