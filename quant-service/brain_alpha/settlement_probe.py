#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""settlement_probe.py — 結算前後各量一次，判「分數是否在 10,000 封頂」。

只讀 GET，不 simulate 不 submit。

## 為什麼要這支
score 現在正好 10000.0，而 11 條 alpha 分佈在 5 個計分日（2/3/2/2/2）
＝ 5 天 × 每日 2,000 上限。這個整數有兩種解釋而處置相反：
    每天剛好吃滿上限  → 繼續交仍有邊際價值
    分數在 10,000 封頂 → 金牌之後再交一條都是 0 分，整條產線邊際價值為零
09-01 交的兩條會在台北 15:54~16:00 結算進榜 —— **不必再交任何東西**就能得到答案。

## fail-closed
任何一次拿不到就寫 `問不到 HTTP xxx`，**不寫看起來正常的數字、不沿用前一筆**。
今天已經抓到同一個病的四個表面（帳本把沒跑的當跑過、守門認不出自己的程序、
分數 401 被吞、「已交 0 條」和「問不到」長一樣），不要在這裡長出第五個。

## `alphas` 要用哪個數字
`/users/self/alphas?limit=1` 回的是 **5,193**（含所有未提交的模擬結果），
`?status=ACTIVE` 才是已提交的 **13**。兩次讀數必須用同一個問法，否則不可比。

## 用法
    python -u settlement_probe.py --at 16:10      # 等到台北 16:10 再量
    python -u settlement_probe.py --now --tag pre
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
TPE = timezone(timedelta(hours=8))
LOG = ROOT / "SETTLEMENT_20260902.log"


def probe(B, tag: str) -> dict:
    out = {"tag": tag, "ts": datetime.now(TPE).isoformat(timespec="seconds")}
    try:
        s = B.auth()
    except Exception as e:                                   # noqa: BLE001
        out["error"] = f"問不到（認證失敗）：{e}"
        return out

    r = s.get(f"{B.API}/users/self/competitions", timeout=30)
    out["comp_http"] = r.status_code
    if not r.ok:
        out["comp"] = f"問不到 HTTP {r.status_code}"
    else:
        j = r.json()
        out["comp_count"] = j.get("count")
        ch = [x for x in (j.get("results") or []) if x.get("id") == "challenge"]
        if not ch:
            out["challenge_found"] = False
            for k in ("score", "rank", "alphas", "level"):
                out[k] = None                                # 空清單 = 查無，不是 0
        else:
            out["challenge_found"] = True
            lb = ch[0].get("leaderboard") or {}
            for k in ("score", "rank", "alphas", "level"):
                out[k] = lb.get(k)

    u = s.get(f"{B.API}/users/self", timeout=30)
    out["self_level"] = u.json().get("level") if u.ok else f"問不到 HTTP {u.status_code}"
    a = s.get(f"{B.API}/users/self/alphas?limit=1&status=ACTIVE", timeout=40)
    out["submitted_count"] = a.json().get("count") if a.ok else f"問不到 HTTP {a.status_code}"
    c = s.get(f"{B.API}/competitions/challenge", timeout=30)
    out["challenge_direct_http"] = c.status_code
    if c.ok:
        out["challenge_direct_lb"] = c.json().get("leaderboard")
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                        # noqa: BLE001
        pass
    import brain_auto as B

    tag = "probe"
    if "--tag" in sys.argv:
        tag = sys.argv[sys.argv.index("--tag") + 1]
    if "--at" in sys.argv:
        hh, mm = (int(x) for x in sys.argv[sys.argv.index("--at") + 1].split(":"))
        while True:
            now = datetime.now(TPE)
            if (now.hour, now.minute) >= (hh, mm):
                break
            print(f"  等 {hh:02d}:{mm:02d}，現在 {now:%H:%M:%S}", flush=True)
            time.sleep(60)
        tag = tag if tag != "probe" else f"at{hh:02d}{mm:02d}"

    rec = probe(B, tag)
    print(json.dumps(rec, ensure_ascii=False, indent=1), flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
