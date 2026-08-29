# -*- coding: utf-8 -*-
"""給 make_lineup.collect() 加獨立性守門。

## 為什麼(2026-08-30 抽驗 facts.json 才發現)
`social_priming` 抓到 12 列,片子講「12 個重測、14,776 人、0 個成功」。
但那 12 列裡:

    Heat-Priming is associated with increased hostile perceptions   × 4
    Priming analytic thinking using the scrambled sentence task      × 3
    Implicitly priming God using the scrambled-sentence paradigm     × 2

**12 次嘗試其實只有 5 個範式**,而且重複列的重測 n 幾乎一樣
(331/326、121/120)—— 那是同一批受試者的不同依變項,不是不同的人。
把 12 列的 n 直接加總 = **重複計算人數**,14,776 是灌水過的。

每個數字都能溯源,守門看不到 —— 這跟 memory 記的「期間偷換」同型:
數字是真的,框架是錯的。而它的方向又剛好是「讓故事更大」。

## 加了什麼
1. `k_distinct`:去重後的範式數。旁白與標題講的是**這個**,不是 `k`。
2. `nr_sum` / `no_sum` 改成**每個範式取最大的那一列**再加總,
   不再跨重疊樣本相加。保守方向 = 少報,不是多報。
3. `MIN_DISTINCT = 4`:範式數不足就 **fail-closed 不出片**。
   `anchoring` 只有 3 個範式,而且最大那一列是 *incidental* anchoring
   (Critcher & Gilovich),經典錨定在 Many Labs 1 是**有重現**的 ——
   拿這 3 列去標「Anchoring 0 個成功」對整個效應是假的。
   這個門檻不是排版偏好,是防止用資料庫的取樣缺口去指控一整條研究路線。
"""
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = pathlib.Path(__file__).resolve().parent / "make_lineup.py"

NEW = '''
#: 一個家族至少要有幾個**互不相同的範式**才值得做成一集。
#: 見檔頭:低於這個數,樣本缺口會被說成研究路線的失敗。
MIN_DISTINCT = 4


def norm_claim(t):
    """把主張正規化到「同一個範式算同一個」的粒度。

    只做保守的處理:小寫、去標點、壓空白、砍尾巴的補語。
    刻意**不做語意合併** —— 寧可把兩個其實一樣的算成兩個(少報獨立性
    的風險是低估故事,方向安全),也不要把兩個不同的併成一個。
    """
    t = re.sub(r"[^a-z0-9 ]+", " ", str(t).lower())
    t = re.sub(r"\\s+", " ", t).strip()
    return t[:60]


def dedupe(items):
    """回傳 (範式數, 每個範式取樣本最大的那一列)。

    重複列多半是同一批受試者的不同依變項(實測:兩列 nr 是 331 / 326)。
    取最大而不是相加,是因為**相加會把同一個人算兩次**。
    """
    best = {}
    for it in items:
        k = norm_claim(it["claim"])
        if k not in best or it["nr"] > best[k]["nr"]:
            best[k] = it
    return len(best), list(best.values())

'''

HOOK = '''    k_distinct, uniq = dedupe(items)
    if k_distinct < MIN_DISTINCT:
        raise SystemExit(
            f"⛔ {family}:{len(s)} 列但只有 {k_distinct} 個互不相同的範式"
            f"(需要 {MIN_DISTINCT})。\\n"
            f"   資料庫在這個家族的覆蓋不足以代表整條研究路線,"
            f"出片會變成用取樣缺口指控一個效應。不出。")
    no_sum = sum(u["no"] for u in uniq)
    nr_sum = sum(u["nr"] for u in uniq)
'''


def main():
    s = P.read_text(encoding="utf-8")
    if "MIN_DISTINCT" in s:
        print("已經打過了"); return 0

    # 1) 插入常數與函式(放在 collect 之前)
    anchor = "def collect(family):"
    assert anchor in s, "找不到 collect"
    s = s.replace(anchor, NEW.lstrip("\n") + "\n" + anchor, 1)

    # 2) 在 return 之前算去重
    ret = "    return {\n        \"family\": family,"
    assert ret in s, "找不到 collect 的 return"
    s = s.replace(ret, HOOK + ret, 1)

    # 3) 換掉三個會被重複樣本灌水的欄位
    pairs = [
        ('        "k": len(s),',
         '        "k": len(s), "k_distinct": k_distinct,'),
        ('        "no_sum": int(s["no"].sum()), "nr_sum": int(s["nr"].sum()),',
         '        # 🔴 跨列相加會把同一批受試者算兩次 —— 見 dedupe。\n'
         '        "no_sum": no_sum, "nr_sum": nr_sum,'),
        ('        "scale": round(float(s["nr"].sum() / s["no"].sum())),',
         '        "scale": round(nr_sum / max(no_sum, 1)),'),
    ]
    for old, new in pairs:
        assert old in s, f"找不到:{old[:40]}"
        s = s.replace(old, new, 1)

    P.write_text(s, encoding="utf-8")
    import py_compile
    py_compile.compile(str(P), doraise=True)
    print("make_lineup.py 已加獨立性守門,語法通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
