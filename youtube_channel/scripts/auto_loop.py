#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""auto_loop.py — 【即時自動閉環】把鬆散信號串成 3 條會自己轉的迴圈。

之前各部門各產各的信號(流量/品管/留言/完播),但「贏家→加碼」「好問題→即產」
「輸家→降權」這三條反饋鏈是斷的:數據躺在 json 裡,沒有東西自動把它接回產線。
這支就是那個接線員——每次跑都做三件事,全部只動**內部可逆檔**:

  迴圈① 贏家全押：從 traffic_signals.top_videos / quality published 找「完播明顯高」
        的贏家片,用 LLM 產「同角度 3-5 支 EP 續集/變體」→ topic_bank(front=True,
        source=auto_winner)。會紅的角度就多押幾支。
  迴圈② 好問題即產：把留言部挑出、已寫進題庫(source=comment)的小白高頻疑問,
        重新提到題庫最前面並標記 priority,確保下批優先製作。
  迴圈③ 輸家自動汰：找已發布片「完播明顯低於門檻且觀看夠樣本」的題材,把它的關鍵字
        寫進 production_orders.avoid_topics **降權**(別再一直產同類)。
        只降權——不刪片、不動標題、不碰已上線影片。

🚨 紅線:只准動 topic_bank / production_orders / auto_actions_log 這類內部檔。
   絕不碰:發布/排程、YouTube 改標題或刪片、買量、開通道、花錢。

用法:
  python scripts/auto_loop.py            # 正式跑(寫檔)
  python scripts/auto_loop.py --dry      # 只印「會全押X/會汰Y/會提前Z」,不動任何檔
  python scripts/auto_loop.py --only winner|comment|loser   # 只跑其中一條
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import studio_common as sc  # 共用地基：PERSONA / has_llm_key / evidence_block

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(d, m):  # type: ignore
        pass

STUDIO = ROOT / "STUDIO"
TRAFFIC = STUDIO / "traffic_signals.json"
QUALITY = STUDIO / "quality_scores.json"
COMPLETION = STUDIO / "completion_signals.json"
ORDERS = STUDIO / "production_orders.json"
ACTIONS_LOG = STUDIO / "auto_actions_log.json"

# ── 門檻(對齊本頻道實證:channel_28d 平均完播 ~43%)──────────────────────────────
WIN_PCT = 60.0          # 完播率 ≥ 此值 = 明顯贏家(高於頻道均值一大截)
WIN_MIN_VIEWS = 60      # 贏家最低觀看樣本(80→60:台股爆款更快達標、更早進贏家迴圈加碼)
WIN_MAX = 3             # 一次最多押幾個贏家角度(控節奏、控 token)
WIN_VARIANTS = 9        # 每輪產幾支續集/變體上限(7→9:瘋狂引流·贏家全押更兇,雙主軸AI×交易+台股續集)

LOSE_PCT = 40.0         # 完播率 < 此值 = 明顯輸家(低於頻道均值)
LOSE_MIN_VIEWS = 60     # 輸家最低觀看樣本(夠樣本才算數,避免誤殺新片)
LOSE_MAX = 6            # 一輪最多降權幾個題材(避免一次砍太多)


# ── 讀檔 / 存檔(全防缺檔,只碰內部可逆檔)──────────────────────────────────────

def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_tw() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def log_action(loop: str, detail) -> None:
    """把每次動作 append 一筆到 STUDIO/auto_actions_log.json({ts,loop,detail})。"""
    log = _load(ACTIONS_LOG, [])
    if not isinstance(log, list):
        log = []
    log.append({"ts": _now_tw(), "loop": loop, "detail": detail})
    _save(ACTIONS_LOG, log)


def _clean_title(slug_or_title: str) -> str:
    """把 slug/title 洗成可讀短片段(去 S_/L_ 前綴、#Shorts、標點)。"""
    t = re.sub(r"^[SL]_", "", (slug_or_title or "").strip())
    t = t.replace("#Shorts", "").replace("#shorts", "").strip()
    return t


def _keyword_pool() -> list[str]:
    """組關鍵字池:頻道實證贏家字 + 既有產線偏好字 + 基本題材詞。用來把片名歸類成題材。"""
    pool: list[str] = []
    ts = _load(TRAFFIC, {})
    if isinstance(ts, dict):
        pool += list(ts.get("win_keywords") or [])
        pool += list(ts.get("weak_keywords") or [])
    orders = _load(ORDERS, {})
    if isinstance(orders, dict):
        pool += list(orders.get("preferred_keywords") or [])
    pool += ["定投", "網格", "複利", "停利", "停損", "回測", "夏普", "馬丁", "風控", "槓桿",
             "勝率", "破產", "爆倉", "ETF", "BTC", "機器人", "實測", "被割", "詐騙", "新手", "派網"]
    # 去重(保序、簡繁不同視為不同,只求粗分類)
    seen, out = set(), []
    for k in pool:
        k = str(k).strip()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _match_keywords(text: str, pool: list[str], limit: int = 4) -> list[str]:
    hit = [k for k in pool if k and k in text]
    return hit[:limit]


# ── 迴圈① 贏家全押 ────────────────────────────────────────────────────────────

def _collect_winners() -> list[dict]:
    """合併 traffic_signals.top_videos(avg_pct) 與 quality published(retention),挑明顯贏家。"""
    winners: dict[str, dict] = {}

    ts = _load(TRAFFIC, {})
    for v in (ts.get("top_videos") or []) if isinstance(ts, dict) else []:
        if not isinstance(v, dict):
            continue
        slug = str(v.get("slug") or v.get("title") or "")
        pct, views = v.get("avg_pct"), v.get("views")
        if slug and _num(pct) and pct >= WIN_PCT and (not _num(views) or views >= WIN_MIN_VIEWS):
            winners[slug] = {"slug": slug, "title": _clean_title(v.get("title") or slug),
                             "pct": float(pct), "views": views if _num(views) else None}

    q = _load(QUALITY, {})
    for x in (q.get("published") or []) if isinstance(q, dict) else []:
        if not isinstance(x, dict):
            continue
        slug = str(x.get("slug") or "")
        ret, views = x.get("retention"), x.get("views")
        if slug and _num(ret) and ret >= WIN_PCT and _num(views) and views >= WIN_MIN_VIEWS:
            prev = winners.get(slug)
            if not prev or float(ret) > prev["pct"]:
                winners[slug] = {"slug": slug, "title": _clean_title(x.get("title") or slug),
                                 "pct": float(ret), "views": views}

    out = sorted(winners.values(), key=lambda w: w["pct"], reverse=True)
    return out[:WIN_MAX]


def _gen_variants(winners: list[dict], n: int) -> list[dict]:
    """LLM 依贏家角度產 n 支同角度續集/變體題目。回 list[{title,angle,category,format}]。"""
    import llm  # 共用路由(主供應商→fallback)
    wl = "\n".join(f"  - 「{w['title']}」完播{round(w['pct'])}%"
                   + (f"、{w['views']}次觀看" if w.get("views") else "") for w in winners)
    prompt = f"""{sc.PERSONA}

{sc.evidence_block()}

你是量化阿森頻道的「贏家加碼」選題官。下面是本頻道**實測完播率明顯偏高**的贏家短片:
{wl}

請針對這些**已被證明會紅的角度**,產 {n} 支「同一角度的 EP 續集 / 變體」題目——
延續同樣的鉤子邏輯(數字戳破直覺 / 我先幫你試別自己送死 / 怕被割避雷),換場景、
換標的或換一個新反直覺結論,但保留讓它紅的那條神經。若贏家本身是台股題,續集不限主題(個股/大盤/ETF/當沖/存股都可,
別硬拉回加密網格),角度維持數據/回測/拆穿/避雷、不喊單、不報明牌、不喊目標價、不保證會漲。誠信鐵則:不保證收益、不喊單、
不編造損益、不用躺賺穩賺等誇大詞。小白定位軟性帶入即可、不必每支都硬套。

🔴 **數字紀律(2026-07-17 加,治長片被誠信守門擋掉的根因)**:以前這裡寫「換數字」,等於叫你
每支都掰一個新績效數字。實案:auto_winner 種出「AI策略回測贏大盤…」這種題,系統**根本沒有
「AI策略回測」這個引擎**,寫稿的人湊不出十分鐘只好編(「年化報酬高達百分之八十」「國外研究
發現八成是過度擬合」),整支長片渲染完才被發布端擋掉、產能全白燒。所以:
①標題/切入點裡的績效數字**只能從上面【實證】區塊挑**,那裡沒有的數字就不要放進題目;
②真的要用「勝率90%」這種數字當鉤子,**只准當成別人的宣稱來拆穿**(寫成「號稱勝率90%?」
「宣稱…」),不可以寫成本頻道實測到的結果;
③**format 選 long 的門檻更高**:十分鐘長片要用真數據撐滿,所以只有「上面【實證】區塊真的
有這個標的/情境的數字」時才可以選 long;查不到就選 short。寧可少一支長片,也不要一支被擋的。

只輸出 JSON 陣列(不要其他字、不要 markdown 圍欄):
[{{"title":"標題","angle":"一句話獨特切入點(延續哪個贏家角度)","category":"網格交易/定投DCA/回測數據/風控心法/工具派網/市場觀念/小白避雷/我幫你試實測/台股大盤ETF 擇一","format":"short 或 long"}}]"""
    txt = llm.complete(prompt, 3000, json_mode=True)
    m = re.search(r"\[.*\]", txt, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    items = []
    for om in re.finditer(r"\{[^{}]*\}", txt, re.S):
        try:
            items.append(json.loads(om.group(0)))
        except Exception:
            continue
    return items


def loop_winner(dry: bool) -> dict:
    winners = _collect_winners()
    if not winners:
        print("① 贏家全押：目前沒有完播明顯偏高的贏家(門檻 完播≥%.0f%% / 觀看≥%d),略過。"
              % (WIN_PCT, WIN_MIN_VIEWS))
        return {"winners": 0, "added": 0}

    names = "、".join(f"「{w['title'][:16]}」({round(w['pct'])}%)" for w in winners)
    if dry:
        print(f"① 贏家全押：會全押 {len(winners)} 個贏家角度 → 產最多 {WIN_VARIANTS} 支續集/變體。")
        print(f"   贏家:{names}")
        return {"winners": len(winners), "added": 0, "dry": True}

    if not sc.has_llm_key():
        print("① 贏家全押：無任何 LLM key,無法產續集/變體,略過(不影響其他迴圈)。")
        return {"winners": len(winners), "added": 0, "skip": "no_llm_key"}

    try:
        variants = _gen_variants(winners, WIN_VARIANTS)
    except Exception as e:  # noqa: BLE001
        print(f"① 贏家全押：LLM 產題失敗:{e}", file=sys.stderr)
        return {"winners": len(winners), "added": 0, "error": str(e)[:120]}

    items = []
    _forced_short = 0
    for v in variants[:WIN_VARIANTS]:
        title = (v.get("title") or "").strip()
        if not title:
            continue
        # 🔴 2026-07-17 auto_winner 一律種短片(治「長片題100%沒憑據」的源頭)。
        # 根因:這支的依據是「完播率贏家的角度」——那是**表現統計**,不是**事實庫的一組數字**;
        # 它的 prompt 從頭到尾沒有 fact_key 概念、也沒有事實可綁,所以種出來的題結構上不可能有
        # 憑據。上面 prompt 第③條寫了「查不到數據就選 short」,但那只是**求 LLM 自律**、沒有任何
        # 程式碼在擋——實測結果:未用長片題 101 支裡 76 支出自 auto_winner 且 100% 無 fact_key,
        # 被誠信 gate 擋掉的長片也 100% 出自這裡。短片 30-45 秒講一個觀念不必用數據撐滿,
        # LLM 沒有「湊不滿十分鐘只好編」的壓力(長片才有),故降級成 short 而不是整個不種——
        # 贏家角度本身是真的有價值的,只是不該拿去餵最會逼出編造的長片路徑。
        # 要綁事實的贏家放大請走 winner_amplifier.py(它有 related_facts/fact_key 驗證機制)。
        if str(v.get("format", "short")).lower().startswith("l"):
            _forced_short += 1
        items.append({
            "title": title,
            "angle": (v.get("angle") or "").strip(),
            "category": (v.get("category") or "").strip(),
            "format": "short",
            "priority": "auto_winner",
        })
    if _forced_short:
        print(f"① 贏家全押：{_forced_short} 支 LLM 想選 long 的已強制降為 short"
              f"(auto_winner 無事實可綁,長片必被誠信守門擋→白燒產能;要長片走 winner_amplifier)。")

    added = 0
    if items:
        from topic_bank import add_topics
        added = add_topics(items, source="auto_winner", front=True)

    detail = {"winners": [w["slug"] for w in winners],
              "winner_titles": [w["title"][:24] for w in winners],
              "generated": len(items), "added": added}
    log_action("winner", detail)
    log_ops("自動閉環", f"贏家全押:{len(winners)} 贏家角度 → 新增 {added} 支續集/變體到題庫")
    print(f"① 贏家全押：{len(winners)} 個贏家角度 → 產 {len(items)} 支、新增 {added} 支到題庫(front, source=auto_winner)。")
    return {"winners": len(winners), "added": added}


# ── 迴圈② 好問題即產 ──────────────────────────────────────────────────────────

def loop_comment(dry: bool) -> dict:
    from topic_bank import load_bank, save_bank
    bank = load_bank()
    if not isinstance(bank, list):
        bank = []
    comment_unused = [t for t in bank
                      if isinstance(t, dict) and t.get("source") == "comment" and not t.get("used")]

    if not comment_unused:
        print("② 好問題即產：題庫裡沒有未製作的觀眾問題(source=comment),略過。")
        return {"promoted": 0}

    preview = "、".join(f"「{t.get('title', '')[:16]}」" for t in comment_unused[:5])
    if dry:
        print(f"② 好問題即產：會提前 {len(comment_unused)} 個觀眾好問題到題庫最前面(確保下批優先製作)。")
        print(f"   問題:{preview}")
        return {"promoted": len(comment_unused), "dry": True}

    # 重新排序:把 comment 題移到最前(保序),其餘接後;並標記 priority 提前
    ids = {id(t) for t in comment_unused}
    rest = [t for t in bank if id(t) not in ids]
    for t in comment_unused:
        t["priority"] = "comment"  # 提前記號(pull 端可據此優先)
    bank = comment_unused + rest
    save_bank(bank)

    titles = [t.get("title", "")[:24] for t in comment_unused]
    log_action("comment", {"promoted": len(comment_unused), "titles": titles})
    log_ops("自動閉環", f"好問題即產:{len(comment_unused)} 個觀眾問題提前到題庫最前")
    print(f"② 好問題即產：已把 {len(comment_unused)} 個觀眾問題提前到題庫最前(priority=comment)。")
    return {"promoted": len(comment_unused)}


# ── 迴圈③ 輸家自動汰 ──────────────────────────────────────────────────────────

def _collect_losers() -> list[dict]:
    """已發布片:完播明顯低於門檻且觀看夠樣本 = 輸家(要降權的題材)。"""
    q = _load(QUALITY, {})
    losers = []
    for x in (q.get("published") or []) if isinstance(q, dict) else []:
        if not isinstance(x, dict):
            continue
        ret, views = x.get("retention"), x.get("views")
        # retention 需 >0(=0 多為無數據,別誤殺);< 門檻且觀看夠樣本才算輸家
        if _num(ret) and 0 < ret < LOSE_PCT and _num(views) and views >= LOSE_MIN_VIEWS:
            losers.append({"slug": str(x.get("slug") or ""),
                           "title": _clean_title(x.get("title") or x.get("slug") or ""),
                           "ret": float(ret), "views": int(views)})
    losers.sort(key=lambda z: z["ret"])  # 最爛的先
    return losers[:LOSE_MAX]


def loop_loser(dry: bool) -> dict:
    losers = _collect_losers()
    if not losers:
        print("③ 輸家自動汰：目前沒有低完播且夠樣本的輸家(門檻 完播<%.0f%% / 觀看≥%d),略過。"
              % (LOSE_PCT, LOSE_MIN_VIEWS))
        return {"losers": 0, "downweighted": 0}

    pool = _keyword_pool()
    orders = _load(ORDERS, {})
    if not isinstance(orders, dict):
        orders = {}
    avoid = orders.get("avoid_topics")
    if not isinstance(avoid, list):
        avoid = []
    existing = "\n".join(str(a) for a in avoid)

    new_entries, planned = [], []
    for L in losers:
        kws = _match_keywords(L["title"], pool)
        frag = L["title"][:20]
        # 去重:同片段已在 avoid 就跳過(避免每天重複塞爆)
        if frag and frag in existing:
            continue
        kw_str = "/".join(kws) if kws else frag
        entry = (f"低完播降權:{kw_str}(實證 完播{round(L['ret'])}%<門檻{int(LOSE_PCT)}%、"
                 f"{L['views']}次觀看｜{frag})")
        new_entries.append(entry)
        planned.append({"slug": L["slug"], "keywords": kws or [frag],
                        "ret": L["ret"], "views": L["views"]})

    if not new_entries:
        print("③ 輸家自動汰：輸家題材都已在 avoid_topics 降權過,無新增。")
        return {"losers": len(losers), "downweighted": 0}

    kwd_preview = "、".join(p["keywords"][0] for p in planned)
    if dry:
        print(f"③ 輸家自動汰：會汰(降權) {len(new_entries)} 個低完播題材寫進 avoid_topics(不刪片、不動上線)。")
        print(f"   題材:{kwd_preview}")
        return {"losers": len(losers), "downweighted": len(new_entries), "dry": True}

    orders["avoid_topics"] = avoid + new_entries
    _save(ORDERS, orders)
    log_action("loser", {"downweighted": len(new_entries), "items": planned})
    log_ops("自動閉環", f"輸家自動汰:降權 {len(new_entries)} 個低完播題材(只降權不刪片)")
    print(f"③ 輸家自動汰：已把 {len(new_entries)} 個低完播題材寫進 avoid_topics 降權(只降權、不刪片、不動上線)。")
    return {"losers": len(losers), "downweighted": len(new_entries)}


# ── 進入點 ────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="auto_loop — 三條即時自動閉環(贏家全押/好問題即產/輸家自動汰)")
    ap.add_argument("--dry", action="store_true",
                    help="只印「會全押X/會提前Y/會汰Z」,不真的寫任何檔")
    ap.add_argument("--only", choices=["winner", "comment", "loser"], default=None,
                    help="只跑其中一條迴圈(不填=三條都跑)")
    args = ap.parse_args()

    mode = "乾跑(dry)" if args.dry else "正式"
    print(f"=== auto_loop 啟動｜{mode}｜{_now_tw()} ===")

    runs = {"winner": loop_winner, "comment": loop_comment, "loser": loop_loser}
    order = ["winner", "comment", "loser"]
    if args.only:
        order = [args.only]

    for name in order:
        try:
            runs[name](args.dry)
        except Exception as e:  # noqa: BLE001 一條掛掉不拖累其他兩條
            print(f"[warn] 迴圈 {name} 出錯(不影響其他迴圈):{e}", file=sys.stderr)

    print("=== auto_loop 結束 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
