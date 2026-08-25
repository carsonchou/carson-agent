#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_queue.py — 從 FReD 母體挑出可拍的集數,產生 facts/episode_queue.csv。

## 為什麼要重建(2026-08-25)
舊佇列 34 集**全是失敗**(殘存比最高 0.36),但頻道簡介寫著
「Not everything fails. Replications that succeeded get their own episodes.」
——那是一句沒有內容兌現的宣稱。這種「方法論宣稱」守門抓不到(它不含可疑數字),
只有回頭看整個佇列的分布才看得見。

母體其實有貨:156 列 successful,其中殘存比 ≥0.7 且樣本夠大的是真的站得住。
所以正解是**把守住的案例排進來**,不是把那句話刪掉。

## 兩條軌道(判定一律由數字決定,不採信 verdict 欄位單獨定調)
- FALL:原始效果夠大(|es_o| ≥ MIN_ES)、重複後殘存比 ≤ 0.5
- HOLD:重複後殘存比 ≥ 0.7 **且**作者自陳 successful(兩個條件都要,
  因為有 verdict=successful 但殘存比 0.03 的列——那是「成功證實沒有效果」)

## 排序與交錯
各軌道內按重複樣本數由大到小(樣本越大,結論越硬)。
每 HOLD_EVERY 集插一集 HOLD:觀眾看得到這個頻道不是一味打臉,
而這正是可信度的來源(主頻道「流言終結者」已驗過同一件事)。
"""
import argparse
import pathlib
import re
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent
# 來源改讀 FORRT 原始工作簿(2,164 列),而不是 fred_usable.csv(348 列)。
#
# ⚠️ 我一度以為那 1,700 列是「被丟掉的完整資料」——**不是**。fred_usable
#    就是「只留 d 與 r」的結果。母體裡 758 列的 es_type 是 **test statistic**
#    (t 或 F 值,根本不是效果量)、173 列 etasq、151 列 beta、74 列 OR。
#    拿 Cohen 的 .2/.5/.8 去講那些數字是**錯的**,不是少講。
#    讀母體的實際好處只是把 d/r/g 從 348 列擴到 482 列(跑道 19 → 30 集)。
SRC = ROOT / "facts" / "fred_2tbvd.zip"        # FORRT 原始工作簿
OUT = ROOT / "facts" / "episode_queue.csv"

# 🔴 只收**可解讀的效果量型別**。母體裡 es_type 有 test statistic / etasq /
#    beta / b / OR / r-squared,它們沒有 Cohen 門檻可套 —— 實測第一版新佇列
#    的第 0 列效果量是 **15.25**(那是個 t 值),會被講成「按慣例是大效果」。
ES_TYPES = {"d", "r", "g"}

# 🔴 只收心理學相關學科。FReD 也收遺傳學、經濟學——實測新佇列第 1 列是
#    「EFCAB4B: Involved in calcium signaling」,那不是這個頻道的題材,
#    而且我沒有能力判斷那個領域的效果量大小慣例。
DISCIPLINES = ("psychology", "marketing", "judgment", "decision",
               "behavio", "cognitive", "social")

MAX_ES = 3.0       # 上限:超過這個值的「d」多半是型別標錯
MIN_ES = 0.15      # 原始效果太小,「它縮水了」就沒有戲也沒有意義
MIN_N_R = 200      # 重複樣本的絕對下限
MIN_RATIO_N = 3    # 且至少是原始的 3 倍——敘事承重的是**倍數**不是絕對人數,
                   # 用絕對門檻 500 會砍掉 216 列卻只換到 13 集(2026-08-25 實測)
FALL_MAX = 0.50
HOLD_MIN = 0.70
HOLD_EVERY = 4     # 每 4 集出現 1 集 HOLD

# description 要唸得出口才能當「當年那篇說了什麼」。裸標籤(Analytic Priming)
# 唸出來聽不懂,66~79 字的整段摘要當旁白也不行。
MIN_W, MAX_W = 6, 28
VERB = re.compile(
    r"\b(is|are|was|were|has|have|increases?|decreases?|reduces?|improves?|"
    r"predicts?|causes?|affects?|leads?|makes?|promotes?|undermines?|correlated|"
    r"associated|should|would|will|can|more|less|higher|lower|expects?|perceives?|tends?|believe\w*)\b", re.I)

# description 欄位有些寫的是**重複研究的結果**而不是原始主張,
# 那種句子拿去當「當年那篇說了什麼」的旁白會直接說錯。
BAD_DESC = re.compile(
    r"^\s*(the\s+)?replicat|did not replicate|failed to replicate|"
    r"results?\s+showed|we\s+(found|tested)\b|this\s+(study|replication)\s+tests?",
    re.I)


def num(v):
    try:
        f = float(v)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    # 🔴 預設不覆蓋正在用的佇列。中途換佇列會讓已產出的 epNNN 與列號錯位
    #    ——那個錯已經犯過一次(重產到一半改 CSV)。
    ap.add_argument("--out", default=None,
                    help="輸出路徑(預設寫到 episode_queue.next.csv,不動現用的)")
    a = ap.parse_args()
    out_path = pathlib.Path(a.out) if a.out else (
        ROOT / "facts" / "episode_queue.next.csv")

    df = (pd.read_excel(SRC) if SRC.suffix in (".zip", ".xlsx")
          else pd.read_csv(SRC, low_memory=False))
    print(f"母體 {len(df)} 列")

    rows = []
    drop = {"缺數字": 0, "效果量型別不可解讀": 0, "非心理學領域": 0,
            "原始效果太小": 0, "重複樣本太小": 0, "主張唸不出口": 0,
            "描述寫的是重複結果": 0, "灰帶(0.5~0.7)": 0}
    for _, r in df.iterrows():
        eo, er = num(r.get("es_value_o")), num(r.get("es_value_r"))
        no, nr = num(r.get("n_o")), num(r.get("n_r"))
        if None in (eo, er, no, nr) or not no or not nr:
            drop["缺數字"] += 1
            continue
        et = str(r.get("es_type_o") or "").strip().lower()
        if et not in ES_TYPES or str(r.get("es_type_r") or "").strip().lower()                 not in ES_TYPES:
            drop["效果量型別不可解讀"] += 1
            continue
        disc = str(r.get("discipline") or "").lower()
        if not any(k in disc for k in DISCIPLINES):
            drop["非心理學領域"] += 1
            continue
        if abs(eo) < MIN_ES or abs(eo) > MAX_ES or abs(er) > MAX_ES:
            drop["原始效果太小"] += 1
            continue
        if nr < MIN_N_R or nr / no < MIN_RATIO_N:
            drop["重複樣本太小"] += 1
            continue
        desc = str(r.get("description") or "").strip()
        if not (MIN_W <= len(desc.split()) <= MAX_W) or not VERB.search(desc):
            drop["主張唸不出口"] += 1
            continue
        if BAD_DESC.search(desc):
            drop["描述寫的是重複結果"] += 1
            continue
        ratio = abs(er) / abs(eo)
        verdict = str(r.get("reported_success") or "").strip().lower()
        if ratio <= FALL_MAX:
            track = "FALL"
        elif ratio >= HOLD_MIN and verdict == "successful":
            track = "HOLD"
        else:
            drop["灰帶(0.5~0.7)"] += 1
            continue
        d = r.to_dict()
        d.update(eo=round(eo, 3), er=round(er, 3), no=int(no), nr=int(nr),
                 ratio=round(ratio, 3), track=track)
        rows.append(d)

    for k, v in drop.items():
        print(f"  淘汰 {k}:{v}")
    q = pd.DataFrame(rows)
    print(f"通過 {len(q)} 列")

    # 🔴 要按**原始研究和重複研究雙重去重**(2026-08-25)。
    #    只去重原始研究時,一篇大型多主張重複研究會生出 16 集「X 與外向性正相關」
    #    ——只換特質名。那正中 YPP inauthentic 定義的「模板化、變化極小、
    #    可大規模複製」,是人工審查的否決項(個股體檢踩過同一個坑)。
    q = q.sort_values("nr", ascending=False)
    q = q.drop_duplicates("title_o", keep="first").drop_duplicates("title_r", keep="first")
    fall = q[q.track == "FALL"].sort_values("nr", ascending=False)
    hold = q[q.track == "HOLD"].sort_values("nr", ascending=False)
    print(f"去重後:FALL {len(fall)} 集 / HOLD {len(hold)} 集")

    # 交錯:每 HOLD_EVERY 集插一集 HOLD
    out, fi, hi = [], 0, 0
    f_list, h_list = fall.to_dict("records"), hold.to_dict("records")
    while fi < len(f_list) or hi < len(h_list):
        for _ in range(HOLD_EVERY - 1):
            if fi < len(f_list):
                out.append(f_list[fi]); fi += 1
        if hi < len(h_list):
            out.append(h_list[hi]); hi += 1
        elif fi >= len(f_list):
            break

    res = pd.DataFrame(out)
    res.to_csv(out_path, index=False, encoding="utf-8")
    n_h = sum(1 for r in out if r["track"] == "HOLD")
    print(f"\n寫出 {OUT.name}:{len(out)} 集"
          f"(FALL {len(out) - n_h} / HOLD {n_h},{n_h / max(1, len(out)):.0%} 是守住的)")
    print("\n前 12 集:")
    for i, r in enumerate(out[:12]):
        print(f"  {i:>2} [{r['track']}] N_r={r['nr']:>6}  "
              f"{abs(r['eo']):.2f}→{abs(r['er']):.2f}  "
              f"{str(r['description'])[:56]}")


if __name__ == "__main__":
    main()
