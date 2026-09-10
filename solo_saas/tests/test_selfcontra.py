# -*- coding: utf-8 -*-
"""同稿自相矛盾偵測器的迴歸測試 —— **全部用真實語料,沒有一個合成 fixture**。

為什麼堅持真案例(docs/ops/2026-09-10_handoff_main_ch.md 的交代,
以及 memory `gate-blind-while-target-evolves`):
    合成 fixture 是照著我的規則寫的,它只會證明「規則是我寫的那樣」,
    不會證明「規則抓得到真實世界」。閘門上線後失效的方式就是**被監控物被改寫**,
    而 fixture 不會跟著被改寫。

🔴 對照檔不見時必須 **FAIL,不准 skip**(memory `verification-that-cannot-fail`):
   一個永遠會綠的測試比沒有測試更糟。

跑法:
    youtube_channel\\.venv\\Scripts\\python.exe solo_saas\\tests\\test_selfcontra.py
"""

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from numerus.selfcontra import (find_contradictions,        # noqa: E402
                                foreign_tokens_from_filename, readings_for)

CORPUS = r"D:\carson-agent\youtube_channel\output"

# --- 陽性對照:真的自相矛盾,必須被抓到 -----------------------------------
# (檔名關鍵字, 這一支的矛盾長什麼樣, 最小差距 pp)
POSITIVE = [
    ("聯亞3081",       "0050 年化 10.1 / 23 / 十點多 三個值並存", 10.0),
    ("旺矽6223",       "買進持有 23.1 對上 All in 11.4 —— 同一檔 ETF 同一件事", 10.0),
    ("jpp-KY5284",     "稿子自己說「同樣的回測期間」,卻給 23.6 和 11.1", 10.0),
    ("安勤3479",       "同樣資金同樣時間 23.5,同一稿十年區間 11.7", 10.0),
    ("ALL-IN0050十年", "本片主角自己的數:一次 All in 年化 23.7 又 21.7", 1.5),
    ("00919高股息",    "同一稿四個 0050 年化:49.7 / 21.3 / 31.4 / 23.8", 20.0),
]

# --- 陰性對照:真的沒有矛盾,不准被抓 -------------------------------------
# 🔴 這一區的每一支都是**我自己的誤報**,手工看過真實語料才發現的。
#    註解寫的是「它為什麼不是矛盾」——因為下一個人放寬規則時會把它放回來。
NEGATIVE = [
    ("致伸4915",     "全稿只有一個 0050 年化讀數(10.5%),沒有東西可以互相矛盾"),
    ("華邦電2344",   "30% 是台積電的,不是 0050 的 —— 中文名要當實體邊界"),
    ("雷科6207",     "「三種買法對決:ALL-IN/定期定額/0050」是列舉句,數字不歸 0050"),
    ("富邦金2881",   "同上,列舉句;20.4/12.9 是富邦金三種買法"),
    ("啟碁6285",     "33.8 是「最大虧損」不是年化 —— 量度詞彙缺一個就變誤報"),
    ("欣興3037",     "「二十三八趴」是漏字的 23.8,舊版猜成 28.0 造出假矛盾"),
    ("禾伸堂3026",   "「年化報酬只有兩成多」是口語量級,不是第二個讀數"),
    ("達明4585",     "21.6 是一次 All in、14.8 是定期定額 —— 本來就該不一樣"),
    ("當沖手續費",   "同上,一次 All in 24.7 vs 定期定額 16.9"),
    ("AI策略回測",   "「0050 歷史資料中…年化 20%」講的是那個 AI 策略,0050 是資料來源"),
    ("鴻準2354",     "33.8 後面接著「的最大回撤」—— 量度詞在數字右邊"),
    ("豐泰9910",     "同上"),
    ("大同2371",     "「遠高於百分之三點六」是一個下界,不是一個讀數"),
    ("友達2409",     "「年化報酬直接跳百分之八起跳」同理"),
    ("美股ETF定期定額vs", "「從 16.9 提升到 19.2」是同一句的前後,不是矛盾"),
    ("財報季毛利率", "「年化報酬略降至 8.8」是換了風控策略之後的值"),
]


def read(path):
    for enc in ("utf-8", "utf-8-sig", "cp950"):
        try:
            return io.open(path, encoding=enc).read()
        except (UnicodeDecodeError, LookupError):
            continue
    return ""


def find_file(keyword):
    """在語料裡找唯一一支檔名含 keyword 的稿子(排除 _redo/_bad_leak 等副本)。"""
    hits = []
    for root, _dirs, files in os.walk(CORPUS):
        for f in files:
            if f.endswith(".voice.txt") and keyword in f:
                hits.append(os.path.join(root, f))
    plain = [h for h in hits
             if os.path.dirname(h).rstrip("\\/").endswith("output")]
    return (plain or hits)


def main():
    fails = []
    checked = 0

    for keyword, why, min_pp in POSITIVE:
        paths = find_file(keyword)
        if not paths:
            # 🔴 不是 skip。對照檔不見了,這個測試就證不了任何事。
            fails.append("陽性對照檔不見了: %s —— 語料被搬動或刪除,"
                         "在補回來之前這支偵測器沒有驗收基礎" % keyword)
            continue
        path = paths[0]
        cs = find_contradictions(
            read(path), foreign_tokens=foreign_tokens_from_filename(
                os.path.basename(path)))
        checked += 1
        if not cs:
            fails.append("漏報 %s(%s)" % (keyword, why))
        elif cs[0].spread < min_pp:
            fails.append("差距太小 %s: %.1f < %.1f pp" %
                         (keyword, cs[0].spread, min_pp))

    for keyword, why in NEGATIVE:
        paths = find_file(keyword)
        if not paths:
            fails.append("陰性對照檔不見了: %s" % keyword)
            continue
        for path in paths:
            cs = find_contradictions(
                read(path), foreign_tokens=foreign_tokens_from_filename(
                    os.path.basename(path)))
            checked += 1
            if cs:
                fails.append("誤報 %s(%s)\n         %r" % (keyword, why, cs))

    # 定義域檢查:陰性對照不能因為「什麼都沒抽到」而通過。
    # (memory `filter-accepted-is-not-filter-applied`:要問相反那一邊)
    for keyword, _why in NEGATIVE[:1] + NEGATIVE[3:5]:
        for path in find_file(keyword):
            rs = readings_for(read(path),
                              foreign_tokens=foreign_tokens_from_filename(
                                  os.path.basename(path)))
            if not rs:
                fails.append("陰性對照 %s 一個 0050 年化讀數都沒抽到 —— "
                             "它是「沒有矛盾」還是「儀器瞎了」分不出來" % keyword)

    print("對照 %d 支(陽性 %d / 陰性 %d 個關鍵字)" %
          (checked, len(POSITIVE), len(NEGATIVE)))
    for f in fails:
        print("  FAIL  " + f)
    print("%s" % ("全部通過" if not fails else "%d 項失敗" % len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
