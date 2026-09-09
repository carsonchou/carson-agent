#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基線的**母體**到底是哪些片。唯讀(Data API videos.list,約 2 units)。

🔴 為什麼要問這一題:判準 A 是「≥ 既有分佈的 P90」,而 **P90 完全由母體決定**。
   判準檔寫的是「既有 **44** 支」,而三本帳本合起來有 **60** 個 id。
   多出來的那些如果是**已下架**的片(下架前觀看本來就低),把它們算進去會讓
   分佈往下拉 ⇒ **P90 變小 ⇒ 門檻變簡單**。偏誤方向剛好是往「我想要的結果」走,
   那是最該擋的一種(`val_str` 的 `is_max` 註解記過同一件事)。

⇒ 兩個母體都算出來,兩個都落檔,由督導拍板用哪一個。**不要自己挑一個比較好過的。**
"""
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
CH2 = pathlib.Path(r"D:\carson-agent\yt_ch2")
BASE = ROOT / "facts" / "_baseline_frozen_2026-09-09.json"


def svc():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    tok = CH2 / "token.json"
    cr = Credentials.from_authorized_user_file(str(tok), [
        "https://www.googleapis.com/auth/yt-analytics.readonly",
        "https://www.googleapis.com/auth/youtube.readonly"])
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request())
        tok.write_text(cr.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=cr, cache_discovery=False)


def pct(vals, p):
    import math
    if not vals:
        return None
    s = sorted(vals)
    k = max(1, math.ceil(p / 100 * len(s)))
    return s[k - 1]


def main():
    base = json.loads(BASE.read_text(encoding="utf-8"))
    per = base.get("per_video") or {}
    if not per:
        print("⛔ 基線檔沒有 per_video,先改 freeze_baseline.py 把它落檔再跑這支")
        return 1
    ids = sorted(per)
    yt = svc()
    status = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        r = yt.videos().list(part="status,snippet",
                             id=",".join(chunk)).execute()
        for it in r.get("items", []):
            status[it["id"]] = {
                "privacy": it["status"]["privacyStatus"],
                "published": it["snippet"]["publishedAt"][:10],
                "title": it["snippet"]["title"][:60]}
    missing = [v for v in ids if v not in status]
    print(f"帳本 {len(ids)} 支;Data API 查得到 {len(status)} 支;"
          f"查不到(已刪或非本頻道){len(missing)} 支")
    from collections import Counter
    print("  privacyStatus:", dict(Counter(
        s["privacy"] for s in status.values())))

    out = {"as_of": base["as_of"], "populations": {}}
    for name, keep in (
            ("all_ledger", lambda v: True),
            ("public_only", lambda v: status.get(v, {}).get("privacy") == "public")):
        sel = [v for v in ids if keep(v)]
        d = {"n": len(sel)}
        for m in ("views", "engagedViews"):
            vals = [per[v][m] for v in sel]
            d[m] = {"P50": pct(vals, 50), "P75": pct(vals, 75),
                    "P90": pct(vals, 90),
                    "max": max(vals) if vals else None, "sum": sum(vals)}
        out["populations"][name] = d
        print(f"\n[{name}] n={len(sel)}")
        for m in ("views", "engagedViews"):
            print(f"   {m:<14} {d[m]}")

    out["status"] = status
    out["not_found"] = missing
    p = ROOT / "facts" / "_baseline_population_2026-09-09.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    import os
    os.replace(tmp, p)
    print(f"\n落檔 → {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
