# -*- coding: utf-8 -*-
"""三元組算術自洽尺:同一句裡的 (總報酬 R, 年化 a, 期間 n) 彼此算不算得通。

## 為什麼要另外一把(04 為什麼不夠)
04 的參考點是**0050 那一腳**:它問「個股的 n 和 0050 的 n 對不對得上」。
所以它看不見兩類東西:
  1. 句子裡沒有 0050 的(全部 Shorts、以及只講個股的段落);
  2. 個股與 0050 **兩腳都用同一個錯期間**的情況 —— 兩邊一致,04 判無害。
本尺不需要配對:參考點改成**同句自己宣告的期間**。
n_implied = ln(1+R)/ln(1+a),要求 |n_implied - n_stated| <= 1.5 年。

## 這把尺不知道哪一個數字錯,這是特徵不是缺陷
2026-09-11 實測抓到方向**相反**的兩型,而判準一樣:
  · 漢磊 3707:期間對(近10年)、**年化被改掉**(事實庫 18.6% → 旁白 6.5%)
  · S_0050vs0056 三支:數字對(事實庫 12.6 年那組)、**期間被改掉**(12.6 年 → 「十年」)
不自洽只證明「這三個數不可能同時成立」,要開原檔才知道是哪一個。

## 🔴 為什麼它和誠信守門(fact_source_guard)是正交的、必須兩把都在
守門問的是「這個數字在事實池裡找不找得到」,而池是一個 38,231 個數字的**扁平集合**
(memory `yt-fact-guard-pool-saturation`)⇒ 6.5 這種數字幾乎一定找得到,整句放行。
本尺不問數字存不存在,問三個數彼此合不合算術 —— **池子被餵飽打不倒它**。
⚠️ 還有一件:守門把「示意/假設/約」當誠實揭露語境(HEDGE)放行。
   本尺**刻意不認 HEDGE**:遮詞可以豁免「沒有憑據」,不能豁免「算術上不可能」。
   實例:詮欣 6205 那句原文是「總報酬**假設為** 215.7%(年化 6%)」。

## 射程限制(③ 反方向被放掉的,寫在這裡不是寫在報告裡)
1. **定義域只有三成**:818 支裡只有 247 支抽得到三元組。只給單一數字的句子本尺全盲。
2. **最大回撤不在三元組裡**:漢磊同一句的 -81.2%/-76.1%/-33.8% 被改寫成 -78%/-61%/-33%,
   本尺一個都看不到。同一句裡「非頭條數字被重述時被改掉」比本尺量到的範圍大。
3. **時間錨點錯看不見**:可成 2474 講「二零一四年一月一日…到二零二三年底」而片發於 2026 年,
   三元組自洽 ⇒ 放行。
4. **下界豁免是刻意留的洞**:年化或期間被寫成「超過/至少/以上」且 n_implied 偏大時放行
   (那與下界一致)。真違規剛好落在這個方向 ⇒ 放行。這是為了砍掉永豐金/藥華藥兩個誤報付的價。
5. 讀的是磁碟上今天的 .voice.txt,不等於當初發布的那一版 ⇒ 報的是下界。

## 對照(全部真案例,不用合成 fixture)
13 陽性 + 6 陰性,全部來自第一版 21 個命中、我逐支開原檔判過的結果(不是抽樣)。
第一版有三個具名解析 bug,每一個都對應下面一組陰性對照:
  (a) 負號被吃掉 ⇒ 凌巨 8105、豐泰 9910(真值 -25.4%/-2.9% ⇒ 9.97 年,本來就自洽)
  (b) 套牢期被當成報酬期間 ⇒ 久元 6261「套牢近9年」、翔名 8091「長達四年又七個月」
  (c) 下界被讀成等號 ⇒ 永豐金 2890「年化超過百分之十」、藥華藥 6446「超過十年」
🔴 對照不過就 exit,不准掃描 —— 修誤報會靜默吃掉真陽性(memory `fp-fixes-silently-eat-true-positives`),
   所以每次改判準都要當場證明 13 個真陽性一個都沒掉,而不是只看命中數變少了。
"""
import re, io, os, glob, sys, math

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
RULER04 = os.path.join(HERE, "04_matched_pair_ruler.py")
OUTDIR = os.path.abspath(os.path.join(HERE, "..", "..", "output"))

# 解析器沿用 04(連它的 13 項單元測試一起跑)—— 不複製常數,它改了本尺跟著改
_g = {"__name__": "_ruler04_head"}
exec(compile(io.open(RULER04, encoding="utf-8").read().split("def scan(path):")[0],
             RULER04, "exec"), _g)
cn2num, TOT, ANN, SENT = _g["cn2num"], _g["TOT"], _g["ANN"], _g["SENT"]

NEG = re.compile(r"(負|-|−|﹣|－)\s*(?:百分之|\d)")
LOWER = re.compile(r"超過|逾|至少|以上|多於|不止")   # 🔴 刻意不含「高達」:那是語氣不是下界
                                                    #    含進去會吃掉日電貿 3090 這個真陽性
YRS = re.compile(r"(?:([\d.]+)|([零〇一二三四五六七八九十百千萬兩點]+))\s*年")
NOT_PERIOD = re.compile(r"套牢|解套|創高|間隔|長達|腰斬|停滯|又$|個月")
# 🔴 09-11:NOT_PERIOD 要**雙向**掃。本檔原本只掃前文(治「套牢近9年」),
#    而退稿區母體的長相是「4.6年套牢」—— 非期間詞在**後面**。只掃一邊會漏,
#    05_rejected_backlog.py 的已知誤報(嘉澤3533)就是這一格。後綴窗只取 4 字
#    (「套牢」「解套」都是 2 字,放寬會開始吃到下一句)。
TOL = 1.5


def _val(m):
    v = cn2num(m.group(1)) if m.group(1) else float(m.group(2).replace(",", ""))
    if v is None:
        return None
    return -v if NEG.search(m.group(0)) else v


def stated_years(s):
    """句內所有「報酬期間」宣稱。回傳 [(年, 是不是下界)]。"""
    out = []
    for m in YRS.finditer(s):
        v = float(m.group(1)) if m.group(1) else cn2num(m.group(2))
        if v is None or v >= 100 or v <= 0.5:   # >=100 是年份(2016年)不是期間
            continue
        pre = s[max(0, m.start() - 14):m.start()]
        if NOT_PERIOD.search(pre) or NOT_PERIOD.search(s[m.end():m.end() + 4]):
            continue
        out.append((v, bool(LOWER.search(pre))))
    return out


def triples(path):
    txt = io.open(path, encoding="utf-8", errors="replace").read()
    res = []
    for sm in SENT.finditer(txt):
        s = sm.group(0).strip()
        if not s:
            continue
        ny = stated_years(s)
        if not ny:
            continue
        for tm in TOT.finditer(s):
            am = ANN.search(s[tm.end():tm.end() + 60])
            if not am:
                continue
            R, A = _val(tm), _val(am)
            if R is None or A is None or R <= -100 or A <= -100 or R == 0 or A == 0:
                continue
            try:
                n_imp = math.log(1 + R / 100.0) / math.log(1 + A / 100.0)
            except ValueError:
                continue
            if n_imp <= 0:
                continue
            a_low = bool(LOWER.search(s[tm.end():tm.end() + am.end()]))
            n, n_low = min(ny, key=lambda t: abs(n_imp - t[0]))
            gap = abs(n_imp - n)
            if gap > TOL and (a_low or n_low) and n_imp > n:
                continue          # 下界方向豁免(見 docstring 射程限制 4)
            res.append({"R": R, "a": A, "n_imp": round(n_imp, 2), "n": n,
                        "gap": round(gap, 2), "bad": gap > TOL, "sent": s[:150]})
    return res


# ── 先驗尺:真案例對照,不過就 exit ────────────────────────────────
POS = ["創意3443", "南亞科2408", "慧洋-KY2637", "日電貿3090", "漢磊3707", "華城1519",
       "華立3010", "詮欣6205", "雷科6207", "群創3481",
       "0050vs0056vs00878", "0050vs0056十年", "0050一次Allin"]
NEG_CTL = {
    "久元6261": "「套牢近9年」被當成報酬期間",
    "翔名8091": "「長達四年又七個月」的套牢期被當成期間",
    "永豐金2890": "「年化超過百分之十」是下界,真值 10.87%",
    "藥華藥6446": "「超過十年」是下界,真值 12.4 年",
    "凌巨8105": "負號被吃掉(真值 -25.4%/-2.9% ⇒ 9.97 年,自洽)",
    "豐泰9910": "負號被吃掉(真值 -35.6%/-4.3% ⇒ 10.01 年,自洽)",
}


def scan_all():
    files = sorted(glob.glob(os.path.join(OUTDIR, "*.voice.txt")))
    dec = ntrip = 0
    hits = []
    for p in files:
        t = triples(p)
        if not t:
            continue
        dec += 1
        ntrip += len(t)
        b = [x for x in t if x["bad"]]
        if b:
            hits.append((os.path.basename(p), b))
    return files, dec, ntrip, hits


def main():
    files, dec, ntrip, hits = scan_all()
    names = " | ".join(n for n, _ in hits)
    miss = [k for k in POS if k not in names]
    still = [k for k in NEG_CTL if k in names]
    print("== 對照(真案例,先驗尺)==")
    for k in POS:
        print(("  ✅ 陽性 " if k not in miss else "  🔴 陽性掉了 ") + k)
    for k, why in NEG_CTL.items():
        print(("  ✅ 陰性已消 " if k not in still else "  🔴 陰性還在 ") + k + " —— " + why)
    print("  陽性 %d/%d、陰性 %d/%d" % (len(POS) - len(miss), len(POS),
                                        len(NEG_CTL) - len(still), len(NEG_CTL)))
    if miss or still:
        print("🔴 對照沒全過,這把尺不准用來下結論。")
        return 2
    print()
    print("== ②母體:磁碟上今天的 .voice.txt ==")
    print("  全部           %d" % len(files))
    print("  可判定         %d  (抽不到三元組 = 不可判定,**不算通過**)" % dec)
    print("  三元組         %d" % ntrip)
    print("  命中片數       %d  (%.1f%% of 可判定)" % (len(hits), 100.0 * len(hits) / max(dec, 1)))
    print()
    for name, b in hits:
        print("🔴", name)
        for x in b:
            print("   R=%.1f%% a=%.1f%% ⇒ n_implied=%.2f 年,同句宣告 %.1f 年,差 %.2f"
                  % (x["R"], x["a"], x["n_imp"], x["n"], x["gap"]))
            print("   句:", x["sent"])
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
