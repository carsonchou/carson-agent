#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quality_score.py — 【倉庫評分官】給每支片 0–100 分＋依門檻判 pass/退件，供決策中心檢視。

評分＝規則式（不耗 AI、可無人值守）：以 audit_video 的檢查項目逐條扣分。
狀態：score < min_score → reject（建議退件重做）；否則 pass。min_score 存 boss_directives.json。
輸出 STUDIO/quality_scores.json 給 control_center『🎬 倉庫評分』分頁讀。

用法：
  python scripts/quality_score.py                 # 掃全倉庫、評分、寫 quality_scores.json
  python scripts/quality_score.py --set-min 75    # 設退件門檻為 75 分
  python scripts/quality_score.py --reject S_xxx  # 退件重做：隔離該片+釋放題目，下輪自動補產
  python scripts/quality_score.py --auto-reject    # 把低於門檻且『未發布』的自動退件（給排程用）
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
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
OUT = ROOT / "output"
STUDIO = ROOT / "STUDIO"
REJECT_DIR = OUT / "_rejected"
SCORES = STUDIO / "quality_scores.json"
LEDGER = STUDIO / "uploaded_ledger.json"
BANK = STUDIO / "topic_bank.json"
DIRECTIVES = STUDIO / "boss_directives.json"


def _load_env():
    """直跑時把專案根 .env 併進 os.environ(cron 由 local_cron 載;直跑沒有→llm.complete 拿不到
    OPENROUTER key→AI 評分靜默失敗、所有片停在未評分被 fail-closed 隔離永遠不發)。"""
    envf = ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text(encoding="utf-8", errors="replace").splitlines():
            s = ln.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()
TW = timezone(timedelta(hours=8))
DEFAULT_MIN = 70
# ── 不可調降的硬地板：任何情況分數低於 FLOOR 一律不得發布。 ──
# min_score（boss_directives.json）可往上調嚴，但 FLOOR 是紅線底線；
# 語意上永遠 FLOOR <= 生效門檻。發布端(daily_publish)以此做 fail-closed 攔截。
FLOOR = 60

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg): pass

import audit_video
import re
import studio_common as sc  # 共用地基：PERSONA / has_llm_key（路由已走 llm.complete）

# audit reason 關鍵字 → 硬扣分（技術/誠信硬傷，AI 分數之上再扣）
DEDUCT = [
    ("mp4 不存在", 100), ("無視訊軌", 45), ("無音軌", 45), ("片長過短", 35),
    ("檔案過小", 30), (".md 腳本不存在", 25), ("禁語", 50), ("Shorts 超過", 18),
    ("缺影片標題", 15), ("缺風險聲明", 12),
]


def _read_script(slug):
    """讀該片的標題＋旁白逐字稿，給 AI 評分。"""
    voice = OUT / f"{slug}.voice.txt"
    txt = voice.read_text(encoding="utf-8") if voice.exists() else ""
    return title_of(slug), txt[:1400]


def ai_score(slug):
    """Claude 真讀腳本，依四面向各 0–25 評分（鉤子/標題CTR/內容/誠信），回 dict 或 None。"""
    if not sc.has_llm_key():
        return None
    title, voice = _read_script(slug)
    if len(voice) < 40:
        return None
    prompt = (
        sc.PERSONA + "\n\n"
        "你是量化阿森（量化/網格/派網/回測/風控，繁中 faceless 短影音）的品管評審。"
        "依下列四面向評分，每項 0–25，**務必拉開分數**（多數片落在 12–20，只有真的強才 22+，嚴禁全給高分）：\n"
        "①hook 前2秒：第一句有具體數字或尖銳衝突才高分；平淡/慢熱開場 ≤10。\n"
        "②title 標題：有點擊公式（數字／反直覺／可搜尋長尾如『派網怎麼設』）才高分；空泛抽象名詞 ≤12。\n"
        "③content 內容：紮實正確清晰，且有『loop／二刷誘導』或結尾 reward 才接近滿分；純說教無記憶點 ≤15；"
        "通篇沒有對觀眾說「你」（缺第二人稱代入）再 −3。\n"
        "　新手友善(加分方向,非硬性):白話、小白聽得懂、走「我先幫你試/避雷」角度的**多加 1-2 分**;硬核術語沒翻人話**小扣 1-2 分**(但內容紮實正確仍可拿高分,別因題材硬核就打死)。\n"
        "④honesty 誠信：不誇大不喊單、有風險意識；出現躺賺／穩賺／保證／一天賺X／包賺 之類一律 ≤8。\n"
        # ── 校準:描述判準區間,不給單一死板數字(避免 AI 照抄同一分,分數才拉得開)──
        "【給分原則】每面向 0-25 分，務必**大膽用滿全距、把好壞拉開**；別怕給低分或給高分，"
        "也**別所有面向都給 18-22 的安全值**。同一批片彼此要有明顯高低差,平庸片就該落到中低段。\n"
        "・頂標區(22-25)：hook 首句就砸具體數字+反差(如『我丟10萬給機器人跑30天,結果賠了?』)、"
        "title 有點擊公式又可搜尋(如『派網網格怎麼設才不會賠?新手3步』)、content 紮實又有 loop/二刷鉤+對『你』說話+白話避雷、honesty 主動講風險與不保證。\n"
        "・中段區(13-19)：有到位但不出色——hook 有帶到主題卻不夠尖、title 有關鍵字但平、content 正確清楚卻沒 loop/記憶點、honesty 沒踩雷但也沒特別點風險。\n"
        "・不合格區(0-12)：平淡慢熱開場、空泛抽象標題、純說教無記憶點、或出現誇大用語(躺賺/穩賺/保證/包賺→honesty ≤8)。\n"
        f"標題：{title}\n旁白逐字稿：{voice}\n\n"
        # 🔴 2026-08-01 這行原本是 '…{"hook":N,"title":N,…}'。**`N` 不是合法 JSON**,
        # 模型照抄就產出不合法的內容。OpenRouter/DeepSeek 寬鬆所以放過,但 Groq 的
        # json_mode 會嚴格驗證 → HTTP 400「Failed to validate JSON」→ ai_score 的
        # `except: return None` 把錯吞掉 → status=unrated → daily_publish fail-closed
        # → **片子永遠不會發布,而且沒有任何告警**。實測 7 支已渲染長片就是這樣卡住的。
        # 改成用文字描述結構、**不給範例數字**:給具體數字會造成錨定
        # (本檔歷史上出過「一堆 82 分」的錨定問題,靠去錨定+溫度 0.1 才修好),
        # 所以寧可讓模型自己生 JSON,也不要塞一組會被照抄的示範分數。
        "只輸出一個 JSON 物件，不要任何其他文字、不要 markdown 圍欄。"
        "鍵:hook、title、content、honesty(四個值都是 0 到 25 的整數)，"
        "以及 note(字串，一句最該改的具體建議)。"
    )
    try:
        import llm  # 走共用路由(OpenRouter DeepSeek)，不再打死掉的 Anthropic
        # 🔴 2026-08-01 max_tokens 從 400 → 1200。400 太小:模型吐中文 note 時會
        # **在 JSON 中途被截斷** → 產出不合法 JSON。舊供應商(OpenRouter/DeepSeek)寬鬆,
        # 拿到截斷字串後下面的 regex 還能勉強撈到;但 Groq 的 json_mode 會嚴格驗證,
        # 直接回 HTTP 400「Failed to validate JSON」→ 被下面 `except: return None` 吞掉
        # → status=unrated → daily_publish fail-closed → **片子永遠不會發布,零告警**。
        # 實測:同一個 prompt,400 必失敗、1200 穩定成功。
        # ⚠️ 這是「靜默失敗」的教科書案例:錯誤被吞、狀態變成合法值(unrated)、
        #    沒有任何一層會叫——7 支已渲染好的長片就這樣卡了一整天沒人發現。
        txt = llm.complete(prompt, 1200, json_mode=True, temperature=0.1)  # 評分要穩、近決定性,不能用預設高溫亂漂
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            return None
        d = json.loads(m.group(0))
        for k in ("hook", "title", "content", "honesty"):
            d[k] = max(0, min(25, int(d.get(k, 0))))
        d["total"] = d["hook"] + d["title"] + d["content"] + d["honesty"]
        return d
    except Exception:
        return None


def tw_now():
    return datetime.now(TW).strftime("%Y-%m-%d %H:%M")


def _load(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except Exception:
        return default


def get_min():
    d = _load(DIRECTIVES, {})
    try:
        return int(d.get("min_score", DEFAULT_MIN))
    except Exception:
        return DEFAULT_MIN


def _score_of_slug(slug):
    """從 quality_scores.json 找該 slug 的分數；查不到／壞檔回 None（防呆，不拋例外）。"""
    try:
        data = _load(SCORES, {})
        if not isinstance(data, dict):
            return None
        for key in ("pending", "published", "items"):
            for it in (data.get(key) or []):
                if isinstance(it, dict) and it.get("slug") == slug:
                    return it.get("score")
    except Exception:  # noqa: BLE001
        return None
    return None


def passes_floor(slug_or_score) -> bool:
    """硬地板判定：分數 >= FLOOR 才回 True。
    參數可為分數(int/float) 或 slug(str，會去 quality_scores.json 查該片分數)。
    未評分(None)／查不到／型別意外一律回 False（fail-closed，寧可擋不可漏）。"""
    try:
        # 布林是 int 子類，先排除以免 True 被當 1 誤判
        if isinstance(slug_or_score, bool):
            return False
        if isinstance(slug_or_score, (int, float)):
            return slug_or_score >= FLOOR
        if isinstance(slug_or_score, str):
            s = slug_or_score.strip()
            if not s:
                return False
            try:  # 純數字字串直接當分數
                return float(s) >= FLOOR
            except ValueError:
                pass
            score = _score_of_slug(s)  # 否則當 slug 去查快取分數
            return isinstance(score, (int, float)) and not isinstance(score, bool) and score >= FLOOR
    except Exception:  # noqa: BLE001
        return False
    return False


def set_min(n):
    n0 = int(n)
    n = max(n0, FLOOR)  # FLOOR 是紅線底線,語意上永遠 FLOOR <= 生效門檻,不能被設更低(見檔頭註解)
    if n != n0:
        print(f"[warn] 門檻 {n0} 低於硬地板 FLOOR={FLOOR},已夾回 {FLOOR} 分")
    d = _load(DIRECTIVES, {})
    d["min_score"] = n
    sc.save_json_atomic(DIRECTIVES, d)
    log_ops("倉庫評分", f"退件門檻設為 {n} 分")
    print(f"[ok] 退件門檻 → {n} 分，重新評定 pass/退件…")
    scan(rescore_ai=False)  # 用快取分數依新門檻重判 pass/退件（快、不重跑 AI）


def title_of(slug):
    md = OUT / f"{slug}.md"
    if md.exists():
        try:
            first = md.read_text(encoding="utf-8").splitlines()[0]
            return first.replace("# 🎬", "").replace("#", "").strip()
        except Exception:
            pass
    return slug


def score_one(slug, ai):
    """合成分數＝AI 內容分(0-100) 再扣 audit 硬傷；無 AI 可評時退回合規分(100-硬扣)。"""
    ok, reasons = audit_video.audit(slug)
    ded = sum(w for kw, w in DEDUCT if any(kw in r for r in reasons))
    if ai:
        score = max(0, min(100, ai["total"] - ded))
    else:
        score = None  # 無法AI評分(缺腳本/限流失敗)→標「未評分」，不退回假100；UI顯示「—」、排最底、下輪自動重評
    return score, reasons


def all_slugs():
    """要評分的成片 slug。**排除 `_ytcta` 衍生檔**。

    🔴 2026-07-30 本檔是唯一沒排除衍生檔的地方,代價很具體:
      `append_yt_cta.py` 會產 `output/<slug>_ytcta.mp4`——那是給 IG/TikTok 接不同片尾卡的
      **衍生檔**,沒有自己的 .md／.voice.txt，所以審核永遠回「.md 腳本不存在」、
      AI 也永遠評不出分。實測 output 下有 **371** 個,造成三個後果:
        ①「未發布候選」被灌水:470 → 真實只有 **99**(而 daily_publish.find_candidates
          **有**排除衍生檔,算出 44——兩邊數字長期打架就是這個原因)。
        ②「未評分」373 支看起來像大災情,其中 371 是衍生檔,**真正未評分只有 2 支**。
        ③每輪評分空轉:未評分的片每支會 `ai_score` 失敗→sleep 6s→重試→再 sleep 1.5s,
          371 × 7.5s ≈ **46 分鐘純等待**,每次跑都白燒。
      而 daily_publish / produce_batch / ig_backfill / fact_source_guard / stall_watchdog /
      build_short_to_long **六支都已經排除**了——只有這裡漏掉。典型的「同一規則多份實作,
      漏一處就等於沒做」(同 memory yt-duplicate-impl-gate-bypass)。
    """
    slugs = set()
    for pat in ("S_*.mp4", "L_*.mp4"):
        for f in OUT.glob(pat):
            if "_ytcta" in f.stem:      # 衍生檔(可能疊成 _ytcta_ytcta),用 in 不用 endswith
                continue
            slugs.add(f.stem)
    return sorted(slugs)


def channel_published(yt):
    """從 YouTube 頻道 uploads 播放清單抓『真實已發布』影片(videoId,title)——含 ledger 沒記到的(如手動發的長片)。"""
    try:
        ch = yt.channels().list(part="contentDetails", mine=True).execute()
        plid = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        out, seen, tok = [], set(), None
        while True:
            r = yt.playlistItems().list(part="snippet,contentDetails", playlistId=plid,
                                        maxResults=50, pageToken=tok).execute()
            for it in r.get("items", []):
                vid = it["contentDetails"]["videoId"]
                if vid in seen:  # uploads 清單偶有重複，去重避免下游 ID 撞號
                    continue
                seen.add(vid)
                out.append((vid, it["snippet"].get("title", "")))
            tok = r.get("nextPageToken")
            if not tok:
                break
        return out
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 抓頻道影片失敗（改用 ledger）：{str(e)[:80]}", file=sys.stderr)
        return []


def scan(rescore_ai=False):
    ledger = _load(LEDGER, {})
    rev = {v: k for k, v in ledger.items()}  # videoId → slug
    min_score = get_min()
    p0 = _load(SCORES, {})
    prev = {}
    for key in ("pending", "published", "items"):
        for i in (p0.get(key) or []):
            if i.get("slug"):
                prev[i["slug"]] = i
    # 1) 評分本機所有 mp4（含未發布 queue ＋ 已發布但本機還留檔的）
    scored = {}
    new_ai = 0
    for slug in all_slugs():
        was = prev.get(slug, {})
        # 只要沒有『有效 ai 分數』就重評(含上次評分失敗存成 ai=None 的)——
        # 否則失敗一次就永久卡假 100(ai 是 None 但 key 存在 → 舊邏輯不再重評)。
        if rescore_ai or not was.get("ai"):
            ai = ai_score(slug)
            if ai:
                new_ai += 1
            else:
                time.sleep(6); ai = ai_score(slug)  # 疑似限流→退避後再試一次
                if ai:
                    new_ai += 1
            time.sleep(1.5)  # 節流,避免大批量連打被 OpenRouter 限流(這才是假100真兇)
        else:
            ai = was.get("ai")
        score_val, reasons = score_one(slug, ai)  # 別用 sc(=import studio_common as sc 的模組別名,會被覆蓋成int)
        scored[slug] = {"slug": slug, "title": title_of(slug), "score": score_val,
                        "reasons": reasons, "ai": ai, "ai_note": (ai or {}).get("note", "")}
    # 2) 未發布 queue ＝ 有 mp4 但不在 ledger（退件對象）
    pending = []
    for slug, it in scored.items():
        if slug in ledger:
            continue
        was = prev.get(slug, {})
        # 防退化「新版不得低於舊版」：未發布片新版分數 < 歷史舊版 → 隔離（重做只准升不准降）。
        # 用現成 prev 快照比對，不新造儲存；隔離失敗也不可中斷評分。
        _pv, _nv = was.get("score"), it["score"]
        if (isinstance(_pv, (int, float)) and not isinstance(_pv, bool)
                and isinstance(_nv, (int, float)) and not isinstance(_nv, bool)
                and _nv < _pv):
            try:
                _quarantine(slug)
            except Exception:  # noqa: BLE001
                pass
            pending.append(dict(it, status="degraded", published=False, videoId="", prev_score=_pv))
            log_ops("倉庫評分", f"防退化隔離：{slug} 新版 {_nv} < 舊版 {_pv}")
            continue
        if was.get("status") == "rejected_manual":
            st = "rejected_manual"
        elif it["score"] is None:
            st = "unrated"  # 未評分(下輪自動重評),不當 pass 也不當 reject
        else:
            st = "reject" if it["score"] < min_score else "pass"
        pending.append(dict(it, status=st, published=False, videoId=""))
    pending.sort(key=lambda x: (x["score"] is None, x["score"] or 0))  # None 排最底
    # 3) 已發布 ＝ 真實頻道 uploads（完整含長片）；抓不到才退回 ledger
    yt = None
    try:
        from decision_dept import yt_service
        yt = yt_service()
    except Exception:
        pass
    chan = channel_published(yt) if yt else []
    published = []
    if chan:
        for vid, title in chan:
            base = scored.get(rev.get(vid, ""))
            published.append({"slug": rev.get(vid) or vid, "title": title, "videoId": vid,
                              "score": base["score"] if base else None,
                              "ai": base["ai"] if base else None,
                              "ai_note": base.get("ai_note", "") if base else "",
                              "reasons": base["reasons"] if base else [],
                              "status": "published", "published": True})
    else:
        for slug, vid in ledger.items():
            base = scored.get(slug)
            published.append({"slug": slug, "title": (base or {}).get("title", slug), "videoId": vid,
                              "score": (base or {}).get("score"), "ai": (base or {}).get("ai"),
                              "ai_note": (base or {}).get("ai_note", ""), "reasons": (base or {}).get("reasons", []),
                              "status": "published", "published": True})
    # 4) 已發布附上真實成效（觀看／留存／CTR，YouTube Analytics；無 token 則略過）
    try:
        import yt_analytics as ya
        stats = ya.video_stats(days=180) or {}
    except Exception:
        stats = {}
    for p in published:
        st = stats.get(p["videoId"])
        if st:
            p["views"] = st.get("views")
            _ret = st.get("retention")
            p["retention"] = min(100.0, round(_ret, 1)) if _ret is not None else None  # loop重播Shorts原生會>100%,夾回合理上限
            p["avg_dur"] = round(st.get("avg_dur")) if st.get("avg_dur") is not None else None
            p["subs"] = st.get("subs")
    if stats:  # 有成效資料就按觀看高→低排（一眼看哪支最紅）；無資料維持頻道時間序
        published.sort(key=lambda x: (x.get("views") is None, -(x.get("views") or 0)))
    payload = {"updated": tw_now(), "min_score": min_score, "has_analytics": bool(stats),
               "summary": {"pending": len(pending), "published": len(published),
                           "pass": sum(1 for i in pending if i["status"] == "pass"),
                           "reject": sum(1 for i in pending if i["status"].startswith("reject"))},
               "pending": pending, "published": published}
    STUDIO.mkdir(parents=True, exist_ok=True)
    sc.save_json_atomic(SCORES, payload)
    s = payload["summary"]
    log_ops("倉庫評分", f"未發布 {s['pending']}(pass{s['pass']}/退{s['reject']})、已發布 {s['published']}（門檻{min_score}、新評AI{new_ai}）")
    print(f"[ok] 倉庫評分：未發布 {s['pending']} 支(pass {s['pass']}／退件 {s['reject']})、已發布 {s['published']} 支，"
          f"門檻 {min_score}，新評 AI {new_ai} → quality_scores.json")
    return payload


def _free_topic(title):
    """把該片對應的題庫題目標回未用，讓 produce_batch 重做（找不到就算了）。"""
    bank = _load(BANK, [])
    if not isinstance(bank, list):
        return
    import re
    norm = lambda t: re.sub(r"[\s，。！？、：；…·\-—()（）]+", "", (t or "")).lower()
    nt = norm(title)
    changed = False
    for t in bank:
        if t.get("used") and (norm(t.get("title", "")) == nt or norm(t.get("title", ""))[:12] == nt[:12]):
            t["used"] = False
            changed = True
    if changed:
        BANK.write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding="utf-8")


REMAKE_ANGLE = "重做版：同主題換更強的開場鉤子與 But/Therefore 結構，內容更紮實，守誠實鐵則"


def _quarantine(slug):
    """把某 slug 的檔案移到 _rejected（不釋放題目，純隔離較差的重做嘗試）。"""
    REJECT_DIR.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob(f"{slug}.*"):
        try:
            shutil.move(str(f), str(REJECT_DIR / f.name))
        except Exception:  # noqa: BLE001
            pass


def produce_until_pass(title, angle=REMAKE_ANGLE, tries=3):
    """產同主題新片直到分數 ≥ 門檻（最多 tries 次）；保留最高分那支、其餘隔離。
    回 (slug, score)。確保『重做出來的一定不低於門檻』(tries 用盡仍未過則保留最佳並警告)。"""
    from produce_batch import make_one
    mn = get_min()
    best, best_sc = None, -1
    for t in range(1, tries + 1):
        try:
            slug = make_one("short", topic_override={"title": title, "angle": angle})
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 第{t}次產片失敗：{str(e)[:70]}", file=sys.stderr); slug = None
        if not slug:
            continue
        sc, _ = score_one(slug, ai_score(slug))
        print(f"  第{t}次：{slug[:18]}… 得分 {sc}（門檻 {mn}）")
        if sc is None:  # AI 評分失敗(限流/腳本未就緒)→ 本輪不算數,別讓 None>=int 直接崩潰整個重做流程。
            print(f"  [warn] 第{t}次 {slug[:18]} 無法AI評分,暫不隔離、留給下輪 scan() 補評分。")
            continue  # 不隔離(未評分≠低分)、也不當 best,直接進下一次重做嘗試
        if sc >= mn:
            if best and best != slug:
                _quarantine(best)
            return slug, sc
        if sc > best_sc:
            if best:
                _quarantine(best)
            best, best_sc = slug, sc
        else:
            _quarantine(slug)
    if best:
        print(f"[warn] {title[:20]}：{tries} 次都沒過門檻 {mn}，保留最高分 {best_sc} 那支。")
    return best, best_sc


def _remake_now(title):
    """立刻重產同主題新片，且確保分數 ≥ 門檻（最多重試 3 次，保留最佳）。"""
    slug, sc = produce_until_pass(title, tries=3)
    ok = slug is not None
    print(f"[{'ok' if ok else 'warn'}] 立即重做：{title[:24]}（得分 {sc}{'，已達門檻' if ok and sc >= get_min() else ''}）")
    return ok


def reject(slug, manual=True, remake=False):
    """退件：把該片所有檔案隔離到 output/_rejected/。
    remake=True → 立刻重產一支同主題新片；否則釋放題目、下輪 produce_batch 自動補產。"""
    if slug in _load(LEDGER, {}):
        print(f"[warn] {slug} 已發布，退件只隔離本機檔案、不會動線上影片（要下架請用 set_public.py）。")
    REJECT_DIR.mkdir(parents=True, exist_ok=True)
    moved = 0
    title = title_of(slug)
    for f in OUT.glob(f"{slug}.*"):
        try:
            shutil.move(str(f), str(REJECT_DIR / f.name))
            moved += 1
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 移動 {f.name} 失敗：{e}")
    if remake:
        log_ops("倉庫評分", f"退件＋立即重做：{title[:24]}（隔離 {moved} 檔，重產中…）")
        print(f"[ok] 已退件：{slug}（隔離 {moved} 檔），立即重產同主題新片…")
        _remake_now(title)
    else:
        _free_topic(title)
        log_ops("倉庫評分", f"退件重做：{title[:24]}（隔離 {moved} 檔、釋放題目待補產）")
        print(f"[ok] 已退件：{slug}（隔離 {moved} 檔，釋放題目，下輪自動補產新片）")
    if manual:
        scan(rescore_ai=False)  # 重掃刷新清單（該片已移走/新片已產 → 反映最新）
    return 0


def remake_all():
    """把目前所有未發布囤片逐支退件＋立即重做（同主題、走現行昇華管線），含高於門檻的。
    給「全倉昇華」用：老闆要把昇華前的舊片全部用新品質重產一遍。"""
    scan(rescore_ai=False)  # 先刷新拿到最新 pending 快照
    data = _load(SCORES, {})
    pend = [it for it in (data.get("pending") or []) if it.get("slug")]
    total = len(pend)
    print(f"[remake-all] 倉庫未發布共 {total} 支，全部逐支重做（含高於門檻的）…")
    log_ops("倉庫評分", f"全倉昇華重做啟動：{total} 支逐支重產")
    done = 0
    for i, it in enumerate(pend, 1):
        slug, title, sc = it["slug"], it.get("title", it["slug"]), it.get("score")
        print(f"[remake-all] ({i}/{total}) 重做：{title[:24]}（原分 {sc}）")
        try:
            reject(slug, manual=False, remake=True)
            done += 1
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {slug} 重做失敗：{e}")
    scan(rescore_ai=False)
    print(f"[remake-all] 完成：{done}/{total} 支已重做")
    log_ops("倉庫評分", f"全倉昇華重做完成：{done}/{total} 支")
    return 0


def _norm(t):
    return re.sub(r"[\s，。！？、：；…·\-—()（）%？?]+", "", (t or "")).lower()


def tidy():
    """整理未發布佇列：同主題(標題正規化前14字)只留最高分那支、其餘隔離；
    留下的若仍 < 門檻，隔離後用 produce_until_pass 重產到過門檻。最後重掃。"""
    data = scan()
    mn = data["min_score"]
    groups = {}
    for it in data["pending"]:
        groups.setdefault(_norm(it["title"])[:14], []).append(it)
    dup_removed = remade = 0
    for key, items in groups.items():
        items.sort(key=lambda x: -(x["score"] or 0))
        best = items[0]
        for it in items[1:]:           # 同主題其餘版本一律隔離（去重）
            _quarantine(it["slug"]); dup_removed += 1
        if (best["score"] or 0) < mn:   # 留下的還沒過門檻 → 隔離後重產到過
            _quarantine(best["slug"])
            slug, sc = produce_until_pass(best["title"], tries=3)
            if slug:
                remade += 1
            print(f"[tidy] 重產到門檻：{best['title'][:24]}（{sc}）")
    qs = scan(rescore_ai=False)
    log_ops("倉庫整理", f"去重 {dup_removed} 支、重產 {remade} 支至門檻 {mn}")
    print(f"[ok] 倉庫整理完成：去重 {dup_removed} 支、重產 {remade} 個主題至門檻 {mn}；"
          f"現未發布 {qs['summary']['pending']} 支(pass {qs['summary']['pass']})。")
    return 0


def auto_reject():
    """排程用：把『未發布且低於門檻』的自動退件並『立即重做到過關』。
    remake=True → 走已存在的 produce_until_pass（隔離舊片＋重產到 >= 門檻），
    讓「低於地板→自動重做」真的發生，而非只隔離。"""
    data = scan()
    n = 0
    for i in data["pending"]:
        if i["status"] == "reject":
            try:
                reject(i["slug"], manual=False, remake=True); n += 1
            except Exception as e:  # noqa: BLE001  單支重做失敗不可中斷整批
                print(f"[warn] {i['slug']} 自動重做失敗：{str(e)[:70]}", file=sys.stderr)
    if n:
        scan(rescore_ai=False)
    log_ops("倉庫評分", f"自動退件 {n} 支未發布低分片")
    print(f"[ok] 自動退件 {n} 支（未發布、低於門檻 {data['min_score']}）。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set-min", type=int, default=None)
    ap.add_argument("--reject", default=None)
    ap.add_argument("--remake", action="store_true", help="配合 --reject：退件後立刻重產同主題新片")
    ap.add_argument("--auto-reject", action="store_true")
    ap.add_argument("--remake-all", action="store_true", help="把所有未發布囤片逐支退件+重做(昇華後品質),含高於門檻的")
    ap.add_argument("--tidy", action="store_true", help="整理佇列：同主題去重留最高分、不足門檻者重產到過")
    ap.add_argument("--rescore-ai", action="store_true", help="強制全部重跑 AI 內容評分（平常用快取）")
    args = ap.parse_args()
    if args.set_min is not None:
        set_min(args.set_min); return 0
    if args.reject:
        return reject(args.reject, remake=args.remake)
    if args.remake_all:
        return remake_all()
    if args.tidy:
        return tidy()
    if args.auto_reject:
        return auto_reject()
    scan(rescore_ai=args.rescore_ai)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
