#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ab_thumbnail.py — 【A/B 縮圖迭代官】對已發布但完播/觀看偏低的片，產更強的變體縮圖。

為什麼：換一支已發布片的縮圖，是「對外」動作（影響 live 影片）。所以本工具
**預設只產建議＋變體圖、不碰任何 live 影片**；真正套用留給決策中心按鈕或明確旗標。

關鍵事實
--------
YouTube Analytics **不提供 impressions / CTR**（實測回 0），無法直接看「縮圖點閱率」。
→ 用 `published[].retention / .views` 當 CTR 代理：低表現 = 低完播 或 觀看落後同期中位
  （縮圖／標題沒勾住 → 曝光轉不成點擊，或點進來留不住）。挑法完全比照 ab_title。

流程
----
1. 讀 STUDIO/quality_scores.json 的 published 清單（videoId/title/retention/views/score）。
2. 挑「完播偏低 或 觀看低於同期中位」的片當 A/B 對象（差的排前面）。
3. 每支：make_thumbnails.derive_cfg 產 base 設計 → llm.complete 再產另 2 組不同
   accent／角度的變體（配色語意：紅=警示、綠=獲利、黃=疑問、藍=工具）。
4. render 每個變體成 assets/thumbnails/{slug}__v{i}.jpg（不動 live）。
5. 寫 STUDIO/ab_thumb_suggestions.json：每支
   {video_id, slug, old_title, retention, views, score, variants:[...], picked, applied}。

套用（對外，需明確旗標）
------------------------
  --apply <video_id> <變體index>   把該片縮圖換成建議中的某變體圖（真的打 YouTube API）。
  --auto-apply                      把每支的 picked（沒選則第 0 個）一次換上（明確、危險，動 live）。
  兩者都會先把舊縮圖 URL／備份記到 STUDIO/ab_thumb_log.json（可據此還原）。

安全
----
* main() 預設只產建議＋變體圖、不改任何 live 影片。
* --dry：只印建議、不寫檔（變體圖仍會 render 到本機供預覽）。
* 換縮圖只在 --apply / --auto-apply 才發生，且一定記 log 可回溯。
* 不誇大、不喊單（PERSONA 誠信鐵則）。

用法
----
  python scripts/ab_thumbnail.py                       # 產建議＋變體圖，寫 ab_thumb_suggestions.json（不改 live）
  python scripts/ab_thumbnail.py --dry                 # 只印建議、render 變體圖、不寫檔、不改 live
  python scripts/ab_thumbnail.py --limit 6             # 最多處理 6 支低表現片
  python scripts/ab_thumbnail.py --apply VIDEOID 1     # 把某片縮圖換成變體[1]（對外！）
  python scripts/ab_thumbnail.py --auto-apply          # 一次換所有 picked/預設變體（對外！）
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
SUGGEST = STUDIO / "ab_thumb_suggestions.json"
LOG = STUDIO / "ab_thumb_log.json"
THUMB_DIR = ROOT / "assets" / "thumbnails"
RESTORE_DIR = THUMB_DIR / "_ab_restore"       # 換前的舊縮圖備份（可還原）
TW = timezone(timedelta(hours=8))

import studio_common as sc  # PERSONA / has_llm_key / evidence_block
import make_thumbnails as mt  # derive_cfg / make_one / ACCENTS / _real_card

# accent 名稱 ←→ RGB tuple（derive_cfg 回 tuple，變體我們用名稱溝通再轉回）
ACCENT_NAMES = {v: k for k, v in mt.ACCENTS.items()}
ACCENT_MEANING = {"red": "警示/虧損", "green": "獲利/實測", "yellow": "疑問/教學", "blue": "工具/平台"}

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


def _accent_name(accent) -> str:
    """RGB tuple → accent 名稱（找不到回 'yellow'）。"""
    if isinstance(accent, str):
        return accent if accent in mt.ACCENTS else "yellow"
    return ACCENT_NAMES.get(tuple(accent) if isinstance(accent, (list, tuple)) else accent, "yellow")


# --------------------------------------------------------------------------- #
# 1) 挑片：完播偏低 或 觀看低於同期中位（比照 ab_title.pick_candidates）
# --------------------------------------------------------------------------- #

def pick_candidates(retention_floor: float = 40.0, limit: int = 8):
    """從 quality_scores.json 的 published 挑 A/B 對象。

    條件（任一即入選）：
      ・retention < retention_floor（完播偏低），或
      ・views < 同期中位（觀看落後）。
    只收有 videoId 且有 title、且至少有一個成效數字（views/retention）的片。
    差的排前面（先低完播、再低觀看），最多 limit 支。
    回 (candidates, meta)。
    """
    data = _load(SCORES, {})
    pub = [p for p in (data.get("published") or [])
           if p.get("videoId") and (p.get("title"))]
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
    cands.sort(key=lambda p: ((p.get("retention") if p.get("retention") is not None else 999.0),
                              (p.get("views") if p.get("views") is not None else 10 ** 9)))
    meta = {"median_views": med_views, "median_retention": med_ret,
            "retention_floor": retention_floor,
            "scored_pool": len(scored), "low_total": len(cands)}
    return cands[:max(0, limit)], meta


# --------------------------------------------------------------------------- #
# 2) 變體產法：base(derive_cfg) + LLM 另 2 組不同 accent/角度
# --------------------------------------------------------------------------- #

def gen_variants(video: dict, n_extra: int = 2):
    """對一支低表現片產變體縮圖設計（回 list[cfg dict]，第 0 個是 base）。

    每個 cfg dict：{idx, accent(name), l1, l2, tag, mark, angle}。
    ・base：make_thumbnails.derive_cfg（標題→鉤子；有 LLM 用 haiku，無則啟發式）。
    ・另 n_extra 組：llm.complete json_mode，強制不同 accent／不同鉤子角度，
      配色語意（紅=警示、綠=獲利、黃=疑問、藍=工具）沿用 make_thumbnails 註解。
    失敗時至少回 [base]（保證能 render 一張）。
    """
    slug = video.get("slug") or ""
    title = video.get("title") or slug
    base_cfg = mt.derive_cfg(slug, title)
    base_accent = _accent_name(base_cfg.get("accent"))
    variants = [{
        "idx": 0, "accent": base_accent,
        "l1": base_cfg.get("l1", ""), "l2": base_cfg.get("l2", ""),
        "tag": base_cfg.get("tag", ""), "mark": base_cfg.get("mark", "?"),
        "angle": "原設計",
    }]
    if not sc.has_llm_key():
        return variants

    ev = sc.evidence_block()
    perf = []
    if video.get("retention") is not None:
        perf.append(f"目前完播率約 {video.get('retention')}%（偏低，縮圖/開頭沒勾住）")
    if video.get("views") is not None:
        perf.append(f"目前觀看約 {video.get('views')}（落後同期）")
    perf_txt = "；".join(perf) or "成效偏低"
    used_accent = base_accent
    prompt = (
        sc.PERSONA + "\n\n"
        + (ev + "\n\n" if ev else "")
        + "你是量化阿森的『縮圖 A/B 迭代官』。下面這支片已發布但表現不好，"
        "請針對『縮圖文字＋視覺角度』重設計出更強的變體（只設計縮圖，不是改內容）。\n"
        f"影片標題：{title}\n"
        f"現況：{perf_txt}。\n"
        f"目前縮圖角度：{base_cfg.get('l1','')} / {base_cfg.get('l2','')}（配色 {used_accent}）。\n\n"
        "【變體要求】\n"
        f"・產 {n_extra} 個**明顯不同角度**的縮圖變體，每個要跟目前角度、彼此都不同。\n"
        "・每個變體用**不同的 accent 配色**（別跟目前的 " + used_accent + " 一樣），配色語意：\n"
        "  紅=警示/虧損、綠=獲利/實測、黃=疑問/教學、藍=工具/平台。\n"
        "・善用鉤子（每個變體挑 1–2 種）：①具體數字/反差 ②懸念缺口 ③小白避雷 ④我先幫你試。\n"
        "・l1=第一行鉤子(2-6字,最吸睛的詞/數字)、l2=第二行(3-8字)、tag=底部說明條(6-14字)、"
        "mark=? 或 ! 或 $ 或 VS。\n"
        "・保留原片主題與關鍵字，不要換題材、不要無中生有數據。\n"
        "・**誠信鐵則**：不喊單、不保證收益、不用躺賺/穩賺/一天賺X/包賺等誇大詞。\n\n"
        '只輸出 JSON（不要其他字）：{"variants":[{"l1":"","l2":"","tag":"","accent":"red|green|yellow|blue",'
        '"mark":"?","angle":"這個變體的一句話定位"}]}'
    )
    try:
        import llm
        import re
        txt = llm.complete(prompt, 600, json_mode=True)
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            return variants
        d = json.loads(m.group(0))
        seen_angles = set()
        for v in (d.get("variants") or []):
            if not isinstance(v, dict):
                continue
            acc = str(v.get("accent") or "").lower().strip()
            if acc not in mt.ACCENTS:
                acc = next((a for a in ("red", "green", "yellow", "blue")
                            if a not in {x["accent"] for x in variants}), "blue")
            l1 = str(v.get("l1") or "").strip()[:8]
            l2 = str(v.get("l2") or "").strip()[:10]
            if not l1 and not l2:
                continue
            ang = str(v.get("angle") or "").strip()[:24]
            if ang and ang in seen_angles:
                continue
            seen_angles.add(ang)
            variants.append({
                "idx": len(variants), "accent": acc,
                "l1": l1 or base_cfg.get("l1", ""), "l2": l2 or base_cfg.get("l2", ""),
                "tag": str(v.get("tag") or base_cfg.get("tag", "")).strip()[:16],
                "mark": str(v.get("mark") or "?").strip()[:2] or "?",
                "angle": ang or "替代角度",
            })
            if len(variants) >= 1 + n_extra:
                break
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 縮圖變體產生失敗：{str(e)[:90]}", file=sys.stderr)
    return variants


def render_variants(video: dict, variants: list) -> list:
    """把每個變體 cfg render 成 assets/thumbnails/{slug}__v{i}.jpg。回填 path，回 variants。

    比照 make_thumbnails.make_auto：策略/幣種題材自動掛真實回測卡（誠實含回撤）。
    """
    slug = video.get("slug") or f"vid_{video.get('video_id') or video.get('videoId') or 'x'}"
    title = video.get("title") or slug
    card = None
    try:
        card = mt._real_card(slug, title)  # 主題不符/無資料回 None
    except Exception:  # noqa: BLE001
        card = None
    for v in variants:
        vslug = f"{slug}__v{v['idx']}"
        cfg = {"slug": vslug, "l1": v.get("l1", ""), "l2": v.get("l2", ""),
               "tag": v.get("tag", ""), "mark": v.get("mark", "?"),
               "accent": mt.ACCENTS.get(v.get("accent", "yellow"), mt.ACCENTS["yellow"])}
        if card:
            cfg["card"] = card
        try:
            out = mt.make_one(cfg)
            # 存相對 ROOT 的路徑（跨機/前端好顯示）
            try:
                v["path"] = str(Path(out).resolve().relative_to(ROOT)).replace("\\", "/")
            except Exception:  # noqa: BLE001
                v["path"] = f"assets/thumbnails/{vslug}.jpg"
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 變體圖 render 失敗 {vslug}：{str(e)[:90]}", file=sys.stderr)
            v["path"] = None
    return variants


# --------------------------------------------------------------------------- #
# 3) 產建議（預設路徑，不碰 live）
# --------------------------------------------------------------------------- #

def build_suggestions(limit=8, retention_floor=40.0, n_extra=2, per_call_sleep=1.2,
                      do_render=True):
    """挑片 + 逐支產變體設計 + render 變體圖，回 payload dict（不寫檔）。"""
    cands, meta = pick_candidates(retention_floor=retention_floor, limit=limit)
    items = []
    for p in cands:
        video = {"video_id": p["videoId"], "videoId": p["videoId"], "slug": p.get("slug", ""),
                 "title": p.get("title", ""), "retention": p.get("retention"), "views": p.get("views")}
        variants = gen_variants(video, n_extra=n_extra)
        if do_render:
            variants = render_variants(video, variants)
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
        if len(variants) > 1:
            time.sleep(per_call_sleep)  # 節流，避免 OpenRouter 連打限流
    payload = {"updated": tw_now(),
               "note": "預設只產建議＋變體圖，不換 live 縮圖；套用請用 --apply/--auto-apply。",
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
# 4) apply_thumbnail：真的換 live 縮圖（預設不觸發）
# --------------------------------------------------------------------------- #

def _backup_old_thumbnail(yt, video_id: str):
    """換前先抓現有縮圖 URL 並下載備份到 _ab_restore/，回 (old_url, backup_path or None)。"""
    old_url, backup = None, None
    try:
        resp = yt.videos().list(part="snippet", id=video_id).execute()
        items = resp.get("items", [])
        if items:
            th = (items[0]["snippet"].get("thumbnails") or {})
            for key in ("maxres", "standard", "high", "medium", "default"):
                if th.get(key, {}).get("url"):
                    old_url = th[key]["url"]
                    break
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 讀舊縮圖 URL 失敗：{str(e)[:90]}", file=sys.stderr)
    if old_url:
        try:
            import urllib.request
            RESTORE_DIR.mkdir(parents=True, exist_ok=True)
            bp = RESTORE_DIR / f"{video_id}_{datetime.now(TW).strftime('%Y%m%d_%H%M%S')}.jpg"
            with urllib.request.urlopen(old_url, timeout=30) as r:
                bp.write_bytes(r.read())
            backup = str(bp.resolve().relative_to(ROOT)).replace("\\", "/")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 備份舊縮圖失敗（僅記 URL 可還原）：{str(e)[:90]}", file=sys.stderr)
    return old_url, backup


def apply_thumbnail(video_id: str, thumb_path: str) -> bool:
    """把某已發布片的縮圖換成 thumb_path（YouTube thumbnails().set()）。

    安全設計：
      ・換前先抓舊縮圖 URL 並下載備份到 _ab_restore/，old_url/backup 一律記 log 可還原。
      ・**此函式只在 --apply / --auto-apply 明確呼叫；main() 預設不會叫它。**
    回 True/False。
    """
    p = Path(thumb_path)
    if not p.is_absolute():
        p = ROOT / thumb_path
    if not p.exists():
        print(f"[error] 變體圖不存在：{p}", file=sys.stderr)
        return False
    try:
        from set_thumbnails import get_service
        from googleapiclient.http import MediaFileUpload
        yt = get_service()
    except Exception as e:  # noqa: BLE001
        print(f"[error] 無法建立 YouTube 服務（缺 token_manage.json？）：{str(e)[:100]}", file=sys.stderr)
        return False
    old_url, backup = _backup_old_thumbnail(yt, video_id)
    try:
        yt.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(p), mimetype="image/jpeg"),
        ).execute()
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        print(f"[error] 換縮圖失敗 {video_id}：{msg[:140]}", file=sys.stderr)
        if any(k in msg.lower() for k in ("thumbnail", "permission", "forbidden")):
            print("⚠️ 若為權限問題：請先到 https://www.youtube.com/verify 完成電話驗證再重試。", file=sys.stderr)
        return False
    log = _load(LOG, [])
    if not isinstance(log, list):
        log = []
    log.append({"ts": tw_now(), "video_id": video_id, "new_thumb": thumb_path,
                "old_url": old_url, "old_backup": backup})
    LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    log_ops("A/B縮圖", f"換縮圖 {video_id} → {Path(thumb_path).name}")
    print(f"[ok] 已換縮圖 {video_id}\n     新：{thumb_path}\n     舊備份：{backup or old_url or '（無法備份，僅未記）'}\n     （已記 log，可回溯還原）")
    return True


def _mark_applied(video_id, idx, path):
    """在 suggestions 檔標記某片 picked=idx、applied=True。"""
    data = _load(SUGGEST, {})
    for it in (data.get("items") or []):
        if it.get("video_id") == video_id:
            it["picked"] = idx
            it["applied"] = True
            it["applied_path"] = path
    if data:
        data["updated"] = tw_now()
        SUGGEST.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_apply(video_id: str, index: int) -> int:
    """--apply：套用 suggestions 檔中某片的第 index 個變體圖（對外，真換 live 縮圖）。"""
    data = _load(SUGGEST, {})
    item = next((i for i in (data.get("items") or []) if i.get("video_id") == video_id), None)
    if not item:
        print(f"[error] suggestions 檔沒有 {video_id}；請先跑一次產建議。", file=sys.stderr)
        return 2
    variants = item.get("variants") or []
    v = next((x for x in variants if x.get("idx") == index), None)
    if v is None and 0 <= index < len(variants):
        v = variants[index]
    if not v:
        print(f"[error] 變體 index {index} 超出範圍（0..{len(variants)-1}）。", file=sys.stderr)
        return 2
    path = v.get("path")
    if not path:
        print(f"[error] 變體[{index}] 沒有已 render 的圖檔（path 為空）。", file=sys.stderr)
        return 2
    print(f"[apply] {video_id} → 變體[{index}]（{v.get('accent')}/{v.get('angle')}）：{path}")
    if apply_thumbnail(video_id, path):
        _mark_applied(video_id, index, path)
        return 0
    return 1


def cmd_auto_apply() -> int:
    """--auto-apply：對每支未套用的片套用 picked（沒選則變體[0]）。對外、危險，需明確旗標。"""
    data = _load(SUGGEST, {})
    items = [i for i in (data.get("items") or []) if not i.get("applied")]
    if not items:
        print("[info] 沒有待套用的建議（都套用過或無建議）。")
        return 0
    print(f"[auto-apply] 將對 {len(items)} 支已發布片換新縮圖（對外動作）…")
    done = 0
    for it in items:
        vid = it.get("video_id")
        idx = it.get("picked")
        if idx is None:
            idx = 0
        variants = it.get("variants") or []
        v = next((x for x in variants if x.get("idx") == idx), None) or (variants[0] if variants else None)
        if not v or not v.get("path"):
            continue
        if apply_thumbnail(vid, v["path"]):
            _mark_applied(vid, v.get("idx", idx), v["path"])
            done += 1
        time.sleep(1.0)
    print(f"[auto-apply] 完成：{done}/{len(items)} 支已換縮圖。")
    return 0


# --------------------------------------------------------------------------- #
# 5) ingest_winner：套用後對比 views/retention，把勝出 accent 寫回（供未來偏好）
# --------------------------------------------------------------------------- #

def ingest_winner():
    """對已套用（applied）的片，比對『套用當下』與『現在』的 views/retention，
    把有明顯改善（觀看或完播上升）的變體 accent 記到 STUDIO/ab_thumb_winners.json，
    供 make_thumbnails/derive_cfg 未來偏好參考。純讀寫本機 json，不碰網路。"""
    data = _load(SUGGEST, {})
    scores = _load(SCORES, {})
    live = {p.get("videoId"): p for p in (scores.get("published") or []) if p.get("videoId")}
    winners_path = STUDIO / "ab_thumb_winners.json"
    winners = _load(winners_path, {"updated": "", "by_accent": {}, "notes": []})
    if not isinstance(winners, dict):
        winners = {"updated": "", "by_accent": {}, "notes": []}
    by_accent = winners.setdefault("by_accent", {})
    notes = []
    for it in (data.get("items") or []):
        if not it.get("applied"):
            continue
        vid = it.get("video_id")
        cur = live.get(vid) or {}
        picked = it.get("picked")
        v = next((x for x in (it.get("variants") or []) if x.get("idx") == picked), None)
        if not v:
            continue
        acc = v.get("accent") or "unknown"
        before_v, after_v = it.get("views") or 0, cur.get("views") or 0
        before_r, after_r = it.get("retention") or 0, cur.get("retention") or 0
        improved = (after_v > before_v) or (after_r > before_r)
        rec = by_accent.setdefault(acc, {"win": 0, "lose": 0})
        rec["win" if improved else "lose"] += 1
        notes.append({"video_id": vid, "accent": acc,
                      "views": [before_v, after_v], "retention": [before_r, after_r],
                      "improved": improved})
    winners["updated"] = tw_now()
    winners["notes"] = notes[-50:]
    winners_path.write_text(json.dumps(winners, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] ingest_winner：{len(notes)} 支已套用片評估完成 → {winners_path.name}")
    return winners


# --------------------------------------------------------------------------- #
# 輸出 / main
# --------------------------------------------------------------------------- #

def print_payload(payload):
    m = payload.get("diagnostics", {})
    print(f"[A/B 縮圖建議] {payload.get('updated','')}")
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
        for v in it["variants"]:
            print(f"   變體[{v['idx']}] {v.get('accent')}（{ACCENT_MEANING.get(v.get('accent'),'')}）"
                  f"｜{v.get('l1')} / {v.get('l2')}｜{v.get('angle')}"
                  + (f"｜{v.get('path')}" if v.get("path") else "｜(圖未產出)"))


def main() -> int:
    ap = argparse.ArgumentParser(description="A/B 縮圖迭代：對低完播/低觀看的已發布片產更強變體縮圖（預設只建議＋圖，不換 live）。")
    ap.add_argument("--limit", type=int, default=8, help="最多處理幾支低表現片（預設 8）")
    ap.add_argument("--retention-floor", type=float, default=40.0, help="完播率低於此值視為偏低（預設 40）")
    ap.add_argument("--variants", type=int, default=2, help="每支除 base 外再產幾個變體（預設 2）")
    ap.add_argument("--dry", action="store_true", help="只印建議、render 變體圖、不寫檔（不改任何 live 影片）")
    ap.add_argument("--no-render", action="store_true", help="不 render 變體圖（只產文字建議，除錯用）")
    ap.add_argument("--apply", nargs=2, metavar=("VIDEO_ID", "INDEX"),
                    help="套用某片的第 INDEX 個變體圖（對外！真換 live 縮圖）")
    ap.add_argument("--auto-apply", action="store_true",
                    help="一次套用所有 picked/預設變體（對外！真換 live 縮圖）")
    ap.add_argument("--ingest", action="store_true", help="評估已套用片的成效變化，寫回勝出 accent（純本機）")
    args = ap.parse_args()

    # ── 對外套用路徑（唯二會換 live 的入口，需明確旗標）──
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
    if args.ingest:
        ingest_winner()
        return 0

    # ── 預設路徑：只產建議＋變體圖，不換任何 live 縮圖 ──
    do_render = not args.no_render
    if args.dry:
        payload = build_suggestions(limit=args.limit, retention_floor=args.retention_floor,
                                    n_extra=args.variants, do_render=do_render)
        print_payload(payload)
        if not payload.get("items"):
            print("\n[dry] 無低完播片，未寫任何檔。")
        else:
            print("\n[dry] 以上為建議；變體圖已 render 供預覽，但未寫檔、未換任何 live 縮圖。")
        return 0

    payload = build_suggestions(limit=args.limit, retention_floor=args.retention_floor,
                                n_extra=args.variants, do_render=do_render)
    payload = _merge_prev_choices(payload)
    STUDIO.mkdir(parents=True, exist_ok=True)
    SUGGEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print_payload(payload)
    n = len(payload.get("items") or [])
    with_var = sum(1 for it in payload["items"] if len(it["variants"]) > 1)
    log_ops("A/B縮圖", f"產建議 {n} 支（{with_var} 支有 LLM 變體）→ ab_thumb_suggestions.json")
    print(f"\n[ok] 已寫 {SUGGEST.name}：{n} 支候選（{with_var} 支有多變體）。"
          f"預設不換 live；要套用請按決策中心按鈕或用 --apply/--auto-apply。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
