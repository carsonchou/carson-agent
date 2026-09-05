#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""發布前 fail-closed 閘門:旁白講的財務數字,對應得到**這一檔**的哪一條 fact?

## 為什麼要有這支(2026-09-06 事故)

已發布影片被人工逐字讀出捏造:聯詠 3034 旁白講「近四季 EPS 13.61 / 12.38 / 10.23 / 9.92 元」,
而事實庫裡**根本沒有** `checkup_eps_trend__3034`。同型共 6 支已下架(設 private)。

根因三層都在 2026-09-06 修了(FinMind 斷料偵測 e760d0ae、`_checkup_context` 餵 skipped
並明令不准提、模板規則②的「沒有就說沒有」出口擴到四項 ecb799ab)——
**但那三層都是「讓它不要編」,沒有一層是「編了就擋下來」。** 這支是後者。

## 判準(督導 2026-09-06 定,不是我挑的)

**「這個數字對應得到這檔股票的哪一條 fact」——不是「這個數字在全域池裡出現過」。**

舊的 `fact_source_guard` 比對的是**全域**事實池(38,231 個數字)。504 檔 × 13 類把 0~200 的
百分比區間填成實質連續(相鄰間距中位 0.0032,而容差 ≥0.25 = 間距的 78 倍)⇒
隨機 400 個百分比通過率 **100%**。它為任何合理數字背書,結構上擋不住本事故。
詳見 memory `yt-fact-guard-pool-saturation` 與 `audit_per_stock_facts.py` 的 docstring。

## 這支擋的失敗形態(寫在前面,因為閘門可以「執行完全正確但問錯問題」)

> 旁白給出某類財務事實的**具體數字**,而該 code 在 `stock_checkup_facts.json`
> **沒有那一類 fact**(它在 `by_code[code]["skipped"]` 裡,或根本不存在)⇒ 數字是填出來的。

這是事故的第一軸,也是規模最大的一軸。

## 🔴 它擋不住什麼(必讀,不要拿它當全稱保證)

1. **第二軸:fact 存在但數值/期間被改。** 例:矽格 6257 真值 6.21 元、旁白講 6.04 元。
   本閘門在該類 fact **存在**時完全不看數字內容,所以這類一律放行。
   獨立驗證員實測規模 ≈ 1~3/124,遠小於第一軸,但**不是零**。
2. **敘事錯亂。** 例:1519 華城「投入一筆資金在臺塑(0050)」(台塑≠0050)、
   1504 東元引用 2018/2006(在事實涵蓋 2022–2025 之外)。那不是數字捏造,是講錯東西。
3. **非財務類的捏造**(產業描述、公司在做什麼、市佔率)。
4. **事實庫本身是錯的**——閘門只保證「旁白對得上事實庫」,不保證事實庫對得上世界。
5. **豁免句型裡的捏造**:強豁免(假設/舉例/明說沒資料)整句不看;弱豁免(條件句/比喻)
   在同子句沒有指名年份時放行。有人在「假設…」句裡塞真宣稱就會漏(已知洞,見 `_exempt`)。
6. **只看得到已落檔的旁白**(`.voice.txt` / `.md`)。片子若不是從這條產線出來的,它什麼都不知道。

## fail-closed 的邊界(哪些情況「不確定就擋」)

| 情況 | 處置 |
|---|---|
| 認得出 code、掃到命中 | **擋** |
| slug 帶「個股體檢」標記 **且** 含 universe 真代號,但認不出是哪一檔 | **擋**(無法查證) |
| 其餘認不出 code 的(系列彙總片 / ETF / 大盤片) | 放行(本閘門不適用) |
| 找不到旁白檔 | **擋**(無法查證) |
| 事實庫讀不到 / 模組壞掉 / 自檢失敗 | **擋**(閘門壞掉時不可以靜默放行) |

倒數第一列是刻意的:`daily_publish._factguard_gate` 現行行為是 import 失敗就整批放行
(`daily_publish.py:578`),那是 fail-open。本閘門不沿用那個形狀。

## 自檢(陽性 + 陰性對照,每次 check() 都跑)

memory `verification-that-cannot-fail`:「知道這個坑不構成免疫,救回它的是陽性對照」。
`self_check()` 的 fixture **寫死在程式碼裡、不讀磁碟**(事實庫變動弄不壞它),
其中兩則是**真實旁白原句**:台玻 1802(必須抓到)、川湖 2059(必須放過)。
任一失敗 ⇒ 閘門視為壞掉 ⇒ 擋。

## 實測(2026-09-06,寫完當下的語料)

| 母體 | 適用 | 擋下 | 內容 |
|---|---|---|---|
| 已發布長片 | 184 | 10(5.4%) | **6 支已確認捏造下架片 6/6 全中**、5 支「疑似」中 4 支;
「誤判·不動」名單四支(文曄3036/禾伸堂3026/英業達2356/川湖2059)**0 支誤擋** |
| 未發布長片 | 51 | 2(3.9%) | 正好是上一棒人工凍結的 6907 雅特力、4585 達明 |

⚠️ 這是**建構時的樣本**,不是獨立驗證:判準是照著這批語料調出來的,
所以它在這批上的成績天然偏高。真正的考驗是明天以後的新片。

用法:
    python scripts/per_stock_fact_gate.py --selftest        # 只跑自檢
    python scripts/per_stock_fact_gate.py --scan            # 掃未發布片(不擋人,看會擋掉誰)
    python scripts/per_stock_fact_gate.py --scan --published
    python scripts/per_stock_fact_gate.py --slug <slug>     # 單支
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
OUTPUT = ROOT / "output"
GATE_LOG = STUDIO / "fabrication_gate_log.jsonl"


class FabricationBlocked(Exception):
    """旁白出現對不上該檔事實的財務數字 ⇒ 不上傳。呼叫端已是 per-slug except,不會影響其他片。"""


# ── 類別 → (旁白關鍵字, 該類數字必須帶的單位) ─────────────────────────────
# 只列**基本面數字**類別:那是 LLM 在斷料期間會去填的洞。
# 走勢類(long_horizon/underwater/halvings)也放進來,因為它們同樣是「沒有就會被編」的類別。
CATEGORY_RULES = {
    "checkup_revenue_trend":      (("營收", "營業收入"), ("億", "萬元", "%", "百分之", "成")),
    "checkup_eps_trend":          (("EPS", "每股盈餘", "每股純益", "每股虧損"), ("元",)),
    "checkup_gross_margin":       (("毛利率",), ("%", "百分之")),
    "checkup_dividend_history":   (("殖利率", "配息", "股利"), ("元", "%", "百分之", "年")),
    "checkup_valuation_position": (("本益比",), ("倍", "百分位")),
    "checkup_long_horizon":       (("總報酬", "年化報酬"), ("%", "百分之", "倍")),
    "checkup_underwater":         (("套牢",), ("年", "天")),
    "checkup_halvings":           (("腰斬",), ("次", "%", "百分之")),
}

# 豁免句型。每一組都對應一個**真實發生過的偽陽性**(2026-09-06 稽核的四種誤判來源)。
_HYPO = ("假設", "如果", "假如", "舉例", "例如", "想像", "試想", "打個比方", "比方說",
         "一旦", "倘若")
# 🔴「當」「若」單字必須**錨定在句首或標點後**,不可以用子字串比對:
#    自檢第一次就是被「相**當**亮眼」整句豁免掉(2026-09-06,寫閘門的當下踩)。
#    同族陷阱:當然/當時/當作/相當/若干。錨定後仍涵蓋川湖 2059
#    「當資料中心擴建潮來臨,營收年增能衝到 40% 以上」。
_HYPO_ANCHORED = re.compile(r"(?:^|[,，、;;::])\s*(?:當|若)")
_METAPHOR = ("好比", "如同", "比喻", "彷彿", "猶如", "比作", "當成")
# 「像」當動詞才是比喻(本益比**像**體溫計 / 就像 / 像是 / 好像);
# 影像/圖像/錄像是名詞,不豁免。← 禾伸堂 3026 / 英業達 2356 那兩支的實際句型
_METAPHOR_RE = re.compile(r"(?<![影圖錄])像")
_NODATA = ("沒有", "查無", "缺乏", "不足", "未提供", "無法取得", "略過", "不完整")
_NODATA_OBJ = ("資料", "數據", "事實", "紀錄")             # ← 文曄 3036「我們沒有…資料」= 正確行為

_CN = "[零一二三四五六七八九十百千萬億兩點]"
_NUMPAT = re.compile(r"(\d[\d,]*(?:\.\d+)?)|(" + _CN + r"{1,16})")


_YEAR_RE = re.compile(r"(?:19|20)\d{2}\s*年")


def _exempt(sent: str) -> str:
    """回傳豁免原因(空字串=不豁免)。⚠️ 每一條豁免都是一個已知的洞。

    🔴 豁免分**強弱兩級**,而分級的理由是一個實際漏抓(2026-09-06):
    台玻 1802 那句捏造是
        「…**當**原物料價格暴漲時,毛利率會**像**溜滑梯一樣崩跌——
          **2022年財報就顯示其毛利率從30%跳水到剩12%**…」
    條件子句、比喻、事實斷言**擠在同一個句子裡**(逗號不切句),整句被豁免吃掉。
    而它正是已下架六支之一 —— 也就是說,只有弱豁免時的整句豁免會放走真事故。

    - **強豁免**(假設/舉例/明說沒資料):講話的人明確表示這不是宣稱 ⇒ 無條件豁免。
    - **弱豁免**(錨定的當/若、比喻):只在句中**沒有具體年份**時才豁免。
      帶「2022年」這種具體年份的子句是事實斷言,不是假設 ——
      條件句的殼包不住一個指名年份的數字。

    驗證:四個已知偽陽性(文曄3036/川湖2059/禾伸堂3026/英業達2356)都沒有具體年份,
    分級後仍全部豁免;台玻 1802 有 2022 年 ⇒ 改為命中。兩邊都在 self_check() 裡鎖住。"""
    if any(h in sent for h in _HYPO):
        return "假設/舉例句(強豁免)"
    if any(n in sent for n in _NODATA) and any(o in sent for o in _NODATA_OBJ):
        return "明說沒有資料(強豁免)"
    return ""


def _weak_exempt(sent: str) -> str:
    """弱豁免原因(空字串=不豁免)。**由呼叫端決定它管不管得到某個數字** —— 見 _clause_of。"""
    if _HYPO_ANCHORED.search(sent):
        return "條件句(弱豁免)"
    if any(m in sent for m in _METAPHOR) or _METAPHOR_RE.search(sent):
        return "比喻句(弱豁免)"
    return ""


_CLAUSE_SPLIT = re.compile(r"[,，、;；:：()（）\[\]「」【】——–—/]")


def _clause_of(sent: str, pos: int) -> str:
    """取 pos 這個位置所在的**子句**(以逗號/括號/破折號切)。

    🔴 為什麼要切到子句:年份必須跟那個數字**在同一個子句**才算事實斷言。
    川湖 2059 實例(它在誤判名單上,整句層級的年份規則會把它變成偽陽性):
        「當全球資料中心擴建潮來臨(**像 2025 年** AI 爆發),川湖的訂單會像洪水般湧入,
          **營收年增能衝到 40% 以上**,這時市場會給它超高本益比」
    年份在括號裡的舉例,而數字在條件子句裡 —— 兩者不同子句 ⇒ 弱豁免仍然成立。
    對照台玻 1802:數字和「2022年財報就顯示」在同一子句 ⇒ 弱豁免管不到。"""
    left = 0
    right = len(sent)
    for m in _CLAUSE_SPLIT.finditer(sent):
        if m.end() <= pos:
            left = m.end()
        elif m.start() > pos:
            right = m.start()
            break
    return sent[left:right]


def _cn_to_float(raw: str):
    """中文數字轉浮點。用 fact_source_guard 的實作;它吃不下的回 None。
    ⚠️ 回 None 不等於安全 —— 見 scan() 裡 unparsed 的處理。"""
    try:
        from fact_source_guard import _cn_num_to_float
        return _cn_num_to_float(raw)
    except Exception:  # noqa: BLE001
        return None


def own_numbers(code: str, results: dict) -> set:
    """這一檔**自己**所有 fact 裡出現過的數字(白名單)。
    刻意不收其他個股的數字 —— 那正是全域池的病根。"""
    s = set()
    for k, v in results.items():
        if not (k.endswith("__" + code) or f"__{code}__" in k):
            continue
        blob = f"{v.get('claim', '')} {v.get('summary', '')}"
        for m in re.finditer(r"-?\d[\d,]*(?:\.\d+)?", blob):
            try:
                fv = abs(float(m.group(0).replace(",", "")))
            except ValueError:
                continue
            s.add(round(fv, 2))
            if 0 < fv <= 100:                 # 百分位補數:「第62百分位」→「38%的時間比現在高」
                s.add(round(100 - fv, 2))
    return s


def have_categories(code: str, results: dict) -> set:
    """該檔**實際有**的 fact 類別。"""
    out = set()
    for k in results:
        if k.endswith("__" + code):
            out.add(k[: -(len(code) + 2)])
        elif f"__{code}__" in k:
            out.add(k.split(f"__{code}__")[0])
    return out


def scan(text: str, code: str, results: dict, strict_unparsed: bool = True) -> list:
    """核心判定。回傳命中清單 [{cat, raw, sent, why}]。

    命中條件(三個都要成立):
      ① 句子提到某類別的關鍵字,而該檔**沒有**那類 fact
      ② 句子裡有帶對單位的具體數字
      ③ 那個數字**不在**該檔自己的事實數字白名單裡
    """
    have = have_categories(code, results)
    white = own_numbers(code, results)
    hits = []
    for sent in re.split(r"[。！？!?\n]", text):
        sent = sent.strip()
        if not sent:
            continue
        if _exempt(sent):            # 強豁免:整句不看
            continue
        weak = _weak_exempt(sent)
        for cat, (kws, units) in CATEGORY_RULES.items():
            if cat in have or not any(k in sent for k in kws):
                continue
            for m in _NUMPAT.finditer(sent):
                raw = m.group(0)
                tail = sent[m.end():m.end() + 3]
                if not any(u in tail or u in raw for u in units):
                    continue
                # 弱豁免只在「這個數字所在的子句沒有指名年份」時放行
                if weak and not _YEAR_RE.search(_clause_of(sent, m.start())):
                    continue
                if m.group(1):
                    try:
                        val = float(m.group(1).replace(",", ""))
                    except ValueError:
                        val = None
                    unparsed = val is None
                else:
                    val = _cn_to_float(raw)
                    unparsed = val is None
                if unparsed:
                    # 轉不出來 = 查不了白名單。類別本來就缺,又冒出一個查不了的數字 ⇒ 當命中。
                    # (2026-09-06 已知偽陽性來源之一:「四千五百四十二點二」轉換器吃不下)
                    if strict_unparsed and len(raw) >= 2:
                        hits.append({"cat": cat.replace("checkup_", ""), "raw": raw,
                                     "sent": sent[:110], "why": "數字無法解析,無法比對白名單"})
                        break
                    continue
                if val == 0:
                    continue
                if round(abs(val), 2) in white:      # 是這檔自己別條事實的數字 → 放行
                    continue
                hits.append({"cat": cat.replace("checkup_", ""), "raw": raw,
                             "sent": sent[:110], "why": f"該檔無 {cat},且數字不在自身事實池"})
                break
    return hits


# ── 自檢:寫死的合成 fixture,不讀磁碟 ──────────────────────────────────
_FIX_RESULTS = {
    # 9999 有毛利率、沒有 eps/營收/本益比;9998 什麼都沒有
    "checkup_gross_margin__9999": {"claim": "近年毛利率:2023年 41.2% → 2025年 43.8%",
                                   "summary": "近年毛利率:2023年 41.2% → 2025年 43.8%"},
}

# 陽性:必須被抓到。抓不到 ⇒ 閘門形同虛設。
_FIX_POS = (
    ("裸捏 EPS", "這家公司近四季每股盈餘來到13.61元。"),
    # 🔴 迴歸鎖:「相**當**亮眼」曾讓整句被條件句豁免吃掉(2026-09-06 自檢第一次就踩)
    ("含『相當』的裸捏", "這家公司近四季每股盈餘來到13.61元,表現相當亮眼。"),
    ("中文數字裸捏", "近四季每股純益分別是十三點六一元。"),
    ("裸捏本益比", "目前本益比只有48倍,遠低於同業水準。"),
    # 🔴 迴歸鎖(台玻 1802,已下架六支之一)——**真實旁白原句**。
    #    條件子句+比喻+事實斷言擠在同一句,整句豁免會放走它;
    #    指名年份與數字同子句 ⇒ 弱豁免管不到。
    ("台玻1802真句:弱豁免句裡的指名年份斷言", "9998",
     "玻璃產業本質上就是「景氣迴圈股」，當原物料價格暴漲、需求驟降時，"
     "毛利率會像溜滑梯一樣崩跌——2022年財報就顯示其毛利率從30%跳水到剩12%，"
     "這種基本面惡化時，技術面怎麼買都會破底。"),
)
# 陰性:必須放過。誤抓 ⇒ 產線被無謂擋住,而每一條都對應一個真實發生過的偽陽性。
_FIX_NEG = (
    ("有 fact 就不看", "這家公司近年毛利率從41.2%成長到43.8%,體質穩健。"),
    ("明說沒有資料(文曄3036)", "我們沒有具體的連續配息年數或近五年平均殖利率資料。"),
    ("前瞻條件句(川湖2059)", "當資料中心擴建潮來臨,營收年增能衝到40%以上。"),
    ("比喻句(禾伸堂3026)", "本益比像體溫計,10倍是平常體溫,15倍就是發高燒。"),
    # 強豁免必須壓過年份 —— 否則「假設你在2008年買進」這種舉例會被當成宣稱
    ("帶年份的明確舉例句", "假設你在2008年買進,當時每股盈餘是5元。"),
    # 🔴 迴歸鎖(川湖 2059,在「誤判·不動」名單上)——**真實旁白原句**。
    #    年份在括號裡的舉例、數字在條件子句裡,兩者**不同子句** ⇒ 必須維持豁免。
    #    整句層級的年份規則會把它變成偽陽性(2026-09-06 實測發生過一次)。
    ("川湖2059真句:年份與數字不同子句",
     "關鍵在「產業景氣迴圈」：當全球資料中心擴建潮來臨（像 2025 年 AI 爆發），"
     "川湖的訂單會像洪水般湧入，營收年增能衝到 40% 以上，這時市場會給它超高本益比。"),
)


def self_check() -> tuple:
    """(ok, 說明)。陽性必須全部抓到、陰性必須全部放過,任一失敗 ⇒ 閘門視為壞掉 ⇒ 擋全部。

    fixture 寫死在程式碼裡、不讀磁碟 —— 事實庫變動弄不壞它。
    memory `verification-that-cannot-fail`:知道這個坑不構成免疫,救回它的是陽性對照。"""
    try:
        for row in _FIX_POS:
            name, code, txt = row if len(row) == 3 else (row[0], "9999", row[1])
            if not scan(txt, code, _FIX_RESULTS):
                return False, f"陽性對照『{name}』沒被抓到(偵測器失效)"
        for row in _FIX_NEG:
            name, code, txt = row if len(row) == 3 else (row[0], "9999", row[1])
            h = scan(txt, code, _FIX_RESULTS)
            if h:
                return False, f"陰性對照『{name}』被誤抓(偵測器過鬆):{h[0]['raw']}"
    except Exception as exc:  # noqa: BLE001
        return False, f"自檢拋例外:{exc}"
    return True, f"陽性 {len(_FIX_POS)}/{len(_FIX_POS)} 抓到、陰性 {len(_FIX_NEG)}/{len(_FIX_NEG)} 放過"


# ── 對外介面 ────────────────────────────────────────────────────────
def _load_facts():
    d = json.loads((STUDIO / "stock_checkup_facts.json").read_text(encoding="utf-8"))
    bl = json.loads((STUDIO / "stock_checkup_backlog.json").read_text(encoding="utf-8"))
    rows = bl if isinstance(bl, list) else bl.get("items", [])
    uni = {str(r["code"]): r.get("name", "") for r in rows
           if isinstance(r, dict) and r.get("code")}
    return d["results"], uni


def _norm(s: str) -> str:
    """台/臺 正規化。universe 寫「台達電」而標題寫「臺達電」⇒ 股名交叉確認失敗
    ⇒ 一支真的個股片變成「不可查證」被誤擋(2026-09-06 實測:臺達電 2308)。"""
    return s.replace("臺", "台")


def resolve_code(slug: str, results: dict, uni: dict):
    """認出這支片講的是哪一檔。先用同 repo 現成的 `audit_per_stock_facts.code_of`
    (滑動視窗 + universe 白名單 + **股名前兩字**三重交叉確認 —— 第三重就是
    「slug 裡的連續數字」騙不過的那道,本線被那個形狀騙過三次),
    失敗再用台/臺正規化重試一次。刻意不改那支現成工具:它每天在跑,
    輸出被跨日比較,我不在這裡動它的行為。"""
    from audit_per_stock_facts import code_of
    c = code_of(slug, results, uni)
    if c:
        return c
    return code_of(_norm(slug), results, {k: _norm(v) for k, v in uni.items()})


# 「個股體檢」在 slug 尾端會被截斷成 個股體檢/個股體/個股/個
_CHECKUP_SLUG_RE = re.compile(r"個股體檢|個股體$|個股$|個$")


def _has_code_candidate(slug: str, uni: dict) -> bool:
    """slug 裡有沒有任何 4 位數字是 universe 裡的真代號。"""
    for chunk in re.sub(r"\D", " ", slug[2:]).split():
        for i in range(max(len(chunk) - 3, 0) + 1):
            if chunk[i:i + 4] in uni:
                return True
    return False


def _looks_like_per_stock(slug: str, uni: dict) -> bool:
    """這支片**應該**講單一個股嗎?認不出代號時,用它決定要放行還是擋。
    **兩個訊號都要成立**,因為單獨任一個都被實測打掉過:

    ①「slug 裡有 4 位數真代號」單獨用會誤擋:年份與數量詞會撞號 ——
      2008=高興昌、2022=聚亨、1580=新麥,害「0050 定期定額連扣20年」
      「台股1580檔全部定投10年」這類大盤/ETF 片被當成不可查證的個股片。
    ②「slug 帶『個股體檢』」單獨用也會誤擋:系列彙總片
      「個股體檢584檔臺股中有287檔資料不完整」帶著這四個字,但它不講單一個股。

    兩者相乘之後,實測 249 支長片誤擋 0 支,而 6907/4585 這種真的認得出來的照擋。"""
    return bool(_CHECKUP_SLUG_RE.search(slug)) and _has_code_candidate(slug, uni)


def slug_narration(slug: str) -> str:
    """旁白全文。.voice.txt 是 TTS 逐字原稿,.md 是分段版;兩份都串起來掃。"""
    parts = []
    for suf in (".voice.txt", ".md"):
        p = OUTPUT / f"{slug}{suf}"
        if p.exists():
            parts.append(p.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def check(slug: str) -> dict:
    """回傳 {'blocked': bool, 'reason': str, 'code': str|None, 'hits': [...]}。
    這支不丟例外(掃描用);要擋人的是 gate_or_raise()。"""
    ok, msg = self_check()
    if not ok:
        return {"blocked": True, "reason": f"閘門自檢失敗:{msg}", "code": None, "hits": []}
    try:
        results, uni = _load_facts()
        code = resolve_code(slug, results, uni)
    except Exception as exc:  # noqa: BLE001
        return {"blocked": True, "reason": f"事實庫/模組載入失敗:{str(exc)[:120]}",
                "code": None, "hits": []}

    if not code:
        if _looks_like_per_stock(slug, uni):
            return {"blocked": True,
                    "reason": "個股體檢片但認不出是哪一檔股票 ⇒ 無法查證,不可放行",
                    "code": None, "hits": []}
        return {"blocked": False, "reason": "非個股體檢片,本閘門不適用",
                "code": None, "hits": []}

    text = slug_narration(slug)
    if not text.strip():
        return {"blocked": True, "reason": "找不到旁白檔(.voice.txt/.md),無法查證",
                "code": code, "hits": []}

    hits = scan(text, code, results)
    if hits:
        cats = sorted({h["cat"] for h in hits})
        return {"blocked": True,
                "reason": f"{uni.get(code, '')}{code} 旁白講了它沒有的事實類別:{'、'.join(cats)}",
                "code": code, "hits": hits}
    return {"blocked": False, "reason": "通過", "code": code, "hits": []}


def _log(slug: str, res: dict) -> None:
    """留痕。⚠️ 只 append,永不覆寫(memory write-truncates-before-it-fails)。"""
    try:
        GATE_LOG.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": datetime.now().isoformat(timespec="seconds"), "slug": slug,
               "code": res.get("code"), "blocked": res.get("blocked"),
               "reason": res.get("reason"),
               "hits": [{"cat": h["cat"], "raw": h["raw"], "sent": h["sent"]}
                        for h in res.get("hits", [])[:6]]}
        with GATE_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass          # 留痕失敗不可以影響擋人的判定
    if not res.get("blocked"):
        return
    # 🔴 擋下來也要有人看得到。只寫 jsonl 等於「有紀錄但沒有讀取者」——
    # 那是 memory `verification-that-cannot-fail` 第十一種的形狀:
    # 一支片被靜默擋掉,當天發布數少一支,而少的那支長得跟「今天沒片可發」一樣。
    # ops_log 是產線既有的、有人在讀的那本。
    try:
        from ops import log_ops
        h = res.get("hits") or [{}]
        log_ops("上架部門", f"🔴捏造閘門擋下 {slug}：{res.get('reason', '')[:80]}"
                            f"｜{h[0].get('raw', '')}「{h[0].get('sent', '')[:40]}」")
    except Exception:  # noqa: BLE001
        pass


def gate_or_raise(slug: str) -> None:
    """發布前呼叫。命中就丟 FabricationBlocked ⇒ 那支不上傳,其餘照發。

    🔴 這裡**刻意不吞例外**。閘門自己壞掉時要擋人,不是靜默放行 ——
    現行 `_factguard_gate` 是 import 失敗就整批放行,那個形狀不沿用。"""
    res = check(slug)
    _log(slug, res)
    if res["blocked"]:
        detail = ""
        if res["hits"]:
            h = res["hits"][0]
            detail = f"｜[{h['cat']}] {h['raw']}「{h['sent'][:60]}」"
        raise FabricationBlocked(f"🔴捏造閘門擋下 {slug}:{res['reason']}{detail}")


# ── CLI ────────────────────────────────────────────────────────────
def _cli() -> int:
    import argparse
    import glob
    import os

    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--scan", action="store_true", help="掃 output 下的片,只報不擋")
    ap.add_argument("--published", action="store_true", help="配 --scan:改掃已發布的")
    ap.add_argument("--slug", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ok, msg = self_check()
    print(f"自檢:{'✅ 通過' if ok else '🔴 失敗'} — {msg}")
    if args.selftest:
        return 0 if ok else 1
    if not ok:
        return 1

    if args.slug:
        res = check(args.slug)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 1 if res["blocked"] else 0

    if not args.scan:
        print("用法:--selftest | --scan [--published] | --slug <slug>")
        return 0

    led = json.loads((STUDIO / "uploaded_ledger.json").read_text(encoding="utf-8"))
    ledset = set(led)
    slugs = [os.path.basename(p)[:-4] for p in glob.glob(str(OUTPUT / "L_*.mp4"))]
    slugs = [s for s in slugs if (s in ledset) == args.published]

    blocked, passed, na, rows = [], [], [], []
    for s in sorted(slugs):
        r = check(s)
        if r["code"] is None and not r["blocked"]:
            na.append(s)
        elif r["blocked"]:
            blocked.append(s)
            rows.append({"slug": s, **r})
        else:
            passed.append(s)
    scope = "已發布" if args.published else "未發布"
    tot = len(blocked) + len(passed)
    print(f"\n=== {scope}長片 {len(slugs)} 支:適用 {tot} 支、不適用 {len(na)} 支 ===")
    print(f"擋下 {len(blocked)} 支 = 適用者的 {100 * len(blocked) / max(tot, 1):.1f}%\n")
    for r in rows:
        print(f"  🔴 {r['slug'][:52]}")
        print(f"     {r['reason']}")
        for h in r["hits"][:2]:
            print(f"     [{h['cat']}] {h['raw']} ← 「{h['sent'][:70]}」")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        print(f"\n已寫入 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
