#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fact_source_guard.py — 數字溯源守門(誠信硬地板)。

**為什麼要有這支(2026-07-13 品保實案)**
頻道定位是「用真回測拆穿割韭菜神話,每個結論都有數據卡佐證」。但實測抓到長片
`L_財報季毛利率成長股…` 通篇講「根據臺股十年資料,勝率只有百分之三十一」「百分之六十七的
個股財報前三個月就反映」——查遍 tw_stock_facts / backtest_cards / scripts,**根本沒有
「毛利率選股回測」這個引擎**,數字全是 LLM 編的(還在三段給出 31/57/54 三個互相矛盾的勝率)。

**既有守門為什麼擋不住**
1. `fact_guard.py` 的績效規則只認阿拉伯數字 `\\d+%`;而 `produce_batch.py` 為了 TTS 唸法
   刻意把數字轉成中文(「百分之八十二」而非「82%」)——註解甚至明寫「也讓真數字不落進
   fact_guard 的阿拉伯數字誤判」。**等於產線從設計上繞過了自己的守門。**
2. fact_guard 的 docstring 寫「或搭 daily_publish 攔」,但 `daily_publish.py` 從來沒引用過
   fact_flags——「攔」這個動作**根本不存在**,偵測到也只是記一筆,片照發。

**這支的判準(跟 fact_guard 互補,不重複)**
fact_guard 問「這句話看起來像不像捏造」(句型規則);
本支問「**這個數字查不查得到來源**」(溯源比對):
  - 從逐字稿抽出所有「績效類數字」(百分比/倍數,阿拉伯與中文唸法都抓)
  - 跟事實庫(`STUDIO/tw_stock_facts.json` + `backtest_cards.json`)裡真實算出來的數字比對
  - 對不上 → **無憑據**(unsourced)。有誠實揭露語境(示意/假設/號稱/拆穿…)才放行。

⚠️ 不能用「有沒有數字」當判準——真實回測的數字也唸成中文百分比,那樣會連好片一起殺。
唯一正確的判準是**溯源**。

用法:
  python scripts/fact_source_guard.py --report            # 只報告(看擋下來會傷多大),不擋
  python scripts/fact_source_guard.py --report --recent 30
  from fact_source_guard import unsourced_claims          # 給 daily_publish 當發布前閘門
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
OUT = ROOT / "output"
STUDIO = ROOT / "STUDIO"

# 事實庫(真實回測算出來的數字才准講)
FACT_FILES = ["tw_stock_facts.json", "backtest_cards.json", "tw_facts_computed.json"]

# 數字比對容差:口播會四捨五入(813.7% → 「百分之八百一十三」),容差要夠寬但不能寬到失效。
TOL_ABS = 1.0      # 絕對容差(百分點)
TOL_REL = 0.02     # 相對容差 2%(大數字用,如 813.7 vs 823.1 → 差 9.4 > 813.7*0.02=16.3? 否 → 仍算相符)
# ⚠️ 上面那組容差刻意「寬」:目的是抓「憑空生成、事實庫裡連個影子都沒有」的數字,
# 不是抓四捨五入誤差。抓錯誤數字(813.7 講成 823.1)是另一個問題,交 fact_guard/人工。

_CN_DIGIT = {"零": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9}

# 誠實揭露語境:同句內有這些 → 不是「本片斷言的事實」,是示意/假設/或在拆穿別人的宣稱 → 放行。
# 與 fact_guard._HEDGE 同一套精神(拆穿誇大回測是本頻道的常態合理題材)。
HEDGE = ("示意", "假設", "僅供參考", "僅為教學", "不代表未來", "非保證", "模擬情境",
         "純假設", "範例數字", "僅供示範", "歷史不代表", "舉例來說", "僅是舉例",
         "號稱", "聲稱", "宣稱", "拆穿", "揭穿", "破解", "陷阱", "迷思", "騙點閱",
         "唬爛", "誇大", "話術", "騙局", "以為", "別再信", "怎麼可能",
         # 以下三類是實測(2026-07-13)抓到的誤判來源,不是捏造斷言,放行:
         # ①數學恆等式(虧50%要賺100%才打平)——算得出來,不需要回測佐證
         "才能打平", "才能回本", "需要賺", "才回得來",
         # ②風險承受度的假設性門檻(「能承受至少30%的帳面虧損」)——是建議不是史實斷言
         "承受", "忍受", "扛得住", "撐得住",
         # ③明講是情境模擬(「5種市場情境實測」這類片會說「市場一路下跌30%」)
         "情境", "想像一下", "極端狀況")

# 績效語境詞:數字附近有這些才算「績效宣稱」(否則 2016 年、每月 5000 元、10 年 都會被誤抓)
PERF_CTX = ("報酬", "獲利", "勝率", "成功率", "命中率", "回撤", "虧損", "賠", "賺",
            "年化", "績效", "夏普", "卡瑪", "波動", "漲", "跌", "翻倍", "倍",
            "總報酬", "累積", "複利", "終值", "機率", "比例", "佔比")


def _cn_num_to_float(s: str) -> float | None:
    """把中文數字唸法轉成 float:八百一十三點七 → 813.7;三十一 → 31;六十七 → 67。
    只處理口播會出現的量級(個/十/百/千),夠用且不過度工程。"""
    s = s.strip()
    if not s:
        return None
    intpart, _, decpart = s.partition("點")
    total = 0
    cur = 0
    got = False
    i = 0
    while i < len(intpart):
        ch = intpart[i]
        if ch in _CN_DIGIT:
            cur = _CN_DIGIT[ch]
            got = True
        elif ch == "十":
            cur = cur if cur else 1
            total += cur * 10
            cur = 0
            got = True
        elif ch == "百":
            cur = cur if cur else 1
            total += cur * 100
            cur = 0
            got = True
        elif ch == "千":
            cur = cur if cur else 1
            total += cur * 1000
            cur = 0
            got = True
        else:
            return None
        i += 1
    total += cur
    if not got:
        return None
    val = float(total)
    if decpart:
        frac = ""
        for ch in decpart:
            if ch in _CN_DIGIT:
                frac += str(_CN_DIGIT[ch])
            else:
                break
        if frac:
            val += float("0." + frac)
    return val


# 百分比:阿拉伯(34.9% / 百分之34.9) 與 中文(百分之三十四點九)
_RX_PCT_ARABIC = re.compile(r"(?:百分之\s*)?(\d{1,4}(?:\.\d+)?)\s*%|百分之\s*(\d{1,4}(?:\.\d+)?)")
_RX_PCT_CN = re.compile(r"百分之([零一二三四五六七八九十百千兩點]+)")


def _clause(text: str, i: int, j: int) -> str:
    """命中點所在的同一子句(以 。！？，、\\n 分界)。跨句的誠實揭露詞不該救援本句斷言。"""
    seps = "。！？\n"
    left = max((text.rfind(c, 0, i) for c in seps), default=-1)
    cands = [p for p in (text.find(c, j) for c in seps) if p != -1]
    right = min(cands) if cands else len(text)
    return text[left + 1: right]


def extract_claims(text: str) -> list[dict]:
    """抽出所有『績效類百分比宣稱』:{value, raw, clause}。非績效語境(年份/金額/年數)不抽。"""
    text = text or ""
    claims: list[dict] = []
    seen_spans: set[tuple[int, int]] = set()

    def _add(val, raw, i, j):
        if val is None:
            return
        if (i, j) in seen_spans:
            return
        cl = _clause(text, i, j)
        # 必須在「績效語境」裡才算宣稱(否則 2016/10年/5000元 全被誤抓)
        if not any(w in cl for w in PERF_CTX):
            return
        seen_spans.add((i, j))
        claims.append({"value": float(val), "raw": raw, "clause": cl.strip()[:90]})

    for m in _RX_PCT_ARABIC.finditer(text):
        raw = m.group(0)
        num = m.group(1) or m.group(2)
        try:
            _add(float(num), raw, *m.span())
        except Exception:  # noqa: BLE001
            pass
    for m in _RX_PCT_CN.finditer(text):
        _add(_cn_num_to_float(m.group(1)), m.group(0), *m.span())
    return claims


def _walk_numbers(obj) -> set[float]:
    """把事實庫裡所有數值(含字串裡的數字)攤平成一個集合,當『可佐證數字池』。"""
    pool: set[float] = set()
    if isinstance(obj, dict):
        for v in obj.values():
            pool |= _walk_numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            pool |= _walk_numbers(v)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        pool.add(abs(float(obj)))
    elif isinstance(obj, str):
        for tok in re.findall(r"-?\d+(?:\.\d+)?", obj):
            try:
                pool.add(abs(float(tok)))
            except Exception:  # noqa: BLE001
                pass
    return pool


_POOL_CACHE: set[float] | None = None


def fact_pool(refresh: bool = False) -> set[float]:
    """事實庫裡「真的算出來過」的所有數字。空集合=事實庫還沒建起來(呼叫端要當心,別誤擋全部)。"""
    global _POOL_CACHE  # noqa: PLW0603
    if _POOL_CACHE is not None and not refresh:
        return _POOL_CACHE
    pool: set[float] = set()
    for fn in FACT_FILES:
        p = STUDIO / fn
        if not p.exists():
            continue
        try:
            pool |= _walk_numbers(json.loads(p.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass
    _POOL_CACHE = pool
    return pool


def _sourced(val: float, pool: set[float]) -> bool:
    """這個數字在事實庫裡找得到(容差內)嗎?"""
    for f in pool:
        if abs(f - val) <= max(TOL_ABS, f * TOL_REL):
            return True
    return False


def unsourced_claims(text: str, pool: set[float] | None = None) -> list[dict]:
    """回傳『查無來源的績效數字宣稱』。空 list = 全部數字都溯源得到(或本來就沒講數字)。

    放行條件(任一):
      - 同句有誠實揭露語境(示意/假設/號稱/拆穿…)→ 不是本片的事實斷言
      - 數字在事實庫容差內找得到 → 有憑據
    """
    pool = fact_pool() if pool is None else pool
    bad = []
    for c in extract_claims(text):
        if any(h in c["clause"] for h in HEDGE):
            continue
        if _sourced(c["value"], pool):
            continue
        bad.append(c)
    return bad


def slug_text(slug: str) -> str:
    """一支片的全部文字(旁白逐字稿 + 標題/描述 .md)——捏造數字兩邊都可能出現。"""
    parts = []
    for suffix in (".voice.txt", ".md"):
        p = OUT / f"{slug}{suffix}"
        if p.exists():
            try:
                parts.append(p.read_text(encoding="utf-8", errors="replace"))
            except Exception:  # noqa: BLE001
                pass
    return "\n".join(parts)


def check_slug(slug: str, pool: set[float] | None = None) -> list[dict]:
    return unsourced_claims(slug_text(slug), pool)


def main() -> int:
    recent = 40
    if "--recent" in sys.argv:
        try:
            recent = int(sys.argv[sys.argv.index("--recent") + 1])
        except Exception:  # noqa: BLE001
            pass
    pool = fact_pool()
    print(f"[fact_source_guard] 事實庫可佐證數字池:{len(pool)} 個")
    if len(pool) < 10:
        print("[fact_source_guard] ⚠️ 事實庫太小(<10 個數字)——現在若開啟硬擋,"
              "會把幾乎所有片都擋掉(產線停擺)。先把 tw_facts_engine 的真實回測灌進事實庫。")

    voices = sorted(OUT.glob("S_*.voice.txt"), key=lambda f: -f.stat().st_mtime)[:recent]
    voices += sorted(OUT.glob("L_*.voice.txt"), key=lambda f: -f.stat().st_mtime)[:10]
    n_bad = 0
    rows = []
    for f in voices:
        slug = f.stem.replace(".voice", "")
        bad = check_slug(slug, pool)
        if bad:
            n_bad += 1
            rows.append((slug, bad))
    print(f"[fact_source_guard] 掃 {len(voices)} 支,{n_bad} 支含『查無來源的績效數字』"
          f"({n_bad * 100 // max(1, len(voices))}%)")
    for slug, bad in rows[:12]:
        print(f"\n  ✗ {slug[:44]}")
        for c in bad[:3]:
            print(f"      無憑據數字 {c['value']}  ←「{c['clause']}」")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
