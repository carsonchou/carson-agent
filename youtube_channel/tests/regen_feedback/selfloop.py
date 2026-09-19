#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""重生自環率:連續兩稿的失敗理由是不是同一個。

用法:
    cd youtube_channel
    .venv/Scripts/python.exe tests/regen_feedback/selfloop.py
    .venv/Scripts/python.exe tests/regen_feedback/selfloop.py --since 09-04

## 這是唯一真正的驗收指標

`produce_batch` 的重生迴圈原本**沒有回饋**:失敗原因算出來、寫進 log,然後丟掉 ——
`call_claude()` 的簽章接不住它。三次重生是三個位元組相同的呼叫,只差取樣隨機性。
**那不是「重生沒收斂」,是沒有迴圈。** 背景與通則見
`docs/ops/2026-09-03_regen_independence_fallacy.md`。

⚠️ **不要用「良率上升」當證據**:良率單日在 0~96% 之間擺,單日變化說明不了任何事。

## 🔴 第一版的量尺量的不是它宣稱的東西(2026-09-03 驗證員實測)

第一版**依標題分組**,而標題會在重生之間改變:

    符合正規式 434 行 → 依標題分組只剩 23 組配對(用掉 10% 的資料)

而倖存的那 23 組**不是隨機子樣本**:

    標題相同(工具看得到)  n= 10   自環 80.0%
    標題不同(工具看不到)  n=205   自環 54.1%

**工具只看得到自環率高 26pp 的那一小撮** —— 重生後標題還一樣 = 新稿和舊稿很像
= 更可能以同一種方式失敗。量尺**選擇性地保留了自環樣本**。

而偏差方向**正好對著它要驗的修法**:回饋若有效,新稿更不一樣、標題更會變 →
同標題配對更少 → 母體再往「改最少的那些稿」收縮。
**它被設計來偵測的改善,正是它最偵測不到的。**

還有假配對:22 個標題群組裡 6 組出現重複序號(`[1,1]`),是兩支不同片因**截斷標題撞名**
被併成一個 run,`sort()` 再把 A 片第一稿配上 B 片第一稿 —— 跨片比較。

⚠️ **「60.9% 與診斷員 57.1% 吻合」不是佐證,是警訊**:兩者共用同一個偏差(都依標題配對)。
**共用偏差的兩次量測互相吻合,不構成獨立印證。**

→ 本版改成**依重生計數器相鄰配對**(第 n → 第 n+1,同一種迴圈),**完全不看標題**。
   驗證員已驗過可信度:run 內相鄰時間差中位 4.3 分、0/221 可疑配對,無平行跑交錯。
"""
import argparse
import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LOG = ROOT / "STUDIO" / "ops_log.txt"

# 六條迴圈各自的 log 前綴。名稱要跟著 produce_batch 的 log 走 ——
# 少收一種就會像第一版那樣「量到的比實際少一個數量級」而且不會有訊號。
# (log 前綴, 顯示名)。⚠️ 前綴就是 log 裡逐字的那一段 —— 正規式由它導出,
# 自檢也拿它比對。第一版把顯示名寫成「鎖題終檢」而 log 是「鎖題長片終檢」,
# 於是自檢把 296 行**已經正確收到**的資料誤報成「沒收到」。
# 同一個東西寫兩份就會分岔,這條線今天已經證明過三次 —— 所以只留一份。
KINDS = (
    ("A4長片", "A4長片"),
    ("鎖題長片終檢", "鎖題終檢"),
    ("標題閘門", "標題閘門"),
    ("Shorts閘門", "Shorts閘門"),
    ("A2捏造績效", "A2捏造績效"),
)
LINE = re.compile(r"^\[(\d\d-\d\d) [\d:]+\] 補產·重生｜(.+)$")
_SINCE = re.compile(r"^\d\d-\d\d$")
# 🔴 KINDS 漏收一種就會**靜默少算**,而那正是上面那行註解自己警告的形狀:
# 第一版漏了四種(只收 A4 與鎖題終檢),這一版仍漏了 A1b(6/221 = 2.7%)。
# 與其每次靠人記得補,不如讓它**自己講**:掃 log 裡所有 `X第N次重生` 的前綴,
# 不在 KINDS 裡的一律列出來。以後新增迴圈也不會無聲漏收。
ANY_KIND = re.compile(r"^(.+?)第\d+次重生:")


def family(reason):
    """把理由歸成家族:字面相同一定同家族;家族相同而字面不同(兩種長度訊息)仍算自環。"""
    for key in ("長度不足", "段數", "資訊密度", "期間", "矛盾", "洩漏", "碎句", "跑題",
                "鋪陳", "罐頭", "禁語", "編造統計", "欄位標記"):
        if key in reason:
            return key
    return reason[:12]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="", help="從這個日期(MM-DD)第一次出現處起算")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # 🔴 打錯字不准偽裝成「還沒產」。`--since 2026-09-01` / `9-3` / `garbage` 在第一版
    # 全部靜靜回「0 支片、產線還沒跑」——而第二段驗收整個押在這一個手打的旗標上。
    if a.since and not _SINCE.match(a.since):
        print(f"🔴 --since 格式錯誤:{a.since!r},應為 MM-DD(例:09-04)")
        return 2

    raw = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    # 🔴 用**檔案位置**切,不用字串比大小。log 沒有年份,而 "01-05" < "09-04" 為 True
    # → 明年一月起 `--since 09-04` 會把所有新資料當成更早濾光,永遠回「沒有資料」。
    # append-only 的 log 本身就是時序,取「該日期第一次出現之後」不受跨年影響。
    start = 0
    if a.since:
        for i, ln in enumerate(raw):
            m = LINE.match(ln.strip())
            if m and m.group(1) == a.since:
                start = i
                break
        else:
            print(f"⚠️ log 裡找不到 {a.since} 的任何重生紀錄 —— "
                  "這**不是**「自環率 0」,是那一天還沒有重生發生(或日期打錯)。")
            return 2

    # 依計數器相鄰組 run:同一種迴圈,序號 n → n+1 才配對;看到 n<=前一個就開新 run。
    runs = collections.defaultdict(list)      # (迴圈別, run 序) → [(序號, 理由)]
    cur = {pre: [0, None] for pre, _ in KINDS}   # 迴圈別 → [run 序, 上一個序號]
    for ln in raw[start:]:
        m = LINE.match(ln.strip())
        if not m:
            continue
        rest = m.group(2)
        for pre, name in KINDS:
            mm = re.match(re.escape(pre) + r"第(\d+)次重生:(.+?)｜", rest)
            if not mm:
                continue
            n, reason = int(mm.group(1)), mm.group(2).strip()
            prev = cur[pre][1]
            if prev is None or n <= prev:      # 新的一支片(序號歸 1 或倒退)
                cur[pre][0] += 1
            cur[pre][1] = n
            runs[(name, cur[pre][0])].append((n, reason))
            break

    pairs = same = same_g = 0
    trans = collections.Counter()
    by_kind = collections.Counter()
    for (kind, _r), seq in runs.items():
        for (n1, r1), (n2, r2) in zip(seq, seq[1:]):
            if n2 != n1 + 1:                   # 序號不連續就不配(保守,寧可少算)
                continue
            pairs += 1
            f1, f2 = family(r1), family(r2)
            same += f1 == f2
            same_g += r1 == r2          # 閘門級:失敗訊息逐字相同
            trans[(f1, f2)] += 1
            by_kind[kind] += 1

    # 自檢:有沒有 KINDS 沒收的迴圈前綴
    seen, known = collections.Counter(), {pre for pre, _ in KINDS}
    for ln in raw[start:]:
        m = LINE.match(ln.strip())
        if not m:
            continue
        mm = ANY_KIND.match(m.group(2))
        if mm and mm.group(1).strip() not in known:
            seen[mm.group(1).strip()] += 1

    win = f"(--since {a.since},從第 {start + 1} 行起)" if a.since else "(全部)"
    print(f"重生日誌 {win}:{len(runs)} 個 run、連續兩稿 {pairs} 組")
    print(f"   配對方式:**依重生計數器相鄰**(第 n → 第 n+1,同一種迴圈),不看標題\n")
    if not pairs:
        print("⚠️ 沒有可比的連續兩稿 —— 這**不是**「自環率 0」,是沒有資料。")
        print("   改動後要重量,需要新產的稿(每次重生 = 一次 LLM 大呼叫)。")
        return 2
    # 🔴 2026-09-03 督導更正:自環率**不是**驗收指標,它單獨看不出改善。
    # 獨立驗證員量到:長度 k 的 run 貢獻 k-1 組配對,所以「重生一次就成功」的 run
    # 貢獻 0 組 —— 208/215 組(97%)來自撞上限的 run,自環率幾乎只在量「救不回來的那些」。
    # 敏感度模擬:25%/50%/75% 的 run 提早成功時,分母 215→148→90→50(崩 77%),
    # 而率只在 52.7~56.0% 之間**非單調**地晃 —— 那是雜訊不是訊號。
    # **修法成功的訊號在分母與 run 長度分佈,不在率。** 看下面那四行,不要看這一行。
    print(f"   (參考,非驗收指標)自環率家族級:{same}/{pairs} = {same / pairs * 100:.1f}%")
    print(f"   自環率(閘門級,失敗訊息逐字相同):{same_g}/{pairs} = {same_g / pairs * 100:.1f}%")
    print("   基準(回饋上線前,同一支工具、同一種配對法):"
          "**家族級 55.3%(n=215)/ 閘門級 52.1%**")
    # 🔴 基準**不是** 54.1%:那是驗證員用來**證明偏差**的「標題不同」子集(n=205),
    # 不是母體。拿它當基準會把改動前估低,讓改動後看起來比實際差 ——
    # 而那一行正是第二段要拿來對照的數字。
    print("   ⚠️ 基準不是 54.1% —— 那是用來證明偏差的子集(n=205),不是母體")
    print("   ⚠️ 也不要跟舊版的 57~61% 比 —— 那組是依標題配對,偏高 26pp\n")
    print("各迴圈的配對數:", dict(by_kind))
    print()
    print("🔴 驗收看這三行(自環率單獨看不出改善,見上方註解):")
    print(f"   ① 配對數(分母):{pairs}          基準 215 —— **變小才是好事**")
    _len_by_kind = collections.defaultdict(collections.Counter)
    for (kind, _r), seq in runs.items():
        _len_by_kind[kind][len(seq)] += 1
    for kind in sorted(_len_by_kind):
        dist = dict(sorted(_len_by_kind[kind].items()))
        tot = sum(dist.values())
        one = dist.get(1, 0)
        print(f"   ② {kind} run 長度分佈:{dist}"
              f"   長度1佔 {one}/{tot} = {one / max(tot, 1) * 100:.1f}%")
    print("      基準 A4長片 {1:5, 2:5, 3:1, 4:30}(長度1佔 12.2%)、"
          "鎖題終檢 {1:60, 2:118}(長度1佔 33.7%)")
    print("      **質量往長度 1 移 = 重生一次就成功 = 修法有效**")
    print("   ③ fail-closed 率另外從 ops_log 的 ⛔ 行數算,基準 A4長片 78.0%、鎖題終檢 61.2%")
    if seen:
        tot = sum(seen.values())
        print(f"\n⚠️ **KINDS 沒收到的迴圈前綴 {len(seen)} 種、{tot} 行**"
              f"({tot / (tot + sum(by_kind.values())) * 100:.1f}% 的重生沒被算進去):")
        for k, c2 in seen.most_common():
            print(f"   {c2:>4}  {k}")
        print("   → 要嘛加進 KINDS,要嘛在此說明為什麼刻意不收。**不要讓它繼續靜默**。")
    print("\n轉移(前一稿 → 後一稿),前 10:")
    for (f1, f2), c in trans.most_common(10):
        print(f"   {c:>3}  {f1} → {f2}" + ("  ← 自環" if f1 == f2 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
