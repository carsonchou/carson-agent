#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""checkup_facts_prefix_health.py —【唯讀】事實庫 key 前綴健康檢查。

方案書:docs/ops/2026-09-09_design_fact_key_ownership.md §4。

## 它在補哪一個洞

`merge_and_write()` 裡的 `others_after == others_before` 對 2026-09-09 那個真實事故是**盲的**:
`checkup_industry_rank__{code}` 被誤刪時,那個 key 對「正在被合併的代號」來說前後都算
「自己的」⇒ **總數不變** ⇒ 閘門不叫。判準必須從「總數」換成「**按前綴分組**」。

## 兩種告警,不是同一件事

  ① **整個前綴消失**(`overall == 0` / 檔案裡一個 key 都不剩)—— 損害最大的那一種。
  ② **覆蓋率下降**(最近重算的 N 檔明顯低於整體)—— 正在流失、但還沒流失完。

🔴 為什麼要分開:第一版**只做了 ②**,而 ② 是拿「現存 key」建表的 ——
   482 個 rank key 被刪光時,那一列根本不存在,gap 無從計算 ⇒ 印「✅ 一切正常」、`exit=0`。
   **偵測器在傷害最大的那一刻閉嘴**(memory `verification-that-cannot-fail`)。
   ⇒ 現在母體改成**應有清單**:`OWNED_PREFIXES ∪ FOREIGN_PREFIXES ∪ 檔案裡實際出現過的前綴`。
     「應該在而不在」本身就是告警,不需要先有 key 才算得出來。

## 判準:level-triggered,量狀態不等事件

② 的判準是比較兩個覆蓋率:
  · 整體覆蓋率 = 有這個前綴的代號數 / `by_code` 全部代號數
  · 最近覆蓋率 = 有這個前綴的代號數 / 最近重算過的 N 檔(依 `computed_at` 排序)
這是量「現在的狀態」不是等「刪除事件發生」,所以它不需要在事故當下在場 ——
事故過了三天再跑它照樣叫得出來。(memory `detector-failure-shapes-2026-09`。)

## 🔴 唯讀

這支**不寫事實庫**,一個 byte 都不寫。它只 `read_text()`。
不要幫它加「順手修好」的功能 —— 偵測器和修復器混在一起時,偵測器壞掉會變成修復器亂改。

用法:
  python scripts/checkup_facts_prefix_health.py                # 預設 N=50 跑正式檔
  python scripts/checkup_facts_prefix_health.py --recent 34    # 換 N
  python scripts/checkup_facts_prefix_health.py --file X.json  # 換母體(回放/測試用)
  python scripts/checkup_facts_prefix_health.py --quiet        # 只印告警與偵測力,不印全表

離開碼:0 = 沒有告警;1 = 有告警;2 = 母體讀不掉/形狀不對/參數無效。

## 建議排程(crontab)

    45 5 * * * /root/yt/run.sh scripts/checkup_facts_prefix_health.py >> /root/yt/logs/cron.log 2>&1

05:45 = 日班 `stock_checkup_daily.py --count 16`(`crontab.txt:152`,05:50)之前、
週日 `checkup_industry_rank.py --apply`(`:622`,06:40)之後一整天
⇒ 讀到的一定是**沒有寫入端在跑的靜止檔**,量到的狀態不會是某一輪合併做到一半的中間態。

⚠️ **不要**用「B 開著檔會害 `_atomic_write_json` 的 `os.replace` 撞 `PermissionError`」當理由 ——
   那條**實測不成立**:B 全程 0.21s、純 `read_text` 只有 0.05s;併發壓測 32 輪 B × 12 次真寫入
   ⇒ 需要退避 **0** 次、失敗 **0** 次(15.5s 的退避預算是 0.21s 的 74 倍)。
   機制是真的,但開檔窗口小到撞不到。選 05:45 的理由只有「靜止檔」那一條。

**exit code 實務上沒人看得到**(cron 對 rc=1 不做任何事、cron.log 一天幾百行)——
所以有告警時本支會另外寫一行進 `STUDIO/ops_log.txt`,那條時間軸才有人看。

驗證:python -m py_compile scripts/checkup_facts_prefix_health.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 前綴表從 stock_checkup_facts 匯入,**不要在這裡複製一份**。
# 兩份表各自過期是「表會過期」這個弱點的平方,而這支的存在理由正是要盯那個弱點。
# ⚠️ 這條 import 會把 tw_facts_engine / stock_fundamentals 的模組本體一起執行。實測代價:
#    0.010s、96 個模組、**pandas/numpy/yfinance 一個都沒被載入**(那些是函式內延遲 import)。
#    代價夠小,所以選擇維持單一真相來源;搬走的討論見第二輪回報。
from stock_checkup_facts import (  # noqa: E402
    OUT_FILE, OWNED_PREFIXES, FOREIGN_PREFIXES, _key_prefix,
)

# ── 門檻 ──────────────────────────────────────────────────────────────────────
#
# ② 覆蓋率下降的告警條件:最近覆蓋率比整體覆蓋率低 ≥ ALERT_GAP_PP 個百分點。
#
# 🔴 為什麼是 15:這個數字是**量出來的,不是挑出來的**。拿 2026-09-09 的正式檔
#    (8,137 key / 651 檔 / 13 前綴)在 N=16/34/50/80 四種切法下全表跑過:
#      · 11 個健康的自有前綴,最大的**負向**偏離是 `checkup_crash` 在 N=16 的 **-2.7pp**
#        (其餘全是正的 —— 最近算的那批覆蓋率通常比歷史平均**高**,因為舊資料有早期失敗殘留)
#      · 真實事故 `checkup_industry_rank`:N=34 **-74.0pp**、N=50 **-52.0pp**、N=80 **-25.3pp**
#    ⇒ 2.7 和 25.3 之間是一整段空的。15 放在這段空帶裡,兩邊各有 5.5x / 1.7x 餘裕。
#    ⚠️ 這個餘裕是**這一份母體**量出來的。母體換了(例如頻道改抓一批冷門股)要重量一次。
ALERT_GAP_PP = 15.0

# 🔴 為什麼預設 N=50:兩個力量拉反方向,50 是**算過的**折衷,不是隨手填的。
#    · 要小 —— N 越大,新事故被舊資料稀釋得越厲害。日班 `--count 16` 一天重算 16 檔 ⇒
#      N=50 ≈ **3 天的產量**,偵測延遲上限約 3 天(N=50 時那個真實事故仍有 -52.0pp)。
#      ⚠️ 稀釋是**會讓它完全叫不出來**的:實測同一份母體 **N≥160 時只剩 -12.8pp,低於門檻**。
#         所以本支每次都會印「偵測力上限」那一行,見 detection_ceiling()。
#    · 要大 —— N 越小,抽樣雜訊越大。N=16 時**一檔就是 6.25pp**,15pp 門檻只等於 2.4 檔;
#      對一個整體覆蓋率 97% 的前綴,16 檔裡漏 3 檔的機率約 1.4%(二項分佈),
#      11 個前綴一起看 ⇒ **每跑一次約 14% 機率誤叫**。那種偵測器兩週就沒人理了。
#      N=50 時一檔只有 2pp、門檻 = 7.5 檔,是 4 個標準差以外 ⇒ 誤叫率可忽略。
DEFAULT_RECENT_N = 50


def load_facts(path: Path) -> dict:
    """唯讀載入。讀不掉就退出(離開碼 2),**不回空骨架** —— 空骨架會讓這支印「一切正常」。"""
    if not path.exists():
        print(f"[prefix_health] 🔴 母體不存在:{path}")
        raise SystemExit(2)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"[prefix_health] 🔴 母體讀不掉:{path}:{exc!r}")
        raise SystemExit(2) from exc
    if (not isinstance(data, dict) or not isinstance(data.get("results"), dict)
            or not isinstance(data.get("by_code"), dict)):
        print(f"[prefix_health] 🔴 母體形狀不對:{path}"
              f"(results={type(data.get('results')).__name__ if isinstance(data, dict) else 'n/a'}、"
              f"by_code={type(data.get('by_code')).__name__ if isinstance(data, dict) else 'n/a'})")
        raise SystemExit(2)
    return data


def index_keys(data: dict):
    """把 results 拆成 (前綴 -> 代號集合)、(前綴 -> 總 key 數)、(前綴 -> 無法歸戶的 key 數)。

    key 形狀是 `prefix__code` 或 `prefix__code__window`(只有 checkup_crash 是三段),
    所以代號取 split 的第二段;**取完要回頭確認它真的在 by_code 裡**,
    對不上的另外收進 unattributed 而不是默默丟掉 —— 默默丟掉的東西就是下一個盲區。
    """
    res, byc = data["results"], data["by_code"]
    codes_of: dict[str, set] = {}
    keys_total: dict[str, int] = {}
    unattributed: dict[str, int] = {}
    for k in res:
        parts = k.split("__")
        prefix = _key_prefix(k)
        keys_total[prefix] = keys_total.get(prefix, 0) + 1
        code = parts[1] if len(parts) >= 2 else None
        if code in byc:
            codes_of.setdefault(prefix, set()).add(code)
        else:
            unattributed[prefix] = unattributed.get(prefix, 0) + 1
    return codes_of, keys_total, unattributed


def recent_order(byc: dict):
    """依 computed_at 由新到舊。⚠️ `computed_at` 是**日期字串**(`2026-09-09`),不含時間 ⇒
    同一天大量並列(實測 2026-08-03 一天 49 檔)。並列時誰算「比較近」本來就沒有答案,
    所以次鍵用代號**把順序釘死**,讓同一份母體每次跑出同一個 recent 集合(可重現)。
    這解決的是「可重現」,**不是**「取樣正確」—— 見 main() 的誤叫清單第 ④ 條。
    """
    return sorted(byc, key=lambda c: ((byc[c].get("computed_at") or ""), c), reverse=True)


def analyse(data: dict, recent_n: int):
    """回傳 (rows, unattributed, n_recent, n_all)。純計算,不印、不寫。"""
    byc = data["by_code"]
    codes_of, keys_total, unattributed = index_keys(data)

    # 🔴 母體 = **應有清單**,不是「現存 key 推出來的清單」。
    #    這是第一版最嚴重的洞:前綴被刪光時它連那一列都不存在 ⇒ 恆不叫。
    expected = set(OWNED_PREFIXES) | set(FOREIGN_PREFIXES) | set(keys_total)

    order = recent_order(byc)
    recent_codes = set(order[:recent_n])
    n_all, n_recent = len(byc), len(recent_codes)

    rows = []
    for prefix in expected:
        codes = codes_of.get(prefix, set())
        total = keys_total.get(prefix, 0)
        unattr = unattributed.get(prefix, 0)
        owner = ("自有" if prefix in OWNED_PREFIXES
                 else "他人" if prefix in FOREIGN_PREFIXES else "未知")
        if total == 0:
            # ① 應該在,但檔案裡一個 key 都沒有。這是最嚴重的一格,而且**不需要覆蓋率**就算得出來。
            kind, alert = "消失", True
            overall = recent = gap = 0.0
        elif not codes and unattr == total:
            # 有 key,但一個都不是按代號編的(`checkup_industry_summary__{產業名}`)⇒
            # 沒有「每檔覆蓋率」這個東西可以量。**這不是告警,是本檢查的盲區**,照實講。
            kind, alert = "非代號編", False
            overall = recent = gap = 0.0
        else:
            kind = "覆蓋率"
            overall = len(codes) / n_all * 100 if n_all else 0.0
            recent = len(codes & recent_codes) / n_recent * 100 if n_recent else 0.0
            gap = recent - overall
            alert = gap <= -ALERT_GAP_PP
        rows.append({"prefix": prefix, "owner": owner, "kind": kind, "n_keys": total,
                     "n_codes": len(codes), "overall": overall, "recent": recent,
                     "gap": gap, "alert": alert})
    rows.sort(key=lambda r: (r["kind"] != "消失", r["gap"]))
    return rows, unattributed, n_recent, n_all


def detection_ceiling(data: dict):
    """掃 N=1..n_all-1,回傳 (safe_n, max_n, holes, prefix)。

    · `safe_n`  = **最大的連續會叫區間上界**:1..safe_n 每一個 N 都叫得出來。
    · `max_n`   = 最大的**會叫**的 N(它上面可能有一堆不會叫的 N)。
    · `holes`   = safe_n 與 max_n 之間**不會叫**的 N。

    🔴 為什麼要分 safe_n 和 max_n,不能只印一個上限:
       第一版只印 max_n=146,而**這份母體在 1..146 之間就有 13 個 N 不會叫**
       (125,126,127,132,133,135,137,138,139,140,141,142,143)。
       覆蓋率是**階梯函數**,gap 在門檻附近來回穿越 ⇒ 會不會叫**不是單調的**:
       實測 120 −16.5(叫)、125 −14.8(不叫)、130 −15.6(叫)、140 −14.0(不叫)、
       144 −15.0(叫)、147 −14.9(不叫)。
       「上限 146」會被讀成「N ≤ 146 都叫得出來」——**那是假的**,而讀這行字的人
       正是要拿它去選 N 的。⇒ 對外承諾只能用 safe_n,max_n 只能當「再往上就全滅」的參考。

    🔴 為什麼一定要印這個:`--recent` 調大時偵測力是**靜默**歸零的 ——
       N 一大,最近集合逼近全母體,每個 gap 都趨近 0,工具照樣印「✅ 一切正常」`exit=0`。
       ⇒ 「使用者把參數調到偵測力歸零」必須**產生輸出**,不能只是不叫。
    ⚠️ 這些數字是**針對檔案現在這個狀態**算的,不是對「任何未來事故」的保證。
       事故越輕(偏離越小),叫得出來的 N 範圍就越窄。
    """
    byc = data["by_code"]
    codes_of, keys_total, _ = index_keys(data)
    order = recent_order(byc)
    n_all = len(byc)

    tracked = [(p, c, len(c) / n_all * 100) for p, c in codes_of.items()
               if keys_total.get(p, 0) > 0]
    hits = {p: 0 for p, _, _ in tracked}
    fires: set[int] = set()
    worst_prefix, worst_gap = None, 0.0
    for n in range(1, n_all):        # n_all 本身無意義:recent == 全母體 ⇒ gap ≡ 0
        code_n = order[n - 1]
        for p, codes, overall in tracked:
            if code_n in codes:
                hits[p] += 1
            gap = hits[p] / n * 100 - overall
            if gap <= -ALERT_GAP_PP:
                fires.add(n)
                if gap < worst_gap:
                    worst_gap, worst_prefix = gap, p
    if not fires:
        return None, None, [], None
    max_n = max(fires)
    safe_n = 0
    while safe_n + 1 in fires:
        safe_n += 1
    holes = [n for n in range(safe_n + 1, max_n + 1) if n not in fires]
    return safe_n, max_n, holes, worst_prefix


def main() -> int:
    ap = argparse.ArgumentParser(description="事實庫 key 前綴健康檢查(唯讀)")
    ap.add_argument("--recent", type=int, default=DEFAULT_RECENT_N,
                    help=f"最近重算的 N 檔當比較組(預設 {DEFAULT_RECENT_N})")
    ap.add_argument("--file", type=str, default=None, help="改用別的母體檔(回放/測試用)")
    ap.add_argument("--quiet", action="store_true", help="只印告警與偵測力,不印全表")
    ap.add_argument("--no-log-ops", action="store_true",
                    help="有告警時不寫 STUDIO/ops_log.txt（顯式逃生門；"
                         "非正式機母體本來就不會寫,不需要這個旗標）")
    args = ap.parse_args()

    if args.recent < 1:
        print(f"[prefix_health] 🔴 --recent 要 ≥ 1(收到 {args.recent})")
        return 2
    path = Path(args.file) if args.file else OUT_FILE
    data = load_facts(path)
    n_all = len(data["by_code"])

    # 🔴 上界:recent 集合 = 全母體時,每個前綴的「最近」和「整體」是同一群代號 ⇒
    #    gap **恆等於 0** ⇒ 這支恆不叫。那不是「檢查通過」,是**檢查沒有定義**。
    #    這種輸入必須被拒絕,不可以靜靜回 exit=0(那正是第一版在全損時的失效形狀)。
    if args.recent >= n_all:
        print(f"[prefix_health] 🔴 --recent={args.recent} ≥ 母體代號數 {n_all} ⇒ "
              f"比較組會等於全母體,每個前綴的偏離恆為 0、這支恆不叫。**這是無效輸入,不是通過。**"
              f"    請給 < {n_all} 的值(預設 {DEFAULT_RECENT_N})。")
        return 2

    rows, unattributed, n_recent, _ = analyse(data, args.recent)

    print(f"[prefix_health] 母體 {path}")
    print(f"[prefix_health] {len(data['results']):,} 個 key / {n_all:,} 檔 / "
          f"{len(rows)} 個應有前綴;比較組 = 最近重算的 {n_recent} 檔")
    if not args.quiet:
        print(f"  {'前綴':<30}{'歸屬':<6}{'型態':<10}{'整體':>9}{'最近':>9}{'偏離':>10}")
        for r in rows:
            mark = "🔴" if r["alert"] else "  "
            if r["kind"] == "消失":
                print(f"{mark}{r['prefix']:<30}{r['owner']:<6}{'消失':<10}"
                      f"{'—':>9}{'—':>9}{'(0 個 key)':>12}")
            elif r["kind"] == "非代號編":
                note = f"({r['n_keys']} 個 key)"
                print(f"  {r['prefix']:<30}{r['owner']:<6}{'非代號編':<10}"
                      f"{'—':>9}{'—':>9}{note:>12}")
            else:
                print(f"{mark}{r['prefix']:<30}{r['owner']:<6}{'覆蓋率':<10}"
                      f"{r['overall']:>8.1f}%{r['recent']:>8.1f}%{r['gap']:>+9.1f}pp")

    # 偵測力:**每次都印**,不管有沒有告警。
    safe_n, max_n, holes, ceil_prefix = detection_ceiling(data)
    if safe_n is None:
        print(f"[prefix_health] ℹ️ 偵測力:目前母體沒有任何前綴在任何 N 下會超過 -{ALERT_GAP_PP:.0f}pp "
              f"⇒ 現在沒有「② 覆蓋率下降」等級的異常可供校準。"
              f"(「① 整個前綴消失」不受 N 影響,任何 N 都叫得出來。)")
    else:
        # 🔴 對外承諾只用 safe_n。max_n 之下有洞,拿 max_n 當「可以選的 N」會選到不會叫的值。
        in_hole = args.recent in holes
        if args.recent <= safe_n:
            room = "餘裕夠"
        elif in_hole:
            room = f"🔴 **N={args.recent} 正好落在洞裡,這個 N 叫不出來**"
        elif args.recent <= max_n:
            room = "⚠️ 超過連續區間(這個 N 剛好會叫,但相鄰的 N 未必)"
        else:
            room = "🔴 **已超過所有會叫的 N,偵測力歸零**"
        hole_note = (f";再往上到 {max_n} 之間**非單調、有 {len(holes)} 個 N 不會叫**"
                     f"(例:{holes[:6]}{'…' if len(holes) > 6 else ''}),{max_n} 以上全滅"
                     if holes else f";{max_n} 以上全滅")
        print(f"[prefix_health] ℹ️ 偵測力:以目前母體,最嚴重的偏離(`{ceil_prefix}`)"
              f"在 **N ≤ {safe_n} 時每一個 N 都叫得出來**{hole_note}。"
              f"目前 N={args.recent} ⇒ {room}。"
              f"⚠️ 要選 N 請只依 {safe_n} 這個數,不要依 {max_n}。")

    alerts = [r for r in rows if r["alert"]]
    gone = [r for r in alerts if r["kind"] == "消失"]
    drop = [r for r in alerts if r["kind"] == "覆蓋率"]
    if not alerts:
        print(f"[prefix_health] ✅ 應有的 {len(rows)} 個前綴都在,且沒有前綴的最近覆蓋率"
              f"低於整體達 {ALERT_GAP_PP:.0f}pp。")
        return 0

    if gone:
        print(f"[prefix_health] 🔴🔴 {len(gone)} 個**應有的前綴整個不見了**"
              f"（不是覆蓋率下降 —— 檔案裡一個 key 都不剩）:")
        for r in gone:
            print(f"    · `{r['prefix']}`（歸屬:{r['owner']}）0 個 key。"
                  f"若歸屬是「他人」,最可能是本腳本的 stale_keys 判準把它刪光了;"
                  f"若是「自有」,最可能是產出端整個失敗。")
    if drop:
        print(f"[prefix_health] 🔴 {len(drop)} 個前綴的最近覆蓋率顯著偏低:")
        for r in drop:
            print(f"    · `{r['prefix']}`（歸屬:{r['owner']}）"
                  f"整體 {r['overall']:.1f}% → 最近 {n_recent} 檔 {r['recent']:.1f}%"
                  f"（{r['gap']:+.1f}pp,門檻 -{ALERT_GAP_PP:.0f}pp）")
    print("[prefix_health] ⚠️ **偏低不等於「被誤刪」**。下面是會讓它誤叫的真實情況,先排除再下結論:")
    print("    ① 最近那批剛好是冷門股 —— 基本面五組(revenue/eps/gross_margin/dividend/"
          "valuation)本來就有 ~13% 的代號抓不到,連續抽到一串小型股就會壓低最近覆蓋率。")
    print("    ② 資料來源掛掉 —— FinMind 2026-07-18 起連不上,害 16 天 108 檔基本面全滅。"
          "那次的簽名是**五個基本面前綴同時叫**;誤刪別人 key 的簽名是**單一他人前綴在叫**。")
    print("    ③ 有人**故意**停產某個前綴 —— 那會長得跟事故一模一樣。"
          "確認是故意的之後,把它從 stock_checkup_facts.OWNED_PREFIXES 拿掉。")
    print("    ④ 取樣邊界 —— `computed_at` 只到日,同一天可以並列數十檔"
          "(實測 2026-08-03 有 49 檔)。N 切在並列中間時 recent 集合含哪幾檔是**任意的**"
          "(已用代號當次鍵釘死,可重現,但不代表那是「對的」取樣)。"
          "結論靠近門檻時,換一個 --recent 再跑一次看結論穩不穩。")

    # 🔴 排程跑的時候,**exit code 沒有人看得到** —— crontab 那行是 `>> logs/cron.log 2>&1`,
    #    cron 不會因為 rc=1 做任何事,而 cron.log 每天幾百行。
    #    ⇒ 告警要送進工廠統一日誌 `STUDIO/ops_log.txt`(同 A 的未知前綴告警、
    #      同 `stock_fundamentals.py:503` 的用法),那裡才是有人看的時間軸。
    # ⚠️ 這**不違反唯讀**:唯讀講的是「不寫事實庫」。這裡寫的是 append-only 的日誌,
    #    一個 byte 都沒有回寫到 results/by_code。
    #
    # 🔴🔴 只有在讀的**就是正式機事實庫**時才送。2026-09-09 這一格洩了兩次:
    #    測試/回放拿 scratchpad 副本當母體,`log_ops` 照樣把一則維運日誌寫進正式機
    #    `STUDIO/ops_log.txt`(母體欄印的是 `facts_master.json` / `gone.json` 這種檔名,
    #    對讀日誌的人是純噪音)。
    #    ⚠️ 第一次的修法是「在測試端釘 sys.modules['ops']」,那修的是**測試環境**不是工具:
    #       `sitecustomize` 由 `site` 在直譯器啟動時 import,那時 `sys.path[0]` 還不是腳本目錄
    #       ⇒ 放在腳本旁邊的那份**根本不會被看到**,B 一被當子行程跑就再洩一次。
    #    ⇒ 判準改成**語意上就對的那一條**:不要為一個非正式機的母體,寫一則正式機的維運日誌。
    #      它不依賴環境變數、不依賴誰記得釘 sys.path,**子行程一樣有效**。
    #      `--no-log-ops` 只是額外的顯式逃生門,**預設安全不靠它**。
    is_prod = path.resolve() == OUT_FILE.resolve()
    if not is_prod:
        print(f"[prefix_health] ℹ️ 母體不是正式機事實庫（{path}）⇒ **不送 log_ops**"
              f"（正式機是 {OUT_FILE}）。告警只在上面的 stdout。")
    elif args.no_log_ops:
        print("[prefix_health] ℹ️ --no-log-ops ⇒ 不送 log_ops。告警只在上面的 stdout。")
    else:
        # ⚠️ 包在 try 裡:日誌通道壞掉不可以讓這支變成 rc=2(那會讓「有告警」被誤讀成「跑不起來」)。
        try:
            from ops import log_ops
            head = "；".join(
                (f"{r['prefix']} 整個消失" if r["kind"] == "消失"
                 else f"{r['prefix']} {r['overall']:.0f}%→{r['recent']:.0f}%")
                for r in alerts[:4])
            log_ops("事實庫前綴健康",
                    f"🔴 {len(alerts)} 個前綴異常（消失 {len(gone)}、覆蓋率下降 {len(drop)}）：{head}"
                    f"｜N={n_recent}")
        except Exception as exc:  # noqa: BLE001
            print(f"[prefix_health] ⚠️ log_ops 送不出去（{exc!r}）—— 告警只存在於 stdout。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
