#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ep0_engine.py — 【系列開播預告 EP.0】確定性產製引擎。

為什麼有這支(2026-07-17 Analytics 90d 實測):
  全頻道訂閱轉換的贏家不是任何 Shorts，而是**系列開播預告**：
    · ijCNjwEDRnc「實測企劃 EP.0 規則先講死」 300 觀看 → 9 訂閱 = 3.00%(佔全頻道訂閱 25%)
    · Zm5zLEAs30Y「TradingView 全攻略開播」     80 觀看 → 4 訂閱 = 5.00%
    · 對照(n 小,只當方向參考勿當定論):Shorts 平均約 0.080%、長片 0.43–0.96%
  最高轉換那支完播率只有 25.88% → **EP.0 的 KPI 是訂閱，不是完播**。
  那兩支都是手寫的，產線零機制在產。本檔把它變成可重複的產線能力。

★骨架(7 拍，蒸餾自上述兩支已驗證範本，不是憑空設計)：
  ①敵人 ②反轉/宣告(這是第零集) ③身分憑證 ④規則先講死 ⑤規模承諾 ⑥為什麼你該追 ⑦CTA明講訂閱+首集鉤
  轉換機制:訂閱理由＝「未來還有一整個系列」而非「這支好看」→ 觀眾不必看完就會訂(故完播與轉換脫鉤)。
  ④「規則先講死」是把**誠信當轉換武器**:主動自我設限(不保證收益/賠的不剪/不作弊)＝「我值得你訂」的證據。

★為什麼確定性模板、不走 LLM：
  1. 骨架已由實證定死，LLM 只會偏離
  2. produce_batch.HOOK_RULES 全是「完播率＝唯一KPI」「前 3 秒丟精確數字」——與 EP.0 的訂閱 KPI
     直接衝突，還會逼 LLM 生數字 → 誠信風險
  3. 結構上不含**自稱**績效數字(範本裡的 812% 是引用敵人的神話，不是自稱)→ 天生過 fact_guard
  4. 零 LLM 成本

★誠信 fail-closed(頻道生死線)：
  EP.0 承諾「接下來要做什麼」必須是產線**真的做得到**的。inventory() 讀真檔算存量，
  低於 MIN_STOCK 直接拒產(回 None)；承諾句的數字由存量**算出來**，不寫死 → 結構上不可能開空頭支票。

★集數連續性(memory 記載過 EP 編號大亂事故)：
  build_topic() 刻意**不設** _is_ep / _is_tw_lab 旗標 —— produce_batch 的 _bump_ep/_bump_tw_lab
  只在那兩個旗標為真時遞增集數。EP.0 是預告不是正片，不可吃掉一集編號。
  (produce_batch.py:3050 註解本來就寫「EP 正片(非預告)產出成功 → 遞增」。)

用法：
  python scripts/ep0_engine.py --list                    # 列各系列 EP.0 狀態與題庫存量
  python scripts/ep0_engine.py --dry tw_lab              # 只印稿，不寫檔(驗證用)
  python scripts/ep0_engine.py --out <dir> tw_lab        # 寫 .md/.voice.txt 到指定目錄(不碰 output/)
  python -m produce_batch --ep0 tw_lab                   # 走正式產線(配音+渲染)

驗證：python -m py_compile scripts/ep0_engine.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

STUDIO = ROOT / "STUDIO"

# 存量下限:低於這個數就不准產 EP.0(承諾會變空頭支票)。
# 定在 8 是因為 EP.0 的承諾語氣是「一整組已經排好」，個位數撐不起這句話。
MIN_STOCK = 8


def _load(path: Path):
    """讀 JSON，讀不到/壞檔回 None(絕不丟例外中斷產線)。"""
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


# ─────────────────────────────────────────────────────────────────────
# 存量查證(誠信命脈:承諾的數字全部從這裡算出來)
# ─────────────────────────────────────────────────────────────────────

def _inv_tw_lab():
    """台股真相實驗室:數未用的真回測事實 key。
    事實來源 STUDIO/tw_stock_facts.json + tw_facts_computed.json(tw_lab_engine 同源)，
    已用的記在 tw_lab_state.json:used_keys。ready = 還沒拍過的真事實組數 = 還能產幾集。"""
    keys = set()
    for name in ("tw_stock_facts.json", "tw_facts_computed.json"):
        d = _load(STUDIO / name) or {}
        r = d.get("results")
        if isinstance(r, dict):
            keys |= set(r.keys())
        elif isinstance(r, list):
            for it in r:
                if isinstance(it, dict) and it.get("key"):
                    keys.add(str(it["key"]))
    st = _load(STUDIO / "tw_lab_state.json") or {}
    used = set(st.get("used_keys") or [])
    unused = keys - used
    return {
        "ready": len(unused),      # 事實已算完、還沒拍 → 立刻可產的集數
        "planned": len(unused),    # 本系列 ready 即 planned(事實已在庫，不需再算)
        "done": len(used & keys),
        "detail": (f"事實總 key {len(keys)}、已用 {len(used & keys)}、未用 {len(unused)}"
                   f"(tw_stock_facts.json + tw_facts_computed.json)"),
    }


def _inv_checkup():
    """個股體檢:backlog 是全台股清單(n_total)，每日 cron 05:50 撈下一檔算事實。
    ready = 事實已算好的檔數(stock_checkup_facts.json:by_code)，planned = backlog 還沒做的檔數。
    ⚠️ 兩者差很大是**正常**的(一天一檔)，所以承諾要分開講:
       「已經體檢完 N 檔」用 ready，「清單上有 M 檔」用 planned —— 不可拿 planned 冒充已完成。"""
    bl = _load(STUDIO / "stock_checkup_backlog.json") or {}
    items = bl.get("items") or []
    todo = [i for i in items if isinstance(i, dict) and not i.get("done")]
    fc = _load(STUDIO / "stock_checkup_facts.json") or {}
    by = fc.get("by_code") or {}
    return {
        "ready": len(by),          # 事實已算完的檔數(可誠實說「已經體檢完」)
        "planned": len(todo),      # backlog 還沒做的檔數(可誠實說「清單上還有」)
        "done": len(items) - len(todo),
        "detail": (f"backlog n_total {bl.get('n_total')}、已做 {len(items) - len(todo)}、"
                   f"未做 {len(todo)}；facts by_code 已算好 {len(by)} 檔"),
    }


# ─────────────────────────────────────────────────────────────────────
# 系列註冊表
# ─────────────────────────────────────────────────────────────────────
# 每個系列填 7 拍的素材。promise() 吃 inventory() 的真實存量算承諾句 → 不可能寫空頭支票。
# 文案語氣照兩支已驗證範本(短句、口語、敵我對立、規則條列、CTA 明講「訂閱」)。

SERIES = {
    "tw_lab": {
        "name": "台股真相實驗室",
        "inv": _inv_tw_lab,
        "min_stock": MIN_STOCK,
        "title": "台股真相實驗室開播｜你聽過的存股常識，我一條一條拿回測驗給你看｜EP.0 規則先講死",
        # ①敵人
        "enemy": ("台股的存股常識，幾乎都是這樣傳的:「長期一定賺」「跌了就加碼」「停利落袋為安」。"
                  "講的人很有信心，但你問他數據呢？沒有。就是「大家都這麼說」。"),
        # ②反轉/宣告
        "turn": ("所以我決定開一個新系列:台股真相實驗室。這支是第零集，我要先把規則講清楚。"),
        # ③身分憑證
        "cred": ("這裡是量化阿森，這個頻道只做一件事:把每一個講法拿去回測，用數據說話，不喊單、也不報明牌。"),
        # ④規則先講死(誠信＝轉換武器)
        "rules": [
            "第一，每一集只驗一個講法，一次講一件事，不混在一起讓你看不出破綻。",
            "第二，用的是真實歷史行情跑出來的回測，手續費、稅、滑價都算進去，不挑對我有利的區間。",
            "第三，結果如實公開。驗出來是對的我就說對，打臉我自己的我也照播，不剪掉。",
            "第四，我不報明牌、不喊進出、不保證任何收益——我只負責把數據攤開，怎麼用是你的決定。",
        ],
        # ⑥為什麼你該追
        "why": ("為什麼要做這個？因為我自己也受夠了那種「聽起來很有道理，但沒有人真的去驗」的說法。"
                "如果一個常識，只有在嘴上講的時候才成立，那它根本不值得你拿錢去試。"
                "我想做的，是那種你看完之後，真的有能力自己判斷「這套說法到底能不能信」的內容。"),
        # ⑦首集鉤
        "first_ep": "第一集,我要驗的是台股最多人信、也最少人查的那一條。",
        "category": "台股真相實驗室",
        "hashtags": ["#台股", "#存股", "#0050", "#回測", "#ETF", "#定期定額", "#台股真相實驗室", "#量化阿森"],
        "broll": ["taiwan stock exchange", "stock market chart", "backtest equity curve", "data chart"],
    },
    "checkup": {
        "name": "個股體檢系列",
        "inv": _inv_checkup,
        "min_stock": MIN_STOCK,
        "title": "個股體檢系列開播｜台股一檔一集，我用同一把尺量完整個市場｜EP.0 規則先講死",
        "enemy": ("你有沒有發現，網路上講個股的影片，幾乎都在講同樣那幾檔？"
                  "剩下一千多檔，沒人講。不是因為它們不重要，是因為講它們沒有流量。"
                  "而那些有人講的，翻來覆去也只有一句「這檔會漲」——問他為什麼，就沒有下文了。"),
        "turn": ("所以我決定做一件很笨、但沒人做的事:台股一檔一集，我用同一把尺，量完整個市場。"
                 "這支是第零集，我要先把規則講清楚。"),
        "cred": ("這裡是量化阿森，這個頻道只做一件事:把每一檔股票的事實攤開，用數據說話，不喊單、也不報明牌。"),
        "rules": [
            "第一，每一檔都用**同一組**體檢項目:營收、獲利、配息、股價走勢、還有它在崩盤時到底跌成什麼樣。同一把尺，不換標準。",
            "第二，數字全部來自公開財報與歷史行情，我只做整理跟計算，不加我自己的預測。",
            "第三，好的壞的都講。體檢出來難看的，我照播，不會為了怕得罪誰就跳過。",
            "第四，這是**介紹，不是推薦**。我不會跟你說任何一檔該買還是該賣，也不保證任何收益——體檢報告給你，判斷是你的事。",
        ],
        "why": ("為什麼要這樣做？因為「沒人講」不等於「不用查」。"
                "你手上那檔冷門股，可能整個 YouTube 都找不到一支認真講它的影片。"
                "我想做的，就是那個你想查任何一檔台股，都查得到一份誠實體檢報告的地方。"),
        "first_ep": "第一集,從市場上最多人抱、卻最少人真的查過它體質的那一檔開始。",
        "category": "個股體檢",
        "hashtags": ["#台股", "#個股分析", "#財報", "#基本面", "#存股", "#個股體檢", "#量化阿森"],
        "broll": ["taiwan stock exchange", "financial report", "stock market chart", "data analytics dashboard"],
    },
}


def _promise(key: str, inv: dict) -> str:
    """⑤規模承諾:數字**全部**來自 inventory() 的真實存量。
    這是誠信命脈——承諾的每個數字都可回查 STUDIO 的真檔，結構上不可能編造。"""
    if key == "tw_lab":
        # ready = 未用的真回測事實組數，一組一集 → 「已經跑完 N 組、排好 N 集」是可查證的事實
        return (f"這不是講講而已。我手上已經跑完 {inv['ready']} 組台股回測，一組一集，全部排好了。"
                f"從第一集開始，一集拆一個講法，一路拆下去。")
    if key == "checkup":
        # ⚠️ ready(已算完) 與 planned(清單待做) 分開講，不可混為一談
        return (f"這不是講講而已。台股 {inv['planned'] + inv['done']} 檔，我已經全部排進清單，"
                f"目前體檢完 {inv['ready']} 檔，每天再往下做一檔，做到整個市場都量完為止。")
    return ""


def inventory(key: str) -> dict | None:
    """回本系列的真實題庫存量;系列不存在回 None。"""
    s = SERIES.get(key)
    if not s:
        return None
    try:
        return s["inv"]()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] {key} 存量查證失敗:{str(exc)[:80]}", file=sys.stderr)
        return None


def build_script(key: str) -> dict | None:
    """組確定性的 EP.0 稿。回可直接當 produce_batch script_override 的 d dict。
    存量不足 → 回 None(fail-closed，寧可不產也不開空頭支票)。"""
    s = SERIES.get(key)
    if not s:
        print(f"[FATAL] 未知系列:{key}(可用:{', '.join(SERIES)})", file=sys.stderr)
        return None
    inv = inventory(key)
    if not inv:
        print(f"[FATAL] {s['name']}:存量查不到，拒產 EP.0。", file=sys.stderr)
        return None
    stock = max(int(inv.get("ready", 0)), int(inv.get("planned", 0)))
    if stock < s["min_stock"]:
        print(f"[FATAL] {s['name']}:題庫存量 {stock} < 下限 {s['min_stock']}，"
              f"拒產 EP.0(承諾會變空頭支票)。{inv['detail']}", file=sys.stderr)
        return None

    rules_txt = "\n\n".join(s["rules"])
    # ⑦CTA:字面必須有「訂閱」二字(兩支範本共同點;produce_batch._ensure_sub_hook 也吃這個)
    cta = (f"{s['first_ep']}如果你也想知道，這些說法攤在數據前面到底剩下什麼，"
           f"那就先按個訂閱，跟著這個系列一起看下去。我們下支見。")

    voice = "\n\n".join([
        s["enemy"],                 # ①敵人
        s["turn"],                  # ②反轉/宣告
        s["cred"],                  # ③身分憑證
        "先把規則訂死。",             # ④規則先講死
        rules_txt,
        _promise(key, inv),         # ⑤規模承諾(存量算出來的)
        s["why"],                   # ⑥為什麼你該追
        cta,                        # ⑦CTA
    ])
    # 去掉 markdown 粗體記號(rules 裡的 ** 是給人看的，配音不能唸出來)
    voice = voice.replace("**", "")

    segments = [
        {"heading": "他們都這樣講", "broll": ["social media scam", "youtube editing timeline"]},
        {"heading": "所以我開一個新系列", "broll": s["broll"][:2]},
        {"heading": "這個頻道只做一件事", "broll": ["data analytics dashboard", "financial graph animation"]},
        {"heading": "規則先講死", "broll": ["checklist", "rules document"]},
        {"heading": "存量攤給你看", "broll": s["broll"][1:3] or ["data chart"]},
        {"heading": "為什麼要這樣做", "broll": ["warning sign", "stock market chart"]},
        {"heading": "訂閱，跟著看下去", "broll": ["subscribe button"] + s["broll"][:1]},
    ]

    desc = "\n\n".join([
        s["enemy"] + s["turn"],
        "規則:" + " ".join(f"{'①②③④'[i]} {r.split('，', 1)[-1] if '，' in r else r}"
                           for i, r in enumerate(s["rules"][:4])).replace("**", ""),
        _promise(key, inv),
        f"這個頻道「量化阿森｜Carson Quant」只做一件事:把每一個說法拆給你看，用數據說話。"
        f"這是「{s['name']}」的開播預告，接下來正式連載，訂閱不錯過。",
        "⚠️ 風險聲明:本影片為資訊與觀念分享，不構成任何投資建議。過去績效不代表未來表現，投資請自行承擔決策後果。",
    ])

    return {
        "title": s["title"],
        "voice_text": voice,
        "segments": segments,
        "description": desc,
        "hashtags": s["hashtags"],
        # ⚠️ 刻意不設 _is_ep / _is_tw_lab:EP.0 是預告不是正片，設了會被 _bump_ep/_bump_tw_lab
        #    吃掉一集編號(見檔頭「集數連續性」)。
        "_is_ep0": True,
        "_ep0_series": key,
        "_ep0_inventory": inv,      # 供稽核:這支承諾的數字是用哪組存量算的
    }


def build_topic(key: str) -> dict | None:
    """回 produce_batch topic_override(讓 gate 知道這是指定題、別重生換題)。"""
    s = SERIES.get(key)
    if not s:
        return None
    return {
        "title": s["title"],
        "angle": f"{s['name']} 系列開播預告 EP.0:規則先講死。KPI 是訂閱不是完播。",
        "category": s["category"],
        "format": "long",
        "ep0_series": key,
    }


def _fmt_status(key: str) -> str:
    s = SERIES[key]
    inv = inventory(key)
    if not inv:
        return f"  {key:10} {s['name']:12} 存量查不到"
    stock = max(int(inv.get("ready", 0)), int(inv.get("planned", 0)))
    ok = "可產" if stock >= s["min_stock"] else f"存量不足(<{s['min_stock']})"
    return f"  {key:10} {s['name']:12} ready={inv['ready']:<6} planned={inv['planned']:<6} {ok}\n" \
           f"             └ {inv['detail']}"


def main() -> int:
    ap = argparse.ArgumentParser(description="系列開播預告 EP.0 確定性產製引擎")
    ap.add_argument("series", nargs="?", help=f"系列代號({', '.join(SERIES)})")
    ap.add_argument("--list", action="store_true", help="列各系列 EP.0 狀態與題庫存量")
    ap.add_argument("--dry", action="store_true", help="只印稿，不寫檔")
    ap.add_argument("--out", default=None, help="寫 .md/.voice.txt 到指定目錄(驗證用，不碰 output/)")
    args = ap.parse_args()

    if args.list or not args.series:
        print("系列 EP.0 狀態(存量讀 STUDIO 真檔):")
        for k in SERIES:
            print(_fmt_status(k))
        if not args.series:
            print("\n用法:ep0_engine.py --dry <series> | --out <dir> <series>")
        return 0

    d = build_script(args.series)
    if not d:
        return 2

    if args.dry or not args.out:
        print(f"=== {d['title']} ===\n")
        print(d["voice_text"])
        print(f"\n--- 字數:{len(d['voice_text'])} ---")
        print(f"--- 存量佐證:{d['_ep0_inventory']['detail']} ---")
        return 0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT / "scripts"))
    import produce_batch as pb
    slug = pb.slugify(d["title"], "L")
    (out / f"{slug}.voice.txt").write_text(d["voice_text"], encoding="utf-8")
    (out / f"{slug}.md").write_text(pb.build_md(d), encoding="utf-8")
    print(f"[ok] 已寫:{out / (slug + '.md')}")
    print(f"[ok] 已寫:{out / (slug + '.voice.txt')}")
    print(f"[存量佐證] {d['_ep0_inventory']['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
