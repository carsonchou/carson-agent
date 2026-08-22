#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_period_disclaimer.py — 給「期間偷換」的已發布片加更正說明(只改描述,不動影片)。

## 為什麼(2026-08-20)
個股體檢的事實有兩組**期間不同**的資料:
    long_horizon = 上市以來/近 20 年 —— 這組**沒有** 0050 對照數字
    three_way    = **近 10 年**(共同起點才能跟 0050 比)—— 0050 的數字只在這組
旁白很自然地拿前者的個股報酬,配上後者的 0050 報酬,中間寫「同期」:
    聯鈞:「20 年賺 4322.4%…同期 0050 是 685.3%」→ 685.3% 其實是 10 年的
    台半:「同期無腦買 0050 總報酬 716%」        → 前文講的是 18.6 年
每個數字都是真的,但期間被偷換,效果是**低估 0050**、讓個股顯得比實際好
——正好和頻道「誠實實測」的定位相反,也正好是觀眾最會檢查的地方
(真留言:「0050 相同期間的含息報酬率差不多」)。

掃描 95 支個股體檢旁白:77 支(81%)犯這條,其中 62 支已發布、合計 13,233 次觀看。
產生端已修(LONG_RULES 規則ⓜ + _long_bad 的 _long_mixed_period 閘門)。

## 為什麼是加更正而不是下架
數字本身都是真的、來源都在事實庫裡,錯的是**期間標示不清**,不是編造。
重製會失去 videoId／觀看數／搜尋排名(搜尋是本頻道唯一在成長的來源),
拿那個換掉一個表述問題不划算。加註說明保留全部既有資產,而且觀眾看得到。
Carson 2026-08-20 拍板選這個做法。

## 安全設計
- **插入不取代**:先 videos.list 取回完整 snippet,只在 description 前面插一段,
  title／tags／categoryId 一字不動原樣送回(videos.update 是整包覆蓋,漏帶等於清空)。
- 原 snippet 備份到 STUDIO/desc_backup/<vid>.json(與章節修正共用同一個備份區)。
- 冪等:描述已含更正標記就跳過。
- 依近 30 天觀看排序:先修還有人在看的。
- 預設 dry-run;--max 控配額(videos.list 1 + videos.update 50 ≈ 51/支)。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

SRC = ROOT / "STUDIO" / "_mixed_period_published.json"
DONE = ROOT / "STUDIO" / "period_disclaimer_done.json"
MARK = "📌 關於片中與 0050 的比較"

# ⚠️ YouTube 描述欄**不渲染 Markdown**:寫 **粗體** 會原樣顯示成兩個星號。
# 第一版直接把內部文件的寫法貼過來,結果觀眾看到的是「取自**近十年**的」。
# 純文字要強調就用「」或全形符號。
NOTE = (
    f"{MARK}\n"
    "片中提到「同期 0050」的報酬數字,取自「近十年」的共同資料起點(兩檔都有可信資料的"
    "那段期間),與片中個股「上市以來／近二十年」的長期報酬並不是同一段期間。\n"
    "兩組數字各自都是真實回測結果,但放在一起講容易讓人以為是同期對比,特此更正。\n"
    "之後的影片已改成在同一句標明期間。\n"
)


def _views_map():
    try:
        import yt_analytics as ya
        from datetime import date, timedelta
        svc = ya._service()
        if svc is None:
            return {}
        r = svc.reports().query(
            ids="channel==MINE", startDate=(date.today() - timedelta(days=30)).isoformat(),
            endDate=date.today().isoformat(), dimensions="video", metrics="views",
            sort="-views", maxResults=200).execute()
        return {x[0]: x[1] for x in (r.get("rows") or [])}
    except Exception:  # noqa: BLE001
        return {}


def _refresh_candidates(rows):
    """把候選名單重算一次並併回去(2026-08-22 修)。

    原本 SRC 是 2026-08-20 掃出來的**靜態快照**(62 筆),之後新發布的片就算中招也
    永遠不會進名單——實測當天就已經漏了 21 支(全是 08-20 之後發布的)。
    改成每次跑都用產線本尊的 `_long_mixed_period` 重掃台帳,聯集進名單。

    ⚠️ 精準度優先:這支工具的動作是**在已公開的影片上加一則認錯啟事**,
    對沒錯的影片加註等於憑空自認有錯,比漏加更傷。所以這裡比產線閘門嚴一級——
    只收「命中句本身有引到數字(%/倍)」的,濾掉像
    「成千上萬的上班族幾乎都在同一時間領到薪水…元大台灣50」這種順帶提及
    (實測就是這一支被誤收)。產線閘門那邊維持寬鬆(誤判只是多重生一次)。
    """
    import re as _re
    try:
        import produce_batch as _pb
        led = json.loads((ROOT / "STUDIO" / "uploaded_ledger.json").read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 候選名單重算跳過({str(exc)[:60]}),沿用既有名單")
        return rows
    _num = _re.compile(r"\d+(?:\.\d+)?\s*%|\d+(?:\.\d+)?\s*倍|百分之[零一二三四五六七八九十百]+")
    have = {r[1] for r in rows}
    added = 0
    for slug, vid in led.items():
        if not isinstance(vid, str) or not vid or not slug.startswith("L_") or vid in have:
            continue
        vp = ROOT / "output" / f"{slug}.voice.txt"
        if not vp.exists():
            continue
        t = vp.read_text(encoding="utf-8", errors="replace")
        if not _pb._long_mixed_period(t, slug):
            continue
        # 命中句必須自己引了數字才收(見 docstring 的精準度優先)
        hit_sents = [s for s in _re.split(r"(?<=[。!?！？])", t)
                     if _pb._long_mixed_period(s, slug)]
        if not any(_num.search(s) for s in hit_sents):
            continue
        rows.append([slug, vid, "auto-refresh"])
        added += 1
    if added:
        try:
            import studio_common as sc
            sc.save_json_atomic(SRC, rows)
        except Exception:  # noqa: BLE001
            SRC.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        print(f"候選名單重算:新增 {added} 支(名單原本是靜態快照,新發布的片以前進不來)")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max", type=int, default=20)
    args = ap.parse_args()

    import daily_publish as dp
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    rows = _refresh_candidates(rows)
    done = set(json.loads(DONE.read_text(encoding="utf-8"))) if DONE.exists() else set()
    views = _views_map()
    cands = [(s, v) for s, v, _ in rows if v not in done]
    cands.sort(key=lambda sv: -views.get(sv[1], 0))
    print(f"待加更正:{len(cands)} 支(已完成 {len(done)});依近 30 天觀看排序\n")

    yt = dp.get_service()
    bk = ROOT / "STUDIO" / "desc_backup"
    bk.mkdir(exist_ok=True)
    n = 0
    for slug, vid in cands:
        if n >= args.max:
            print(f"[quota] 達本輪上限 {args.max},其餘下次續(冪等)")
            break
        try:
            r = yt.videos().list(part="snippet", id=vid).execute()
            items = r.get("items") or []
            if not items:
                done.add(vid)
                continue
            sn = items[0]["snippet"]
            desc = sn.get("description") or ""
            if MARK in desc:
                done.add(vid)
                continue
            new_desc = NOTE + "\n" + desc
            if len(new_desc) > 4990:
                new_desc = new_desc[:4990]
            print(f"  ✏ {slug[:40]} (觀看 {views.get(vid, 0)})")
            if not args.apply:
                n += 1
                continue
            (bk / f"{vid}.json").write_text(json.dumps(sn, ensure_ascii=False), encoding="utf-8")
            body = {"id": vid, "snippet": {
                "title": sn.get("title"), "description": new_desc,
                "categoryId": sn.get("categoryId"), "tags": sn.get("tags", []),
            }}
            if sn.get("defaultLanguage"):
                body["snippet"]["defaultLanguage"] = sn["defaultLanguage"]
            yt.videos().update(part="snippet", body=body).execute()
            done.add(vid)
            n += 1
            print("     ✅ 已加更正")
        except Exception as exc:  # noqa: BLE001
            print(f"     [warn] {str(exc)[:120]}", file=sys.stderr)
    if args.apply:
        DONE.write_text(json.dumps(sorted(done)), encoding="utf-8")
        try:
            from ops import log_ops
            log_ops("期間更正", f"加更正說明 {n} 支(累計 {len(done)})")
        except Exception:  # noqa: BLE001
            pass
    print(f"\n{'已加' if args.apply else '將加'} {n} 支")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
