#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""帳本 ↔ 平台對帳（**唯讀**，不提交、不模擬、不寫帳本）。

## 為什麼需要這支
`pick_next.py` 的候選池是 `B.load_ledger()`，也就是說**帳本看不到的 alpha，
整條產線就永遠選不到它**——即使它已經在平台上、已經跑完、且全部 checks 通過。
2026-09-05 對帳查出 199 條這種 alpha，其中 4 條 checks 零 FAIL，最高 Sharpe 2.35
（對照：已提交 13 條的最高是 2.40）。詳見 `docs/ledger-platform-gap-20260905.md`。

## 平台端點的硬限制
`/users/self/alphas` 單一 query **最多只回前 1,000 條**（超過回 HTTP 400），
所以要用 `dateCreated` 區間切片抓，count > 950 就對半再切。

## 用法
    python reconcile.py                 # 印摘要
    python reconcile.py --dump out.json # 另存缺口明細
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain_auto as B  # noqa: E402

ROOT = Path(__file__).resolve().parent
LEDGER = ROOT / "auto_ledger.jsonl"
START = dt.datetime(2026, 8, 25)          # 帳號建立於 2026-08-26 10:57 ET


def _get(s, url):
    """401 換 token、429 退避；其餘狀態碼直接拋（不吞、不沿用前一筆）。"""
    for _ in range(10):
        r = s.get(url, timeout=90)
        if r.status_code == 200:
            return s, r.json()
        if r.status_code == 429:
            time.sleep(15); continue
        if r.status_code == 401:
            s = B.auth(); continue
        raise RuntimeError(f"HTTP {r.status_code} {r.text[:200]} @ {url}")
    raise RuntimeError(f"重試用盡 @ {url}")


def _rng(a: dt.datetime, b: dt.datetime) -> str:
    return (f"dateCreated%3E={a:%Y-%m-%dT%H:%M:%S}-04:00"
            f"&dateCreated%3C{b:%Y-%m-%dT%H:%M:%S}-04:00")


def fetch_platform(s, verbose=True) -> dict:
    out: dict = {}

    def walk(a, b):
        nonlocal s
        q = _rng(a, b)
        s, j = _get(s, f"{B.API}/users/self/alphas?limit=1&{q}")
        c = j["count"]
        if c == 0:
            return
        if c > 950:                        # 單 query 上限 1,000，留餘裕
            mid = a + (b - a) / 2
            walk(a, mid); walk(mid, b); return
        off = 0
        while off < c:
            s, j = _get(s, f"{B.API}/users/self/alphas?limit=100&offset={off}&{q}")
            res = j.get("results") or []
            if not res:
                break
            for al in res:
                st = al.get("settings") or {}
                out[al["id"]] = {
                    "dc": al.get("dateCreated"), "status": al.get("status"),
                    "delay": st.get("delay"), "universe": st.get("universe"),
                    "decay": st.get("decay"), "nz": st.get("neutralization"),
                    "code": (al.get("regular") or {}).get("code"),
                    "sharpe": (al.get("is") or {}).get("sharpe"),
                    "fitness": (al.get("is") or {}).get("fitness"),
                    "fails": [c2["name"] for c2 in ((al.get("is") or {}).get("checks") or [])
                              if c2.get("result") == "FAIL"],
                }
            off += 100
        if verbose:
            print(f"  {a:%m-%d %H:%M}..{b:%m-%d %H:%M} count={c} total={len(out)}", flush=True)

    d = START
    end = dt.datetime.utcnow() - dt.timedelta(hours=4) + dt.timedelta(days=1)
    while d < end:
        walk(d, d + dt.timedelta(days=1))
        d += dt.timedelta(days=1)
    return out


def load_ledger_rows():
    rows, bad = [], 0
    for ln in LEDGER.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:  # noqa: BLE001  併發寫入交錯造成的壞行，如實計數不靜默丟棄
            bad += 1
    return rows, bad


def _norm(x: str | None) -> str:
    return " ".join((x or "").split())


def classify(plat: dict, rows: list) -> dict:
    """對每條「平台有、帳本沒有」的 alpha，指出帳本裡對應的那一列是怎麼記的。

    比對鍵用 (expr, decay, neutralization) —— 只比 expr 會把不同 decay 的變體混在一起。
    """
    ids = {r["alpha_id"] for r in rows if r.get("alpha_id")}
    kmap = collections.defaultdict(list)
    for r in rows:
        kmap[(_norm(r.get("expr")), r.get("settings_decay"), r.get("nz"))].append(r)

    miss = sorted(set(plat) - ids, key=lambda a: plat[a]["dc"])
    detail = []
    for a in miss:
        p = plat[a]
        hits = kmap.get((_norm(p["code"]), p["decay"], p["nz"]), [])
        if not hits:
            why = "帳本完全沒有這條（本帳本以外的工具產生）"
        elif any(h.get("ok") for h in hits):
            why = "帳本有同鍵的成功列但 alpha_id 不同（同一式子跑了兩次）"
        else:
            e = str(hits[0].get("error"))
            if "Location" in e:
                why = "帳本記成「無有效 Location」"
            elif "401" in e:
                why = "帳本記成 poll 401"
            elif "WARNING" in e:
                why = "帳本記成 status=WARNING（平台仍建立了 alpha）"
            elif "status=None" in e:
                why = "帳本記成 status=None"
            else:
                why = f"帳本記成其他錯誤：{e[:60]}"
        detail.append({"id": a, **p, "why": why})
    return {
        "platform_total": len(plat),
        "ledger_unique_alpha_id": len(ids),
        "ledger_only": sorted(ids - set(plat)),   # 帳本有平台沒有 → 應為 0
        "missing": detail,
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    s = B.auth()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    plat = fetch_platform(s)
    rows, bad = load_ledger_rows()
    rep = classify(plat, rows)

    print(f"\n對帳時間（台北）{now}")
    print(f"平台 alpha 總數      {rep['platform_total']}")
    print(f"帳本唯一 alpha_id    {rep['ledger_unique_alpha_id']}（壞行 {bad}）")
    print(f"平台有、帳本沒有     {len(rep['missing'])}")
    print(f"帳本有、平台沒有     {len(rep['ledger_only'])}")

    print("\n按原因：")
    for w, n in collections.Counter(m["why"] for m in rep["missing"]).most_common():
        print(f"  {n:4d}  {w}")

    clean = [m for m in rep["missing"] if not m["fails"] and m["sharpe"] is not None]
    clean.sort(key=lambda m: -m["sharpe"])
    print(f"\n其中 checks 零 FAIL（產線永遠選不到的合格品）{len(clean)} 條：")
    for m in clean:
        print(f"  {m['id']}  {m['dc'][:16]}  sharpe {m['sharpe']}  fitness {m['fitness']}")

    if "--dump" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--dump") + 1])
        out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n明細 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
