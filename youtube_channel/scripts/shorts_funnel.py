#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shorts_funnel.py — 【白帽漏洞③｜Shorts 切片漏斗 SOP】

Shorts 養帳號權重 → 灌長片：一支長片自動規劃 3–5 支 Shorts 的『切點 + 導流文案』，
每支 Short 拋一個鉤子、片尾導去長片/主頻道，形成一個『同主題引流叢集』。
對 faceless 量產特別有利（一份長內容裂變成多支高曝光 Shorts，互相拉抬權重）。

輸入優先序：
  1) output/ 內『尚未切過』的長片腳本 L_*.md（真的有長片時，照逐字稿挑切點）。
  2) 沒有新長片時，退而從題庫抽一個未用的 long 題目當『叢集主題』，規劃 3–5 支 Shorts。
輸出：
  - 把規劃出的 Shorts 題目灌進 STUDIO/topic_bank.json（parent=長片slug/主題，source=funnel）。
  - 一份人看的切片 SOP：STUDIO/REPORTS/{date}_切片漏斗_{slug}.md。
誠信鐵則：導流文案不誇大、不喊單、不保證收益。
用法：python scripts/shorts_funnel.py [--max 2] [--per 4] [--dry]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import studio_common as sc  # noqa: E402  共用地基：PERSONA、has_llm_key、evidence_block
STUDIO = ROOT / "STUDIO"
OUT = ROOT / "output"
REPORTS = STUDIO / "REPORTS"
BANK = STUDIO / "topic_bank.json"
SEEN = STUDIO / "funnel_seen.json"
TW = timezone(timedelta(hours=8))

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg): pass

try:
    from produce_batch import GUARD
except Exception:  # noqa: BLE001
    GUARD = "誠信鐵則：不保證收益、不喊單、不編造損益。頻道=量化阿森。"


def tw_today():
    return datetime.now(TW).strftime("%Y-%m-%d")


def _load_seen():
    try:
        return set(json.loads(SEEN.read_text(encoding="utf-8"))) if SEEN.exists() else set()
    except Exception:
        return set()


def _save_seen(seen):
    try:
        SEEN.write_text(json.dumps(sorted(seen), ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _long_scripts(seen):
    """找尚未切過的長片腳本：output/L_*.md，回傳 [(slug, title, content)]。

    2026-08-12 贏家優先:舊版 sorted(glob) = **字母序**,切到哪支全看檔名。跨頻道研究
    (20 頻道實抓)的結論是:同行 Shorts 成功的全是「從已成功的長片切出的結論」,獨立產
    的 Shorts 就是我們自己量到的 0.04 訂閱/支。改成:已發布且有觀看的長片按觀看數
    降冪排最前(贏家先切),未發布/查無觀看的排後(字母序維持穩定)。"""
    views = {}
    try:
        _q = json.loads((STUDIO / "quality_scores.json").read_text(encoding="utf-8"))
        for it in (_q.get("published") or []):
            if it.get("slug"):
                views[it["slug"]] = it.get("views") or 0
    except Exception:  # noqa: BLE001
        pass
    res = []
    for f in sorted(OUT.glob("L_*.md")):
        slug = f.stem
        if slug in seen:
            continue
        try:
            txt = f.read_text(encoding="utf-8")
            first = txt.splitlines()[0] if txt else ""
            title = first.replace("# 🎬", "").replace("#", "").strip()
            res.append((slug, title or slug, txt))
        except Exception:
            continue
    res.sort(key=lambda r: -views.get(r[0], 0))
    return res


def _pull_long_topic(consume=True):
    """退路：題庫抽一個未用 long 題目當叢集主題。consume=True 才標記已用＋寫檔（dry 模式不動資料）。
    回傳 (seed_id, title, angle) 或 None。"""
    if not BANK.exists():
        return None
    try:
        bank = json.loads(BANK.read_text(encoding="utf-8"))
    except Exception:
        return None
    for t in bank:
        if not t.get("used") and t.get("format") == "long":
            if consume:
                t["used"] = True
                try:
                    BANK.write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception:
                    pass
            return (t.get("id", ""), t.get("title", ""), t.get("angle", ""))
    return None


def _drop_untraceable(items, body, title):
    """誠信閘:切片題的每個數字都必須在來源長片裡找得到,否則整支丟掉。

    🔴 2026-08-14 實測抓到(這條管線原本**完全沒有溯源檢查**):LLM 為聯鈞那支
    規劃的 5 支切片裡,有 3 支帶著長片根本沒有的數字——「單筆賺 18.8%、定投賺 22.4%」
    (22.4 其實是總報酬 4322.**4**% 的尾數被誤讀成獨立數字)、「-67.5% 巨坑」、
    「卡瑪比率 0.24」。這些題會直接變成 Shorts 的標題與內容 → 等於在**封面**上印
    編造績效,正是 fact_guard 當初要擋的事,只是那道閘門只裝在長片產線上。
    (同型病灶見 memory yt-duplicate-impl-gate-bypass:閘門只裝在一條路上。)

    判準:標題與 angle 裡每個「帶單位的數字」(%、倍、年、萬…)必須在來源長片文字中
    出現。**fail-closed**:對不上就丟掉那一支,寧可少產也不要產帶假數字的題。
    比對用去掉逗號的原字串,並允許 4322.4 這種長數字包含短數字的情況——
    但 22.4 只出現在 4322.4 之中時**不算數**(那正是本次事故的樣態),
    故比對「該數字前後不可緊鄰其他數字」。
    """
    src = re.sub(r"[,，]", "", body + " " + (title or ""))
    # 來源長片本身也大量使用中文數字唸法(「總報酬百分之六百五十六點四」),所以比對前
    # 要把**兩邊**都正規化成同一種表示,否則真數字會被當成編造擋掉(第一版實測誤殺
    # 656.4 與 18.8 這兩個長片明明有的值)。這裡建一個來源數字池:阿拉伯原文 + 中文轉換值。
    _src_pool = set(re.findall(r"\d+(?:\.\d+)?", src))
    try:
        from fact_source_guard import _cn_num_to_float as _c2f
        _src_cn = re.findall(r"百分之([零一二三四五六七八九十百千點]+)", src)
        _src_cn += re.findall(r"([零一二三四五六七八九十百千點]{2,})[倍年萬]", src)
        for _s in _src_cn:
            _v = _c2f(_s)
            if _v is not None:
                _src_pool.add("%g" % _v)
    except Exception:  # noqa: BLE001
        pass
    # 專有名詞黑名單:Shorts 觀眾是被 feed 推來的陌生人,術語=直接滑走
    # (同 LONG_RULES ⓐ 的前 30 秒禁術語)。實測 LLM 生出「多數人以為卡瑪比率 0.24 沒差」
    # ——那個數字連長片都沒有,而且對小白是天書。術語題一律丟。
    _JARGON = ("卡瑪", "夏普", "標準差", "貝塔", "CAGR", "beta", "Sharpe", "索提諾", "波動率")
    kept, dropped = [], []
    for it in items or []:
        text = f"{it.get('title','')} {it.get('angle','')}"
        _j = [w for w in _JARGON if w in text]
        if _j:
            dropped.append((it.get("title", "")[:34], [f"術語:{_j[0]}"]))
            continue
        # 🔴 2026-08-17:只抓阿拉伯數字是不夠的——切片**旁白**一律用中文唸法
        # (「報酬負百分之三十七」),閘門看不到就等於沒閘。實際事故:B41_vS97LO8 憑空
        # 生出「-37%」(疑似把長片的「最大回撤 -38.3%」誤讀成報酬),已對外播出 479 次
        # 才被抓到下架。中文數字轉換直接重用長片產線既有的
        # fact_source_guard._cn_num_to_float(不重刻,那支已驗證過多輪)。
        _text_norm = re.sub(r"[,，]", "", text)
        nums = re.findall(r"\d+(?:\.\d+)?(?=\s*[%％倍年萬元月天])", _text_norm)
        try:
            from fact_source_guard import _cn_num_to_float
            _cns = []
            # ⚠️ 中文的百分比,單位在**數字前面**(「百分之三十七」),不是後面——
            # 第一版照阿拉伯數字的寫法找「數字後接%」,結果一個都沒抓到(實測 3/3 漏放)。
            _cns += re.findall(r"百分之([零一二三四五六七八九十百千點]+)", _text_norm)
            _cns += re.findall(r"([零一二三四五六七八九十百千點]{2,})[倍年萬]", _text_norm)
            for _cn in _cns:
                _v = _cn_num_to_float(_cn)
                if _v is not None:
                    nums.append("%g" % _v)
        except Exception:  # noqa: BLE001
            pass
        bad = []
        for n in nums:
            # 該數字必須在來源出現,且不可只是更長數字的一部分(前後不能緊鄰數字/小數點,
            # 正是 22.4 被誤讀自 4322.4 的事故樣態);或命中來源的中文數字池。
            _hit = re.search(r"(?<![\d.])" + re.escape(n) + r"(?![\d])", src)
            if not _hit and n not in _src_pool:
                bad.append(n)
        if bad:
            dropped.append((it.get("title", "")[:34], bad))
        else:
            kept.append(it)
    for t, b in dropped:
        print(f"[誠信閘] 丟棄切片題(數字溯源不到 {b}):{t}", file=sys.stderr)
    if dropped:
        try:
            log_ops("切片漏斗", f"⛔ 誠信閘丟棄 {len(dropped)} 支切片題(數字查無來源)")
        except Exception:  # noqa: BLE001
            pass
    return kept


def plan(per, title, body):
    """請 LLM 把一份長內容/主題規劃成 per 支 Shorts 的切點＋導流文案。"""
    ev = sc.evidence_block()
    prompt = f"""{sc.PERSONA}
以上是頻道人設(含軟性新定位:照顧怕被割的小白)。你現在是這個頻道的【切片漏斗規劃師】。{GUARD}
{(ev + chr(10)) if ev else ""}
把下面這支『長片/長主題』，裂變成 {per} 支獨立 Shorts，組成一個互相導流的叢集。原則：
- ★★【標題硬規·2026-08-14】每支標題**必須含一個取自下面長片內容的具體數字**
  (報酬率／回撤％／套牢年數／倍數/年化%),而且是**不同的數字**。
  ✅「4322%的代價:套牢過X年」「年化X%但最大回撤X%」
  ❌「什麼樣的高報酬才值得冒險?」「投資X的真實體驗」「X的真相」——泛泛而談、沒數字、
     五支互換也成立的標題,一律不合格。這是實測 CTR 最高的結構(大數字+反轉)。
- ★ {per} 支必須切**不同面向**,以下各挑一個不重複:①最刺眼的報酬數字 ②最痛的回撤/套牢數字
  ③兩種做法的對決(單筆vs定投、抱著vs停利) ④「多數人以為X,數據說Y」的反直覺判決
  ⑤一個具體情境代入(那年進場的人後來怎麼了)。**嚴禁五支都是「高報酬背後有風險」的換句話說**。
- 🔴【不可推翻來源結論·誠信硬規 2026-08-17】你的任務是把長片的結論**切成小塊**,
  不是重新下結論。**嚴禁**產出與長片數據相反的判斷。
  實際事故:長片明明寫「定期定額總報酬提升到 656.4%、最大回撤降到 -38.3%,顯示定期定額
  降低風險」,切片卻生出「定期定額反而虧更多、報酬 -37%」——把**回撤**當成**報酬**、
  還把長片的結論整個反轉,那支片對外播了 479 次才被抓下架。
  ⚠️ 每個數字都必須是長片裡**該指標**的數字:回撤是回撤、報酬是報酬、年化是年化,
  不可張冠李戴;長片說 A 好就不能說 A 差(要反直覺請從長片**自己就有的**反轉點取材)。
- 每支 Short 對齊小白：用「我先幫你試、別自己送死」的口吻,各自能獨立看懂。
- 優先靠向上面【本頻道實證數據】裡已驗證高完播的角度(有的話)，別憑空發想。
- 每支結尾一句『導流文案』:自然引導去看完整長片。
  ⚠️ 要觀眾按鈕時**一律講「訂閱」,絕對禁止「追蹤」**——YouTube 的按鈕上寫的是「訂閱」,
  講「追蹤」是 IG 語彙,觀眾不知道要按哪個鍵(本頻道已為此全面修正過一次,別再犯)。
  不誇大、不喊單、不保證收益。

長片標題：{title}
長片內容/主題：
{body[:4000]}

只輸出 JSON 陣列（不要其他字、不要 markdown 圍欄）：
[{{"title":"這支Short的標題","angle":"切哪個新手雷/誤解＋鉤子","cta":"片尾導流文案一句"}}]"""
    import llm  # 共用路由：主供應商→失敗退回 fallback，換模型只改 env
    # 🔴 2026-08-14:這支每天都被 Groq 免費層 429 打掉(08-13、08-14 連兩天「規劃失敗:
    # groq 429 rate limit」→ 切片漏斗連續產出 0 支)。而它是目前最重要的一條管線:
    # Shorts feed 每天帶進 1,200+ 次**外部**觸及(頻道最大的非訂閱者來源),而贏家切片
    # 是研究實證唯一能把那些觸及轉成訂閱的作法。
    # 它一天只打 1~2 次小呼叫,走付費(OpenRouter)的成本約 $0.0001/次——為了省這個
    # 而讓整條戰略管線每天掛掉,是明顯錯誤的取捨。故此處局部覆寫 LLM_BIG_FOR_SMALL,
    # 讓小呼叫也能用付費供應商;用完還原,不影響其他部門的省錢設定。
    _prev_small = os.environ.get("LLM_BIG_FOR_SMALL")
    os.environ["LLM_BIG_FOR_SMALL"] = "1"
    try:
        txt = llm.complete(prompt, 1800, json_mode=True)
    finally:
        if _prev_small is None:
            os.environ.pop("LLM_BIG_FOR_SMALL", None)
        else:
            os.environ["LLM_BIG_FOR_SMALL"] = _prev_small
    m = re.search(r"\[.*\]", txt, re.S)
    if m:
        try:
            return _drop_untraceable(json.loads(m.group(0)), body, title)
        except Exception:
            pass
    items = []
    for om in re.finditer(r"\{[^{}]*\}", txt, re.S):
        try:
            items.append(json.loads(om.group(0)))
        except Exception:
            continue
    return items


def _write_sop(slug, title, shorts):
    REPORTS.mkdir(parents=True, exist_ok=True)
    L = [f"# ✂️ 切片漏斗 SOP｜{title}", "",
         f"> 來源：`{slug}`　規劃 {len(shorts)} 支引流 Shorts（同主題叢集，互相拉抬權重 → 導去長片/主頻道）",
         f"> 產生日：{tw_today()}　誠信鐵則：導流文案不誇大、不喊單、不保證收益", ""]
    for i, s in enumerate(shorts, 1):
        L += [f"## Short {i}：{s.get('title','')}",
              f"- **切點/鉤子**：{s.get('angle','')}",
              f"- **片尾導流文案**：{s.get('cta','')}", ""]
    (REPORTS / f"{tw_today()}_切片漏斗_{slug[:24]}.md").write_text("\n".join(L), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=2, help="本輪最多處理幾支長片/長主題")
    ap.add_argument("--per", type=int, default=4, help="每支長片裂變成幾支 Shorts")
    ap.add_argument("--dry", action="store_true", help="只規劃、印出，不寫題庫/SOP")
    args = ap.parse_args()
    if not sc.has_llm_key():
        print("[FATAL] 無任何 LLM 供應商 API key", file=sys.stderr); return 2

    seen = _load_seen()
    jobs = []  # [(slug, title, body, is_real_long)]
    for slug, title, body in _long_scripts(seen)[:args.max]:
        jobs.append((slug, title, body, True))
    # 沒有新長片就退而用題庫的 long 題目當叢集主題
    if not jobs:
        for _ in range(args.max):
            seed = _pull_long_topic(consume=not args.dry)
            if not seed:
                break
            sid, st, sa = seed
            jobs.append((f"topic_{sid}", st, f"主題：{st}\n切入點：{sa}", False))
            if args.dry:
                break  # dry 不消耗題庫，同題只取一支當樣本，避免重複

    if not jobs:
        print("[切片漏斗] 無新長片、題庫也無未用 long 題目，本輪略過。")
        log_ops("切片漏斗", "無長片/長題可切，略過")
        return 0

    from topic_bank import add_topics
    total_short, total_long = 0, 0
    for slug, title, body, is_real in jobs:
        try:
            shorts = plan(args.per, title, body)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] 規劃失敗 {slug}：{exc}", file=sys.stderr); continue
        shorts = [s for s in shorts if (s.get("title") or "").strip()][:args.per]
        if not shorts:
            continue
        if args.dry:
            print(f"\n=== {title} → {len(shorts)} 支 Shorts ===")
            for s in shorts:
                print(f"  ✂️ {s.get('title','')}｜導流：{s.get('cta','')[:40]}")
            continue
        items = [{"title": s["title"],
                  # 把導流文案併進 angle，produce_batch 寫腳本時會帶到片尾
                  "angle": (s.get("angle", "") + "｜片尾導流：" + s.get("cta", "")).strip("｜"),
                  "category": "市場觀念", "format": "short",
                  "parent": slug} for s in shorts]
        # 🔴 2026-08-15 front=True:題庫裡積了 111 支未用切片題,而產線每天只產 1 支 Shorts
        # → 新題排在隊尾要等 100 天以上才輪得到。而本工具現在**只從已發布的贏家長片**切
        # (2026-08-12 起依觀看數排序),這批題正是我們現在最想測的東西(Shorts feed 每天
        # 1,200+ 次外部觸及是頻道最大的非訂閱者來源,而贏家切片是研究實證唯一能轉化它的作法)。
        # pull_topic 的 sort 是穩定排序,同 rank 保留題庫順序 → front=True 讓新切片題
        # 在同層內排最前面。量很小(每次 2~5 支),不會淹掉旗艦/體檢那兩個更高的優先層。
        n = add_topics(items, source="funnel", front=True)
        total_short += n
        total_long += 1
        _write_sop(slug, title, shorts)
        if is_real:
            seen.add(slug)
        print(f"[ok] {title[:30]} → 規劃 {n} 支引流 Shorts 進題庫")
    if not args.dry:
        _save_seen(seen)
        log_ops("切片漏斗", f"{total_long} 支長片/長題 → 裂變 {total_short} 支引流 Shorts 進題庫")
        print(f"\n[ok] 切片漏斗：{total_long} 個主題裂變成 {total_short} 支引流 Shorts，已進題庫＋SOP 報告。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
