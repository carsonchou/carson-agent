#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ab_title.py — 【A/B 標題迭代官】對已發布但完播/觀看偏低的片，產更強的變體標題。

為什麼：改一支已發布片的標題，是「對外」動作（影響 live 影片）。所以本工具
**預設只產建議、不碰任何 live 影片**；真正套用留給決策中心按鈕或明確旗標。

流程
----
1. 讀 STUDIO/quality_scores.json 的 published 清單（含 videoId/title/score/retention/views）。
2. 挑「完播偏低 或 觀看低於同期中位」的片當 A/B 對象（差的排前面）。
3. 對每支用 llm.complete（注入 sc.PERSONA + 小白避雷角度 + evidence_block）產 2–3 個
   更強變體標題（數字／懸念／避雷／我幫你試）。
4. 寫 STUDIO/ab_title_suggestions.json：每支
   {video_id, slug, old_title, retention, views, score, variants:[...], picked:null, applied:false}。

套用（對外，需明確旗標）
------------------------
  --apply <video_id> <變體index>   把該片標題改成建議中的某個變體（真的打 YouTube API）。
  --auto-apply                      把每支的 picked（沒選則第 0 個）一次套用（明確、危險，會動 live）。
  兩者都會把 old→new 記到 STUDIO/ab_title_log.json（存 old_title 可還原）。

安全
----
* main() 預設只產建議、不改任何 live 影片。
* --dry：只印建議、不寫任何檔、不碰網路（沒資料時優雅印「無低完播片」）。
* 改標題只在 --apply / --auto-apply 才發生，且一定記 log 可回溯。
* 不誇大、不喊單（PERSONA 誠信鐵則）。

用法
----
  python scripts/ab_title.py                       # 產建議，寫 ab_title_suggestions.json（不改 live）
  python scripts/ab_title.py --dry                 # 只印建議、不寫檔、不改 live
  python scripts/ab_title.py --limit 12            # 最多處理 12 支低表現片
  python scripts/ab_title.py --apply VIDEOID 1     # 把某片標題改成建議變體[1]（對外！）
  python scripts/ab_title.py --auto-apply          # 一次套用所有 picked/預設變體（對外！）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
SCORES = STUDIO / "quality_scores.json"
SUGGEST = STUDIO / "ab_title_suggestions.json"
LOG = STUDIO / "ab_title_log.json"
TW = timezone(timedelta(hours=8))

MAX_TITLE_LEN = 100  # YouTube 標題上限

import studio_common as sc  # PERSONA / has_llm_key / evidence_block

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg): pass


def tw_now() -> str:
    return datetime.now(TW).strftime("%Y-%m-%d %H:%M")


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except Exception:
        return default


def _median(nums):
    xs = sorted(x for x in nums if isinstance(x, (int, float)))
    if not xs:
        return None
    n = len(xs)
    mid = n // 2
    return xs[mid] if n % 2 else (xs[mid - 1] + xs[mid]) / 2


# --------------------------------------------------------------------------- #
# 1) 挑片：完播偏低 或 觀看低於同期中位
# --------------------------------------------------------------------------- #

def pick_candidates(retention_floor: float = 40.0, limit: int = 8):
    """從 quality_scores.json 的 published 挑 A/B 對象。

    條件（任一即入選）：
      ・retention < retention_floor（完播偏低），或
      ・views < 同期中位（觀看落後）。
    只收有 videoId 且有 title、且至少有一個成效數字（views/retention）的片。
    差的排前面（先低完播、再低觀看），最多 limit 支。
    回 (candidates, meta)；meta 含中位數等診斷資訊。
    """
    data = _load(SCORES, {})
    pub = [p for p in (data.get("published") or [])
           if p.get("videoId") and (p.get("title"))]
    # 只在「有成效資料」的片上做 A/B（沒 Analytics 無從判斷強弱）
    scored = [p for p in pub if p.get("views") is not None or p.get("retention") is not None]
    med_views = _median([p.get("views") for p in scored if p.get("views") is not None])
    med_ret = _median([p.get("retention") for p in scored if p.get("retention") is not None])

    def is_low(p):
        ret = p.get("retention")
        views = p.get("views")
        low_ret = ret is not None and ret < retention_floor
        low_views = (views is not None and med_views is not None and views < med_views)
        return low_ret or low_views

    cands = [p for p in scored if is_low(p)]
    # 差的優先：完播低優先，其次觀看低（None 視為最大，排後面）
    cands.sort(key=lambda p: ((p.get("retention") if p.get("retention") is not None else 999.0),
                              (p.get("views") if p.get("views") is not None else 10 ** 9)))
    meta = {"median_views": med_views, "median_retention": med_ret,
            "retention_floor": retention_floor,
            "scored_pool": len(scored), "low_total": len(cands)}
    return cands[:max(0, limit)], meta


# --------------------------------------------------------------------------- #
# 2) 變體產法：LLM 注入 PERSONA + 小白避雷 + evidence
# --------------------------------------------------------------------------- #

def gen_variants(old_title: str, retention, views, n: int = 3):
    """對一支低表現片產 n 個更強變體標題。回 list[str]（失敗回 []）。

    角度（軟性小白定位）：數字具體化／懸念缺口／避雷（別自己送死）／我先幫你試。
    走共用 llm.complete（OpenRouter 路由），json_mode 強制吐合格 JSON。
    """
    if not sc.has_llm_key():
        return []
    ev = sc.evidence_block()
    perf = []
    if retention is not None:
        perf.append(f"目前完播率約 {retention}%（偏低，開頭/標題沒勾住）")
    if views is not None:
        perf.append(f"目前觀看約 {views}（落後同期）")
    perf_txt = "；".join(perf) or "成效偏低"
    prompt = (
        sc.PERSONA + "\n\n"
        + (ev + "\n\n" if ev else "")
        + "你是量化阿森的『標題 A/B 迭代官』。下面這支片已發布但表現不好，"
        "請針對『標題』重寫出更強的變體（只改標題，不是改內容）。\n"
        f"原標題：{old_title}\n"
        f"現況：{perf_txt}。\n\n"
        "【變體要求】\n"
        "・產 " + str(n) + " 個**明顯不同角度**的變體，每個 ≤ 42 字（含 emoji/#Shorts 也算）。\n"
        "・善用這些鉤子（每個變體挑 1–2 種，別全部塞）：\n"
        "  ①具體數字/反差（如『丟10萬跑30天，結果賠了？』）\n"
        "  ②懸念缺口（留一個非看不可的問號）\n"
        "  ③小白避雷（『新手別急著開，先看這個』『別自己送死』的軟性語氣）\n"
        "  ④我先幫你試（『我拿真錢/真回測替你試過』）\n"
        "  ⑤可搜尋長尾（如『派網網格怎麼設』方便被搜到）。\n"
        "・保留原片主題與關鍵字，不要換題材、不要無中生有數據。\n"
        "・**誠信鐵則**：不喊單、不保證收益、不用躺賺/穩賺/一天賺X/包賺等誇大詞（會被限流）。\n"
        "・若原標題含 #Shorts 等尾標，變體可沿用。\n\n"
        '只輸出 JSON（不要其他字）：{"variants":["變體1","變體2","變體3"]}'
    )
    try:
        import llm
        txt = llm.complete(prompt, 500, json_mode=True)
        import re
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            return []
        d = json.loads(m.group(0))
        out = []
        seen = set()
        for v in (d.get("variants") or []):
            v = str(v).strip().strip('"').strip()
            if not v or v == old_title or v in seen:
                continue
            v = v[:MAX_TITLE_LEN]
            seen.add(v)
            out.append(v)
        return out[:n]
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 變體產生失敗：{str(e)[:90]}", file=sys.stderr)
        return []


# --------------------------------------------------------------------------- #
# 3) 產建議（預設路徑，不碰 live）
# --------------------------------------------------------------------------- #

def build_suggestions(limit=8, retention_floor=40.0, n_variants=3, per_call_sleep=1.2):
    """挑片 + 逐支產變體，回 payload dict（不寫檔）。"""
    cands, meta = pick_candidates(retention_floor=retention_floor, limit=limit)
    items = []
    for p in cands:
        variants = gen_variants(p.get("title", ""), p.get("retention"), p.get("views"), n=n_variants)
        items.append({
            "video_id": p["videoId"],
            "slug": p.get("slug", ""),
            "old_title": p.get("title", ""),
            "retention": p.get("retention"),
            "views": p.get("views"),
            "score": p.get("score"),
            "variants": variants,
            "picked": None,
            "applied": False,
        })
        if variants:
            time.sleep(per_call_sleep)  # 節流，避免 OpenRouter 連打限流
    payload = {"updated": tw_now(), "note": "預設只產建議，不改 live 影片；套用請用 --apply/--auto-apply。",
               "diagnostics": meta, "items": items}
    return payload


def _merge_prev_choices(payload):
    """保留上一輪已選/已套用的 picked/applied（同 video_id）。"""
    prev = {i.get("video_id"): i for i in (_load(SUGGEST, {}).get("items") or [])}
    for it in payload["items"]:
        old = prev.get(it["video_id"])
        if old:
            it["picked"] = old.get("picked")
            it["applied"] = bool(old.get("applied"))
    return payload


# --------------------------------------------------------------------------- #
# 4) apply_title：真的改 live 標題（預設不觸發）
# --------------------------------------------------------------------------- #

def apply_title(video_id: str, new_title: str) -> bool:
    """把某已發布片的標題改成 new_title（YouTube videos().update part=snippet）。

    安全設計：
      ・先抓現有 snippet，只覆蓋 title，其他欄位（categoryId/description/tags…）原樣保留。
      ・old→new 一律記到 STUDIO/ab_title_log.json（存 old_title，可據此還原）。
      ・**此函式只在 --apply / --auto-apply 明確呼叫；main() 預設不會叫它。**
    回 True/False。
    """
    new_title = (new_title or "").strip()[:MAX_TITLE_LEN]
    if not new_title:
        print("[error] 新標題為空，取消。", file=sys.stderr)
        return False
    try:
        from decision_dept import yt_service
        yt = yt_service()
    except Exception as e:  # noqa: BLE001
        print(f"[error] 無法建立 YouTube 服務（缺 token？）：{str(e)[:100]}", file=sys.stderr)
        return False
    try:
        resp = yt.videos().list(part="snippet", id=video_id).execute()
        items = resp.get("items", [])
        if not items:
            print(f"[error] 找不到影片 {video_id}（可能非本頻道或已刪）。", file=sys.stderr)
            return False
        snippet = items[0]["snippet"]
        old_title = snippet.get("title", "")
        if old_title == new_title:
            print(f"[skip] {video_id} 標題未變（已是目標標題）。")
            return False
        # 只改 title，其餘 snippet 欄位原樣送回（categoryId 必帶，否則 API 退件）
        snippet["title"] = new_title
        yt.videos().update(part="snippet", body={"id": video_id, "snippet": snippet}).execute()
    except Exception as e:  # noqa: BLE001
        print(f"[error] 更新標題失敗 {video_id}：{str(e)[:120]}", file=sys.stderr)
        return False
    # 記 log（可還原）
    log = _load(LOG, [])
    if not isinstance(log, list):
        log = []
    log.append({"ts": tw_now(), "video_id": video_id,
                "old_title": old_title, "new_title": new_title})
    LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    log_ops("A/B標題", f"改標題 {video_id}：{old_title[:16]}… → {new_title[:16]}…")
    print(f"[ok] 已改標題 {video_id}\n     舊：{old_title}\n     新：{new_title}\n     （已記 log，可回溯還原）")
    return True


def _mark_applied(video_id, new_title):
    """在 suggestions 檔標記某片 picked=標題、applied=True。"""
    data = _load(SUGGEST, {})
    for it in (data.get("items") or []):
        if it.get("video_id") == video_id:
            it["picked"] = new_title
            it["applied"] = True
    if data:
        data["updated"] = tw_now()
        SUGGEST.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_apply(video_id: str, index: int) -> int:
    """--apply：套用 suggestions 檔中某片的第 index 個變體（對外，真改 live）。"""
    data = _load(SUGGEST, {})
    item = next((i for i in (data.get("items") or []) if i.get("video_id") == video_id), None)
    if not item:
        print(f"[error] suggestions 檔沒有 {video_id}；請先跑一次產建議。", file=sys.stderr)
        return 2
    variants = item.get("variants") or []
    if not (0 <= index < len(variants)):
        print(f"[error] 變體 index {index} 超出範圍（0..{len(variants)-1}）。", file=sys.stderr)
        return 2
    new_title = variants[index]
    print(f"[apply] {video_id} → 變體[{index}]：{new_title}")
    if apply_title(video_id, new_title):
        _mark_applied(video_id, new_title)
        return 0
    return 1


def cmd_auto_apply() -> int:
    """--auto-apply：對每支未套用的片套用 picked（沒選則變體[0]）。對外、危險，需明確旗標。"""
    data = _load(SUGGEST, {})
    items = [i for i in (data.get("items") or []) if not i.get("applied")]
    if not items:
        print("[info] 沒有待套用的建議（都套用過或無建議）。")
        return 0
    print(f"[auto-apply] 將對 {len(items)} 支已發布片套用新標題（對外動作）…")
    done = 0
    for it in items:
        vid = it.get("video_id")
        new_title = it.get("picked") or (it.get("variants") or [None])[0]
        if not new_title:
            continue
        if apply_title(vid, new_title):
            _mark_applied(vid, new_title)
            done += 1
        time.sleep(1.0)
    print(f"[auto-apply] 完成：{done}/{len(items)} 支已改標題。")
    return 0


# --------------------------------------------------------------------------- #
# 輸出 / main
# --------------------------------------------------------------------------- #

def print_payload(payload):
    m = payload.get("diagnostics", {})
    print(f"[A/B 標題建議] {payload.get('updated','')}")
    print(f"  同期中位：觀看 {m.get('median_views')}、完播 {m.get('median_retention')}%；"
          f"完播門檻 {m.get('retention_floor')}%；低表現池 {m.get('low_total')} 支。")
    items = payload.get("items") or []
    if not items:
        print("  無低完播片（或無成效資料）：沒有需要 A/B 的對象。")
        return
    for i, it in enumerate(items, 1):
        print(f"\n{i}. [{it['video_id']}] 完播 {it.get('retention')}% / 觀看 {it.get('views')}"
              f"（品管分 {it.get('score')}）")
        print(f"   原：{it['old_title']}")
        if it["variants"]:
            for j, v in enumerate(it["variants"]):
                print(f"   變體[{j}]：{v}")
        else:
            print("   （變體未產出：無 LLM key 或產生失敗）")


def main() -> int:
    ap = argparse.ArgumentParser(description="A/B 標題迭代：對低完播/低觀看的已發布片產更強變體（預設只建議，不改 live）。")
    ap.add_argument("--limit", type=int, default=8, help="最多處理幾支低表現片（預設 8）")
    ap.add_argument("--retention-floor", type=float, default=40.0, help="完播率低於此值視為偏低（預設 40）")
    ap.add_argument("--variants", type=int, default=3, help="每支產幾個變體（預設 3）")
    ap.add_argument("--dry", action="store_true", help="只印建議、不寫檔、不碰網路（不改任何 live 影片）")
    ap.add_argument("--apply", nargs=2, metavar=("VIDEO_ID", "INDEX"),
                    help="套用某片的第 INDEX 個變體（對外！真改 live 標題）")
    ap.add_argument("--auto-apply", action="store_true",
                    help="一次套用所有 picked/預設變體（對外！真改 live 標題）")
    args = ap.parse_args()

    # ── 對外套用路徑（唯二會改 live 的入口，需明確旗標）──
    if args.apply:
        vid, idx = args.apply
        try:
            idx = int(idx)
        except ValueError:
            print("[error] INDEX 必須是整數。", file=sys.stderr)
            return 2
        return cmd_apply(vid, idx)
    if args.auto_apply:
        return cmd_auto_apply()

    # ── 預設路徑：只產建議，不改任何 live 影片 ──
    if args.dry:
        # 不寫檔、不碰網路以外（LLM 仍需產變體）；若無 key/無資料則優雅收尾
        payload = build_suggestions(limit=args.limit, retention_floor=args.retention_floor,
                                    n_variants=args.variants)
        print_payload(payload)
        if not (payload.get("items")):
            print("\n[dry] 無低完播片，未寫任何檔。")
        else:
            print("\n[dry] 以上為建議；未寫檔、未改任何 live 影片。")
        return 0

    payload = build_suggestions(limit=args.limit, retention_floor=args.retention_floor,
                                n_variants=args.variants)
    payload = _merge_prev_choices(payload)
    STUDIO.mkdir(parents=True, exist_ok=True)
    SUGGEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print_payload(payload)
    n = len(payload.get("items") or [])
    with_var = sum(1 for it in payload["items"] if it["variants"])
    log_ops("A/B標題", f"產建議 {n} 支（{with_var} 支有變體）→ ab_title_suggestions.json")
    print(f"\n[ok] 已寫 {SUGGEST.name}：{n} 支候選（{with_var} 支有變體）。"
          f"預設不改 live；要套用請按決策中心按鈕或用 --apply/--auto-apply。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
