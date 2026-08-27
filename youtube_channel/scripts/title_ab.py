#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""title_ab.py — 標題改寫的前後對照實驗(在已發布的存量上做)。

## 為什麼
2026-08-27 Carson 從 Studio 讀到:**曝光點閱率 2% 以下**(多數頻道落在 2~10%)。
也就是說人看到了但**沒點**——破口在點擊,不在影片。
我先前三次都在猜「點進來之後為什麼走」,方向從一開始就錯了。
(順帶:Analytics API 根本沒有 impressions 指標,`yt_analytics.impressions_ctr()`
 是照「它存在」寫的、`except` 一包 → **從上線起一直靜默回 None**,所以這個頻道
 從來沒有過點閱率資料。這也是為什麼這個破口這麼久沒被看見。)

## 量到的標題問題
103 支已發布體檢片:
  · 標題長度中位 **62 字**,**100% 超過 40 字**(手機搜尋結果的可見範圍)
  · 「個股體檢【股名 代號】」前綴吃掉中位 **13 字 = 手機可見範圍的 32%**
→ 每一支的鉤子都被切在半路(「你扛得住——」後面沒了)。

## 為什麼可以在存量上做
體檢片是**常青**的搜尋佔位(不是 feed 驅動的 4 天壽命),曝光會持續進來;
而 `videos.update` **只換標題,videoId 與搜尋排名都保留**(同 thumbnails.set 是純賺)。
所以不必等新片:直接在存量上做前後對照,而且有效的話受惠的是全部 103 支。

## 設計
- 依基準觀看數**配對**後分派(不是純亂數):排序後兩兩一組、組內一個進實驗一個進對照,
  兩組的觀看分布因此幾乎相同 —— 個股本身的搜尋量差異是這裡最強的混淆變數。
- 分派用固定 seed,可重現。
- **只動一個變數**:短標題 + 股名股號前置。句式一律沿用同一個模子,
  數字全部沿用舊標題或事實庫,**不新增任何宣稱**。一次動兩個變數結果就讀不出來。
- 舊標題完整存檔,`--restore` 可整批還原。

## 誠實邊界
- 改標題理論上會讓 YouTube 重新評估相關性,可能短期擾動排名。新標題把股名股號
  **往前移**,對「搜尋股名」這個查詢的相關性是往上;但這正是要留對照組的原因。
- n=20/20 只看得出大的差異。若差距在 ±15% 內,結論是「看不出差異」不是「沒有差異」。

用法:
  python scripts/title_ab.py                 # dry-run:列出配對、分派、新舊標題
  python scripts/title_ab.py --apply         # 真的改(每支 50 units)
  python scripts/title_ab.py --report        # 兩週後看結果
  python scripts/title_ab.py --restore       # 把實驗組標題改回去
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STUDIO = ROOT / "STUDIO"
STATE = STUDIO / "title_ab.json"
N_PER_ARM = 20
SEED = 20260827


def _facts():
    try:
        return json.loads((STUDIO / "stock_checkup_facts.json").read_text(encoding="utf-8"))["results"]
    except Exception:  # noqa: BLE001
        return {}


def _title_of(slug):
    p = ROOT / "output" / f"{slug}.md"
    if not p.exists():
        return None
    try:
        first = p.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    except Exception:  # noqa: BLE001
        return None
    return re.sub(r"^#\s*🎬?\s*", "", first).strip() or None


def rewrite(old_title, facts):
    """重組成短標題。回 None = 這支不動(寧可不改也不亂改)。

    🔴 **報酬、期間、最大回撤三者一律取自同一條 `checkup_long_horizon__<code>` claim**,
    不從舊標題拼湊。理由是本頻道的誠信事故就是「期間偷換」——兩個數字各自都真、
    但來自不同期間,湊在一起整句就是假的。標題是最容易犯這個的地方(字數壓力大、
    最先被砍掉的就是「近20年」這種修飾)。通則:A 與 B 要並排,必須來自同一組事實。

    我的第一版把期間整個省掉(「台燿6274｜賺15395%」),那是往錯的方向走 ——
    一個沒有年數的報酬率對觀眾毫無意義,而且正是這個頻道踩過的坑。

    格式:股名股號(比對搜尋詞) → 期間+報酬 → 風險 → 問句,總長 <= 40 字。"""
    import re as _re
    m = _re.match(r"個股體檢\s*【\s*([^\d】]+?)\s*(\d{4})\s*】", old_title or "")
    if not m:
        return None
    name = m.group(1).strip().rstrip("*")
    code = m.group(2)
    claim = (facts.get(f"checkup_long_horizon__{code}") or {}).get("claim", "")
    if not claim:
        return None
    # 期間:「近20年」或「上市以來（…）約18.6年」
    per = _re.search(r"近\s*([\d.]+)\s*年", claim) or _re.search(r"約\s*([\d.]+)\s*年", claim)
    ret = _re.search(r"總報酬\s*(-?[\d,\.]+)\s*%", claim)
    dd = _re.search(r"最大回撤\s*-?([\d.]+)\s*%", claim)
    if not (per and ret and dd):
        return None
    yrs = per.group(1).rstrip("0").rstrip(".") if "." in per.group(1) else per.group(1)
    r = float(ret.group(1).replace(",", ""))
    if r <= 0:                      # 賠錢的用「賺」講不通,這批先不動
        return None
    gain = f"{r/100:.0f}倍" if r >= 1000 else f"{r:.0f}%"
    t = f"{name}{code}｜{yrs}年賺{gain}，但最慘跌{float(dd.group(1)):.0f}%你抱得住嗎？"
    return t if len(t) <= 40 else None


def _candidates():
    """已發布體檢長片 + 近 28 天觀看(當基準)。走 Analytics(獨立配額)。"""
    import yt_analytics as ya
    from datetime import date, timedelta
    led = json.loads((STUDIO / "uploaded_ledger.json").read_text(encoding="utf-8"))
    v2s = {v: k for k, v in led.items() if isinstance(v, str) and len(v) == 11}
    s = ya._service()
    end = date.today() - timedelta(days=4)
    start = end - timedelta(days=27)
    rows = s.reports().query(
        ids="channel==MINE", startDate=str(start), endDate=str(end),
        metrics="views,estimatedMinutesWatched", dimensions="video",
        sort="-estimatedMinutesWatched", maxResults=200).execute().get("rows", [])
    facts = _facts()
    out = []
    for vid, views, mins in rows:
        slug = v2s.get(vid)
        if not slug or not slug.startswith("L_") or "體檢" not in slug:
            continue
        old = _title_of(slug)
        new = rewrite(old, facts) if old else None
        if not new or new == old:
            continue
        out.append({"slug": slug, "vid": vid, "views": views, "mins": mins,
                    "old": old, "new": new})
    return out, (start.isoformat(), end.isoformat())


def _assign(cands):
    """依基準觀看數**配對**分派:排序後兩兩一組,組內用固定 seed 決定誰進實驗組。
    純亂數在 n=40 時很容易讓兩組的觀看分布差一截,而觀看數正是這裡最強的混淆變數。"""
    import random
    rnd = random.Random(SEED)
    ranked = sorted(cands, key=lambda x: -x["views"])[:N_PER_ARM * 2]
    treat, ctrl = [], []
    for i in range(0, len(ranked) - 1, 2):
        a, b = ranked[i], ranked[i + 1]
        if rnd.random() < 0.5:
            a, b = b, a
        treat.append(a)
        ctrl.append(b)
    return treat, ctrl


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--restore", action="store_true")
    args = ap.parse_args()

    if args.report or args.restore:
        if not STATE.exists():
            print("還沒有實驗紀錄。")
            return 0
        st = json.loads(STATE.read_text(encoding="utf-8"))

    if args.restore:
        import daily_publish as dp
        yt = dp.get_service()
        n = 0
        for r in st["treat"]:
            try:
                v = yt.videos().list(part="snippet", id=r["vid"]).execute()["items"][0]
                sn = v["snippet"]
                # 還原成**線上實際的**舊標題,不是本機 .md 那一份。
                # 兩者可能不同(線上被別的腳本改過/人工改過),用 .md 還原等於設成
                # 一個從來沒上線過的標題 —— 還原本身變成一次新的改動。
                sn["title"] = r.get("old_live") or r["old"]
                yt.videos().update(part="snippet", body={"id": r["vid"], "snippet": sn}).execute()
                n += 1
                print(f"↩ 還原 {r['vid']} {r['old'][:40]}")
            except Exception as e:  # noqa: BLE001
                print(f"[err] {r['vid']} {str(e)[:80]}")
                if "quota" in str(e).lower():
                    break
        print(f"\n已還原 {n} 支。")
        return 0

    if args.report:
        import statistics as stx
        import yt_analytics as ya
        from datetime import date, timedelta
        s = ya._service()
        end = date.today() - timedelta(days=4)
        start = end - timedelta(days=27)
        rows = s.reports().query(
            ids="channel==MINE", startDate=str(start), endDate=str(end),
            metrics="views", dimensions="video", sort="-views",
            maxResults=200).execute().get("rows", [])
        now = {r[0]: r[1] for r in rows}
        print(f"改標題於 {st['applied_at']};現在期間 {start} ~ {end}\n")
        print(f"{'組別':<8}{'支數':>4}{'基準中位觀看':>12}{'現在中位觀看':>12}{'變化':>10}")
        res = {}
        for arm, lbl in (("treat", "實驗(改)"), ("ctrl", "對照(不改)")):
            g = [(r, now.get(r["vid"], 0)) for r in st[arm]]
            b = stx.median(r["views"] for r, _ in g)
            a = stx.median(n for _, n in g)
            res[arm] = (b, a)
            print(f"{lbl:<8}{len(g):>4}{b:>12.0f}{a:>12.0f}{(a-b)/max(b,1)*100:>+9.0f}%")
        tb, ta = res["treat"]
        cb, ca = res["ctrl"]
        lift = ((ta / max(tb, 1)) / max(ca / max(cb, 1), 0.01) - 1) * 100
        print(f"\n差異中的差異(扣掉大盤趨勢):{lift:+.0f}%")
        print("⚠️ n=20/20 只看得出大的差異;±15% 內的結論是「看不出差異」不是「沒有差異」。")
        return 0

    cands, (b0, b1) = _candidates()
    print(f"可改寫的已發布體檢片:{len(cands)} 支(基準期間 {b0} ~ {b1})")
    if len(cands) < N_PER_ARM * 2:
        print(f"⚠️ 不足 {N_PER_ARM*2} 支,會照現有數量配對。")
    treat, ctrl = _assign(cands)
    print(f"\n配對分派:實驗組 {len(treat)} / 對照組 {len(ctrl)}")
    import statistics as stx
    print(f"  基準中位觀看  實驗 {stx.median(r['views'] for r in treat):.0f}"
          f" / 對照 {stx.median(r['views'] for r in ctrl):.0f}   ← 兩組要接近才算配對成功")
    print("\n實驗組會改成:")
    for r in treat[:8]:
        print(f"  觀看{r['views']:>5}  舊({len(r['old'])}字) {r['old'][:52]}")
        print(f"              新({len(r['new'])}字) {r['new']}")
    if len(treat) > 8:
        print(f"  …共 {len(treat)} 支")
    if not args.apply:
        print(f"\n[dry-run] 未改動。要真的改:--apply(每支 50 units,共 {len(treat)*50})")
        return 0

    import daily_publish as dp
    yt = dp.get_service()
    n = 0
    for r in treat:
        try:
            v = yt.videos().list(part="snippet", id=r["vid"]).execute()["items"][0]
            sn = v["snippet"]
            r["old_live"] = sn.get("title")          # 以線上實際標題為準,不信本機 .md
            sn["title"] = r["new"]
            yt.videos().update(part="snippet", body={"id": r["vid"], "snippet": sn}).execute()
            n += 1
            print(f"✅ {r['vid']} {r['new']}")
        except Exception as e:  # noqa: BLE001
            print(f"[err] {r['vid']} {str(e)[:90]}")
            if "quota" in str(e).lower():
                print("配額停止(冪等,下個配額日接著改)")
                break
    st = {"applied_at": time.strftime("%F %T"), "baseline_period": [b0, b1],
          "treat": treat[:n], "ctrl": ctrl, "seed": SEED}
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n改了 {n} 支;對照組 {len(ctrl)} 支不動。兩週後 --report。")
    try:
        from ops import log_ops
        log_ops("標題實驗", f"短標題改寫 {n} 支(對照 {len(ctrl)} 支不動)")
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
