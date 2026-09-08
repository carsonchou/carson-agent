#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""帳本 ↔ 平台對帳（**唯讀**，不提交、不模擬、不寫帳本）。

## 為什麼需要這支
`pick_next.py` 的候選池是 `B.load_ledger()`，也就是說**帳本看不到的 alpha，
整條產線就永遠選不到它**——即使它已經在平台上、已經跑完、且全部 checks 通過。
2026-09-05 對帳查出 199 條這種 alpha，其中 4 條 checks 零 FAIL，最高 Sharpe 2.35
（對照：已提交 13 條的最高是 `wpjQpqJ6` 的 2.40；2.35 與已交的 `LL7rbXY6` 同分）。詳見 `docs/ledger-platform-gap-20260905.md`。

## 讀取時滯（**看到非 0 先別當異常**）
列舉一輪要 ~10 分鐘，而 miner 一直在產（平均約 0.4 條/分）。列舉開始後才產出的 alpha
會**先進帳本、還沒被掃到**，於是「帳本有、平台沒有」出現非 0。2026-09-05 實測到 1 條
（`om6Ql5Zm`，ET 09-04 22:51 建立，單獨 `GET /alphas/{id}` 回 200）。
⇒ 非 0 時逐條打 `GET /alphas/{id}`；回 200 就是時滯，不是缺漏。

## 平台端點的硬限制
`/users/self/alphas` 單一 query **最多只回前 1,000 條**（超過回 HTTP 400），
所以要用 `dateCreated` 區間切片抓，count > 950 就對半再切。

## 用法
    python reconcile.py                 # 印摘要
    python reconcile.py --dump out.json # 另存缺口明細
    python reconcile.py --snapshot      # 只存平台快照（挑片器的候選池來源之一）
    python reconcile.py --snapshot --report  # 兩件都做
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import os
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


def fetch_platform(s, verbose=True, totals: dict | None = None) -> dict:
    """列舉全庫。`totals` 給了的話,把**平台自報的 count 加總**寫進去
    (`totals["expected"]`)—— 那是唯一能事後判斷「這輪有沒有少抓」的憑據:
    下面的分頁迴圈碰到空頁就 `break`,**少抓不報錯**,而一份殘缺快照對讀取端
    長得跟完整的一模一樣(2026-09-08 獨立驗證員抓到)。
    """
    out: dict = {}
    expected = 0

    def walk(a, b):
        nonlocal expected, s
        q = _rng(a, b)
        s, j = _get(s, f"{B.API}/users/self/alphas?limit=1&{q}")
        c = j["count"]
        if c == 0:
            return
        if c > 950:                        # 單 query 上限 1,000，留餘裕
            mid = a + (b - a) / 2
            walk(a, mid); walk(mid, b); return
        expected += c                      # 平台自報的應有筆數（切片不重疊）
        off = 0
        while off < c:
            s, j = _get(s, f"{B.API}/users/self/alphas?limit=100&offset={off}&{q}")
            res = j.get("results") or []
            if not res:
                break
            for al in res:
                st = al.get("settings") or {}
                cks = ((al.get("is") or {}).get("checks") or None)
                out[al["id"]] = {
                    "dc": al.get("dateCreated"), "status": al.get("status"),
                    "delay": st.get("delay"), "universe": st.get("universe"),
                    "decay": st.get("decay"), "nz": st.get("neutralization"),
                    "code": (al.get("regular") or {}).get("code"),
                    "sharpe": (al.get("is") or {}).get("sharpe"),
                    "fitness": (al.get("is") or {}).get("fitness"),
                    # 🔴 `checks_n` 是「有沒有評過」的出口。只存 fails 的話,
                    #    **沒有 checks**（`is` 缺席／模擬沒跑完）與 **零 FAIL**
                    #    在下游長得一模一樣(都是 `fails == []`),而前者必須被當成
                    #    「不知道」擋掉、後者才是合格品。`None` = 這條沒有 is/checks。
                    "checks_n": (len(cks) if cks is not None else None),
                    "fails": [c2["name"] for c2 in (cks or []) if c2.get("result") == "FAIL"],
                    "pending": [c2["name"] for c2 in (cks or []) if c2.get("result") == "PENDING"],
                }
            off += 100
        if verbose:
            print(f"  {a:%m-%d %H:%M}..{b:%m-%d %H:%M} count={c} total={len(out)}", flush=True)

    d = START
    end = dt.datetime.utcnow() - dt.timedelta(hours=4) + dt.timedelta(days=1)
    while d < end:
        walk(d, d + dt.timedelta(days=1))
        d += dt.timedelta(days=1)
    if totals is not None:
        totals["expected"] = expected
    return out


# ───────────────────── 平台快照（挑片器的第二本帳） ─────────────────────
# `pick_next.py` 的候選池原本只有 `auto_ledger.jsonl`，於是「平台上有、帳本沒有」
# 的 alpha 結構上永遠選不到（2026-09-05 對帳：199 條，其中 4 條 checks 零 FAIL）。
# 修法是把候選池改成「帳本 ∪ 平台」，而平台這一半就存在這個快照裡。
# 快照由 `reconcile.py` 產（列舉規則只有這一份實作），由 `pick_next.py` 讀。
SNAPSHOT = ROOT / "platform_alphas.json"
SNAPSHOT_MAX_AGE_H = 24.0        # 缺口每天還在長（乙群 ET 逐日 0~8 條）


def save_snapshot(plat: dict, path: Path = SNAPSHOT, expected: int | None = None) -> Path:
    """原子寫入。**不可以直接寫最終路徑** —— `open(...,"w")` 是先截斷後寫入，
    寫到一半拋例外會留下 0 bytes，而空快照對讀取端是「合法但錯誤的零筆」
    （memory `write-truncates-before-it-fails`）。"""
    payload = {
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),   # 台北
        "fetched_at_epoch": time.time(),
        "count": len(plat),
        # 平台自報的應有筆數。`load_snapshot()` 拿它擋「列舉中途少抓」——
        # 沒有這一欄的話,殘缺快照與完整快照在讀取端**完全分不出來**,
        # 而少掉的那群正是平台獨有的候選 = 這次修的 bug 換個位置復發。
        "expected_total": expected,
        "alphas": plat,
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    n = len(json.loads(tmp.read_text(encoding="utf-8"))["alphas"])   # 讀回比對
    if n != len(plat):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"快照讀回不符：寫 {len(plat)} 讀 {n}")
    os.replace(tmp, path)
    return path


def load_snapshot(path: Path = SNAPSHOT, max_age_h: float = SNAPSHOT_MAX_AGE_H):
    """回 `(alphas, meta, why)`。拿不到一律回 `(None, meta_or_None, 原因)`。

    ⚠️ **不要**在拿不到時回空 dict：呼叫端會把「沒問到平台」讀成「平台上沒有
    額外的東西」，那正是本次要修掉的那個 fail-open 的新版本。
    """
    if not path.exists():
        return None, None, f"快照不存在（{path.name}）"
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return None, None, f"快照讀不動：{e}"
    al = d.get("alphas")
    if not isinstance(al, dict) or not al:
        return None, d, "快照裡沒有 alphas（0 筆的快照當成拿不到，不是當成空平台）"
    exp = d.get("expected_total")
    if exp is None:
        return None, {"count": len(al)}, ("快照沒有 expected_total（舊格式）—— "
                                          "無法判斷列舉完不完整，重抓一份")
    if len(al) < exp:
        return None, {"count": len(al), "expected": exp}, (
            f"快照不完整：抓到 {len(al)} 筆，平台自報應有 {exp} 筆（少 {exp - len(al)}）")
    ep = d.get("fetched_at_epoch")
    if not ep:
        return None, {"count": len(al)}, "快照沒有 fetched_at_epoch，判斷不了新舊"
    age_h = (time.time() - float(ep)) / 3600.0
    meta = {"fetched_at": d.get("fetched_at"), "count": len(al),
            "expected": exp, "age_h": age_h}
    if age_h > max_age_h:
        return None, meta, (f"快照過期 {age_h:.1f}h > {max_age_h:.0f}h"
                            f"（{d.get('fetched_at')}）")
    return al, meta, ""


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


def _kind(err: str) -> str:
    if "Location" in err:
        return "無有效 Location"
    if "401" in err:
        return "poll 401"
    if "WARNING" in err:
        return "status=WARNING"
    if "status=None" in err:
        return "status=None"
    return "其他：" + err[:40]


def classify(plat: dict, rows: list) -> dict:
    """對每條「平台有、帳本沒有」的 alpha，指出帳本裡對應的那一列是怎麼記的。

    比對鍵用 (expr, decay, neutralization) —— 只比 expr 會把不同 decay 的變體混在一起。

    🔴 **這個鍵不唯一，所以桶只是形狀不是成因。** 9,168 個鍵裡 2,576 個對到多列、
    1,709 個鍵的 `ok` 狀態彼此不一致。同一個鍵可能同時有「無有效 Location」和
    「poll 401」兩種列，而 poll 401 代表 POST 成功、模擬確實跑了 —— 那才是孤兒
    alpha 更自然的解釋。因此除了主桶，另外回報 `kinds`（該鍵所有錯誤型別的分佈）
    與 `ambiguous`（該鍵是否混有多種型別）。**替單一 alpha 定案成因時只能用
    `ambiguous=False` 的那些。**（2026-09-05 驗證員實據，見
    `docs/ledger-platform-gap-20260905.md`。）
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
        kinds: collections.Counter = collections.Counter()
        if not hits:
            # 中性描述。**不要在這裡寫成因**：`WjPmVLpQ`（09-04 建立、產線時期）
            # 也會落進這一桶，貼「本帳本以外的工具產生」是未經驗證的推論。
            why = "帳本無同鍵列"
        elif any(h.get("ok") for h in hits):
            why = "帳本有同鍵的成功列但 alpha_id 不同（同一式子跑了兩次）"
        else:
            kinds = collections.Counter(_kind(str(h.get("error"))) for h in hits)
            why = "帳本記成 " + _kind(str(hits[0].get("error")))
        detail.append({"id": a, **p, "why": why, "kinds": dict(kinds),
                       "ambiguous": len(kinds) > 1})
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
    totals: dict = {}
    plat = fetch_platform(s, totals=totals)
    if "--snapshot" in sys.argv:
        p = save_snapshot(plat, expected=totals.get("expected"))
        print(f"\n平台快照 {len(plat)} 條 → {p}（{now} 台北）")
        if "--report" not in sys.argv:
            return 0
    rows, bad = load_ledger_rows()
    rep = classify(plat, rows)

    print(f"\n對帳時間（台北）{now}")
    print(f"平台 alpha 總數      {rep['platform_total']}")
    print(f"帳本唯一 alpha_id    {rep['ledger_unique_alpha_id']}（壞行 {bad}）")
    print(f"平台有、帳本沒有     {len(rep['missing'])}")
    print(f"帳本有、平台沒有     {len(rep['ledger_only'])}"
          + ("  ← 逐條用 GET /alphas/{id} 確認，多半是列舉期間 miner 新產的讀取時滯"
             if rep["ledger_only"] else ""))
    for a in rep["ledger_only"]:
        print(f"    {a}")

    print("\n按原因（桶只是形狀不是成因，見 classify() docstring）：")
    for w, n in collections.Counter(m["why"] for m in rep["missing"]).most_common():
        amb = sum(1 for m in rep["missing"] if m["why"] == w and m["ambiguous"])
        tail = f"（其中 {amb} 條同鍵混有多種錯誤型別，成因有歧義）" if amb else ""
        print(f"  {n:4d}  {w}{tail}")

    clean = [m for m in rep["missing"]
             if m.get("checks_n") and not m["fails"] and m["sharpe"] is not None]
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
