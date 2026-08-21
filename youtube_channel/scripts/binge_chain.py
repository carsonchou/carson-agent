#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""binge_chain.py — 把全頻道長片串成「一部接一部」的連播鏈。

## 解的是哪個實測問題(2026-08 量測)
- 50 支長片抽驗:**0 支**描述有指向另一支影片的連結——每支片都是死路
- 播放清單來源每次觀看 **137 秒**(全來源最高),但 28 天只有 **49 次**觀看
- 片約 4 天死透([[yt-video-lifespan-4days]]),因為沒有任何機制把舊片接進新流量

## 機制(為什麼是這三行連結)
1. 「▶ 接著看下一集」用 `watch?v=NEXT&list=PL` 格式——**點了會帶著播放清單軌進場,
   看完自動接下一支**。這是 YouTube 原生的連播機制,不是裝飾性連結。
2. 「📺 本系列自動連播」給整條清單入口。
3. 「🔔 訂閱」帶 `?sub_confirmation=1`,點開直接彈訂閱確認框。

## 鏈的結構:環狀
每支片的「下一集」= 同系列的下一支;最後一支繞回第一支 → **每支片永遠有下一集**,
鏈沒有斷點。系列歸屬優先序:
  個股體檢(代號+股名雙命中,防文案數字誤判)→ 產業清單(9 條)
  → 真相實驗室 → ETF定投 → EP實測 → 避雷拆穿 → 台股量化/AI×交易(兜底)

## 安全(沿用 desc_backfill.py 的驗證過骨架)
- **只動自己的區塊**:區塊由固定哨兵行包夾;已存在→整塊替換(鏈要能隨新片更新),
  不存在→插在第一段之後。任何情況下把區塊拿掉必須還原回原文,不一致就跳過該支。
- 長度 ≤ 4900 才寫;寫回帶完整 snippet(title/categoryId/tags 原樣保留——
  **videos.update 的 snippet 是整包覆寫**,漏帶欄位會被清掉)。
- 狀態逐支落地 STUDIO/binge_chain_state.json;quotaExceeded 優雅停。
- 配額:videos.list 批次 50 支/1 單位;videos.update 50 單位/支。

用法:
  python scripts/binge_chain.py --dry-run          # 本地算鏈,不連網
  python scripts/binge_chain.py --max 120          # 正式跑(依流量優先序)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
STUDIO = ROOT / "STUDIO"
LEDGER = STUDIO / "uploaded_ledger.json"
IND_MAP = STUDIO / "industry_map.json"
IND_PL = STUDIO / "industry_playlists.json"
PE = STUDIO / "playlist_engine.json"
BUCKETS = STUDIO / "playlists.json"
BASELINE = STUDIO / "binge_baseline.json"
STATE = STUDIO / "binge_chain_state.json"
TOKEN = ROOT / "token_manage.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

BAR = "━━━━━━━━━━━━"
SENTINEL = "▶ 接著看下一集"
HANDLE = "carsonquant"

BLOCK_TMPL = (BAR + "\n"
              + SENTINEL + ":\n"
              + "https://www.youtube.com/watch?v={nxt}&list={pl}\n"
              + "📺 本系列自動連播:\n"
              + "https://www.youtube.com/playlist?list={pl}\n"
              + "🔔 訂閱不漏接:https://www.youtube.com/@" + HANDLE + "?sub_confirmation=1\n"
              + BAR)

# 區塊比對:第一個 BAR 行(緊接哨兵)到下一個 BAR 行,含前後至多一個換行
BLOCK_RE = re.compile(
    re.escape(BAR) + r"\n" + re.escape(SENTINEL) + r".*?" + re.escape(BAR),
    re.S)

# 嚴格模板:replace 前驗證舊區塊「整段」就是我們的標準形狀,防吞使用者文字。
# (驗證員實證:半殘區塊會讓 BLOCK_RE 吞掉使用者原文,且還原檢查看不見;
#  第一版「長度上限」防線實測擋不住——吞文的匹配段反而更短。fullmatch 才是定案。)
STRICT_BLOCK_RE = re.compile(
    re.escape(BAR) + "\n"
    + re.escape(SENTINEL) + ":\n"
    + r"https://www\.youtube\.com/watch\?v=[\w-]+&list=[\w-]+" + "\n"
    + "📺 本系列自動連播:\n"
    + r"https://www\.youtube\.com/playlist\?list=[\w-]+" + "\n"
    + "🔔 訂閱不漏接:https://www.youtube.com/@" + HANDLE + r"\?sub_confirmation=1" + "\n"
    + re.escape(BAR))




def load(p, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def save_state(d):
    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE)


# ── 系列分類 ────────────────────────────────────────────────────────────────
_CODE_RE = re.compile(r"(?<!\d)(\d{4,6})(?!\d)")


def classify(slug, imap):
    """回 (series_key, sort_key)。sort_key 用於系列內排序。"""
    # 個股體檢:代號+股名雙命中(niche_scan 學到的教訓:只看數字會抓到文案數字)
    hits = []
    # 🔴 「臺/台」異體字:slug 寫「臺達電」、industry_map 是「台達電」,不正規化會
    #    讓幾十支體檢片對不上(dry-run 實測抓到臺達電/正達等掉進兜底桶)
    slug_n = slug.replace("臺", "台")
    # 🔴 代號常被連寫兩次(「正達31493149」):8 位數字串讓 \d{4,6} 兩側邊界
    #    完全匹配不到。改成:取每段數字串的 整串(若4-6位)/前4/前5/前6 當候選,
    #    反正還有「股名必須同時出現」這道強過濾,不會誤抓。
    cands = []
    for m in re.finditer(r"\d+", slug):
        run = m.group(0)
        if 4 <= len(run) <= 6:
            cands.append(run)
        for L in (4, 5, 6):
            if len(run) > L:
                cands.append(run[:L])
    for code in dict.fromkeys(cands):
        info = imap.get(code)
        if info:
            nm = (info.get("name") or "").rstrip("*").replace("臺", "台")
            nm_base = nm.replace("-KY", "").replace("*", "")
            if nm and (nm in slug_n or (len(nm_base) >= 2 and nm_base in slug_n)):
                hits.append((code, info["industry"]))
    if hits:
        code, ind = max(hits, key=lambda h: len(h[0]))
        return ("checkup:" + ind, code)
    if "真相實驗室" in slug or "臺股真相" in slug:
        return ("truth_lab", None)
    if re.search(r"00\d{2,3}|0050|0056|定投|DCA|高股息|存股", slug):
        return ("etf_dca", None)
    if re.search(r"EP\d|機器人.*實測|實測.*機器人|網格.*實測", slug):
        return ("ep_live_test", None)
    if re.search(r"避雷|迷思|流言|騙|割韭菜|拆穿|陷阱", slug):
        return ("beginner_debunk", None)
    if re.search(r"AI|Claude|自動交易|程式交易", slug, re.I):
        return ("bucket:AI×交易", None)
    return ("bucket:台股量化", None)


def build_chain(dry=False):
    """回 [{vid, slug, series, next_vid, playlist_id}](已按流量優先序排列)。"""
    ledger = load(LEDGER, {})
    imap = (load(IND_MAP, {}) or {}).get("map", {})
    ind_pl = (load(IND_PL, {}) or {}).get("playlists", {})
    pe = load(PE, {}) or {}
    buckets = load(BUCKETS, {}) or {}

    pl_of = {}
    for ind, rec in ind_pl.items():
        pl_of["checkup:" + ind] = rec["id"]
    for k in ("truth_lab", "etf_dca", "ep_live_test", "beginner_debunk"):
        if k in pe and pe[k].get("playlist_id"):
            pl_of[k] = pe[k]["playlist_id"]
    for k, v in buckets.items():
        if isinstance(v, dict) and v.get("playlist_id"):
            pl_of["bucket:" + k] = v["playlist_id"]
    fallback_checkup = (pe.get("stock_checkup") or {}).get("playlist_id")

    # 只做長片(S_ 開頭是 Shorts:實測轉化率是長片的 1/12,而且 Shorts 描述幾乎沒人看)
    groups = {}
    for slug, vid in ledger.items():
        if not isinstance(vid, str) or not vid or slug.startswith("S_"):
            continue
        key, sort_key = classify(slug, imap)
        groups.setdefault(key, []).append((sort_key or "", slug, vid))

    rows = []
    singles = []
    for key, members in groups.items():
        pl = pl_of.get(key)
        if pl is None and key.startswith("checkup:"):
            pl = fallback_checkup
        if pl is None:
            continue                        # 沒清單可掛的系列,不硬塞
        # 系列內排序:體檢按代號,其餘按台帳寫入序(append-only = 發布序)
        if key.startswith("checkup:"):
            members.sort(key=lambda m: m[0])
        n = len(members)
        if n == 1:
            # 🔴 單支系列不能發沒有哨兵行的殘缺區塊(BLOCK_RE 比對不到→重跑會重複插入)。
            #    改把所有單支系列收進一個跨系列環,它們也獲得真實的「下一集」。
            singles.append({"vid": members[0][2], "slug": members[0][1],
                            "series": key, "pl": pl})
            continue
        for i, (_, slug, vid) in enumerate(members):
            nxt = members[(i + 1) % n][2]   # 環狀:最後一支繞回第一支
            rows.append({"vid": vid, "slug": slug, "series": key,
                         "next": nxt, "pl": pl})

    # 單支系列串成跨系列環(每支保留自己的清單連結,next 指向下一個單支)
    m = len(singles)
    for i, r in enumerate(singles):
        r["next"] = singles[(i + 1) % m]["vid"] if m > 1 else None
        if r["next"]:
            rows.append(r)

    # 流量優先序:近90天分鐘數高的先做(Analytics 基準檔)
    base = load(BASELINE, {}) or {}
    rank = {v[0]: i for i, v in enumerate(base.get("top_videos", []))}
    rows.sort(key=lambda r: rank.get(r["vid"], 10 ** 6))
    return rows


# ── 描述改寫 ────────────────────────────────────────────────────────────────
def apply_block(desc, block):
    """插入或替換自己的區塊。回 (新描述, 動作)。驗證:拿掉區塊必須還原原文。"""
    desc = desc or ""
    m = BLOCK_RE.search(desc)
    if m:
        # 🔴 驗證員實證的吞文路徑:舊區塊被手動刪掉結尾 BAR 時,非貪婪比對會
        #    一路吃到「下一條 BAR」,把中間的使用者原文一起吞掉——而還原檢查兩邊
        #    用同一個 regex,吞掉的文字在兩邊都消失,結構上看不見。
        #    防線:匹配到的舊區塊長度不得超過標準區塊 + 80 字元,超過=有夾帶,跳過。
        # 定案防線:匹配段必須整段完全符合標準模板(fullmatch);
        # 第一版長度上限實測擋不住(吞文的匹配段反而更短)。被改過的區塊一律跳過。
        if not STRICT_BLOCK_RE.fullmatch(m.group(0)):
            return None, "stale-block-malformed"
        new = BLOCK_RE.sub(block, desc, count=1)
        if BLOCK_RE.sub("", new, count=1) != BLOCK_RE.sub("", desc, count=1):
            return None, "restore-check-failed"
        return new, "replaced"
    lines = desc.split("\n")
    # 插在第一個非空行之後(第一行通常是鉤子句,保持在最上面)
    at = 1
    for i, ln in enumerate(lines):
        if ln.strip():
            at = i + 1
            break
    new_lines = lines[:at] + ["", block, ""] + lines[at:]
    new = "\n".join(new_lines)
    if BLOCK_RE.sub("", new, count=1).replace("\n\n\n", "\n\n").strip() \
            != desc.replace("\n\n\n", "\n\n").strip():
        # 寬鬆比對(僅空行差異)仍不一致 → 保守跳過
        stripped = BLOCK_RE.sub("", new, count=1)
        if stripped.replace("\n", "") != desc.replace("\n", ""):
            return None, "restore-check-failed"
    return new, "inserted"


def yt_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    cr = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not cr.valid and cr.expired and cr.refresh_token:
        cr.refresh(Request())
    return build("youtube", "v3", credentials=cr, cache_discovery=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true",
                    help="真的寫入。不帶 = 乾跑(驗證員要求:與 storefront 語義統一,誤跑不傷)")
    ap.add_argument("--max", type=int, default=120, help="本輪最多更新幾支(50 quota/支)")
    a = ap.parse_args()

    rows = build_chain()
    from collections import Counter
    cnt = Counter(r["series"].split(":")[0] for r in rows)
    print(f"連播鏈:{len(rows)} 支長片,{len(set(r['series'] for r in rows))} 個系列")
    for k, v in cnt.most_common():
        print(f"   {k:12s} {v} 支")

    if a.dry_run or not a.apply:
        print("\n前 12 支(流量優先序):")
        for r in rows[:12]:
            nx = r["next"][:8] + "…" if r["next"] else "(單支,只掛清單)"
            print(f"   {r['vid']}  next={nx:14s} pl={r['pl'][:14]}  {r['slug'][:38]}")
        print("\n--dry-run:未連網。")
        return 0

    state = load(STATE, {}) or {}
    done = state.setdefault("done", {})       # vid -> {"next":..., "at":...}
    todo = [r for r in rows
            if done.get(r["vid"], {}).get("next") != r["next"]
            and done.get(r["vid"], {}).get("fails", 0) < 2][:a.max]
    print(f"\n待更新 {len(todo)} 支(已是最新狀態的跳過)")
    if not todo:
        return 0

    yt = yt_service()
    # 批次抓 snippet(50 支/1 單位)
    snip = {}
    ids = [r["vid"] for r in todo]
    for i in range(0, len(ids), 50):
        rr = yt.videos().list(part="snippet,status", id=",".join(ids[i:i + 50])).execute()
        for it in rr.get("items", []):
            snip[it["id"]] = it
    print(f"抓到 {len(snip)} 支現況(消失/被刪的自動跳過)")

    ok = fail = 0
    for r in todo:
        it = snip.get(r["vid"])
        if not it:
            done[r["vid"]] = {"next": r["next"], "at": time.strftime("%F %T"),
                              "note": "missing"}
            save_state(state)
            continue
        sn = it["snippet"]
        # 🔴 與平行系統協調(2026-08-21 發現):部分片描述在發布時已由產線寫入
        #    「▶ 下一集(EPxx):https://youtu.be/XXX」(EP 序)。兩個「下一集」各指一支
        #    會讓觀眾混亂 → 遇到就**採納它的目標**(EP 序的追劇語意更強),
        #    本區塊補它缺的 &list= 自動連播與訂閱鈕。它那行照insertion-only原則不動。
        m_ep = re.search("▶ 下一集[^\n]*?youtu\\.be/([\\w-]{11})",
                         sn.get("description", ""))
        if m_ep and m_ep.group(1) != r["vid"]:
            r = dict(r, next=m_ep.group(1))
        if r["next"]:
            block = BLOCK_TMPL.format(nxt=r["next"], pl=r["pl"])
        else:
            block = BLOCK_TMPL.replace(SENTINEL + ":\n"
                                       + "https://www.youtube.com/watch?v={nxt}&list={pl}\n",
                                       "").format(pl=r["pl"], nxt="")
        _desc0 = sn.get("description", "")
        # 清掉 2026-08-21 早上舊版工具留的「▶ 下一集(EPn):youtu.be/…」單行(7 支)。
        # 舊行與本版哨兵(▶ 接著看下一集 + BAR 區塊)不同,不清會出現兩個「下一集」。
        # 精確匹配整行才刪,不碰使用者其他文字。
        _desc0 = chr(10).join(
            l for l in _desc0.split(chr(10))
            if not re.fullmatch(r"▶ 下一集\(EP\d+\):https://youtu\.be/[\w-]+", l.strip()))
        new_desc, action = apply_block(_desc0, block)
        if new_desc is None or len(new_desc) > 4900:
            print(f"   ✗ {r['vid']} 跳過({action if new_desc is None else '超長'})")
            fail += 1
            continue
        # 寫回前備份原 snippet(repo 既有慣例:fix_period_disclaimer.py 同款,
        #  87 個歷史備份檔為證;驗證員指出本檔漏抄這條,已補)
        bdir = STUDIO / "desc_backup"
        bdir.mkdir(exist_ok=True)
        bpath = bdir / (r["vid"] + ".json")
        if not bpath.exists():          # 只留最早版本 = 最接近原始的
            bpath.write_text(json.dumps(it, ensure_ascii=False, indent=1),
                             encoding="utf-8")
        sn["description"] = new_desc
        try:
            yt.videos().update(part="snippet",
                               body={"id": r["vid"], "snippet": sn}).execute()
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "quotaExceeded" in msg:
                print("   ⛔ 配額用罄,優雅停止(狀態已逐支落地)")
                break
            print(f"   ✗ {r['vid']} {msg[:80]}")
            rec = done.setdefault(r["vid"], {})
            rec["fails"] = rec.get("fails", 0) + 1
            save_state(state)
            fail += 1
            continue
        done[r["vid"]] = {"next": r["next"], "at": time.strftime("%F %T"),
                          "action": action}
        save_state(state)
        ok += 1
        if ok % 20 == 0:
            print(f"   …已更新 {ok} 支")
    print(f"\n完成:更新 {ok} 支、失敗/跳過 {fail} 支。"
          f"約耗配額 {ok * 50 + (len(ids) + 49) // 50} 單位")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
