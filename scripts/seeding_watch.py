# -*- coding: utf-8 -*-
"""seeding_watch.py — 種題守望(主頻道線,2026-09-05)

## 為什麼存在
`stock_checkup_daily.py` 的 `history[].n_new_topics` 在 09-05 之後有三種值,
而**沒有任何自動化讀取者** —— -1 只有人看得到,而昨晚已經證明過「沒人拿著的哨等於沒有哨」
(兩支 session-local monitor 隨 session 一起撞 429 死掉,零訊號)。
本檔是那個讀取者,跑在**排程層**,和任何 Claude session 的生死無關。

## 判準:兩條,少任一條都會在它最該叫的場景不叫
| 值 | 意思 | 動作 |
|---|---|---|
| ≥1 | 健康 | — |
| 0 | 種題跑完但沒有新題(候選全撞重複) | 單獨一個 0 正常;**連續 K 個才叫** |
| **-1** | **種題丟例外**(同列有 seed_error) | 立刻叫 |

🔴 **為什麼一定要看「連續 K 個 0」而不只看 -1**:
09-05 之前「LLM 全滅」被 `seed_topics_for_code` 自己 catch 成 `return 0`,
所以歷史上真正打死產線的那次失效,長相是 **0 不是 -1**
(08-06/08-09/08-12/08-15/08-18/08-25/08-28 都是 16/16 全 0,08-29 是 30/30)。
只接 -1 的哨,會在它最該叫的那個場景**完全不叫**。
K=5 的校準:08-30 regime 翻轉之後最長連續 0 是 **0 檔**,所以 K=5 一次都不會誤中;
而它會在 08-21/23/24/25/26/28/29 全部響。

## 正向輸出
**每次跑都寫一行 log,健康的日子也寫** —— 「沒輸出」因此永遠是異常,而不是「沒事」。

## 演習
`--selftest` 走獨立 state、每行帶 `[DRILL]` 前綴、**永不推播**。
教訓來自 `quota_ceiling_watch`(2026-09-02):驗證員手改 state 模擬事件,
兩行 🎉 落進正式 log,和真事件一模一樣 —— **假證據落在自己指定的權威來源裡,比沒有守望更糟。**

用法:
  python scripts/seeding_watch.py              # 正式(排程每天台北 07:00,05:50 那輪跑完之後)
  python scripts/seeding_watch.py --selftest   # 演習:用預期會叫的輸入引它一次
"""
import sys, json, pathlib, datetime, collections

REPO = pathlib.Path(__file__).resolve().parent.parent
STATE = REPO / "youtube_channel" / "STUDIO" / "stock_checkup_daily_state.json"
LOG = REPO / "docs" / "ops" / "seeding-watch.log"
sys.path.insert(0, str(REPO / "youtube_channel" / "scripts"))

# 演習模式:err|zero|all。**每一條判準各要有自己的引爆輸入** ——
# 第一版只有一種 fixture,它引爆了 -1 那條而「連續 0」那條完全沒被走到,
# 而後者才是覆蓋歷史真實失效(08 月那一個月)的那條。
# 「哨叫了」不等於「每一條判準都會叫」。
SELFTEST_MODE = next((a.split("=", 1)[1] if "=" in a else "all"
                      for a in sys.argv if a.startswith("--selftest")), None)
SELFTEST = SELFTEST_MODE is not None
K_ZERO = 5          # 連續幾個 0 才算異常(校準見檔頭)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def say(t):
    try:
        print(t)
    except Exception:
        pass


def record(line):
    if SELFTEST:
        line = "[DRILL] " + line
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    say(line)


def alert(title, body):
    if SELFTEST:
        say("[DRILL] 演習不推播")
        return
    try:
        from notify import push
        push(title, body, tag="seedling")
    except Exception as e:
        say(f"(ntfy 推播失敗,不影響本檢查:{e!r})")



# ── 上游斷料偵測(2026-09-06 加)────────────────────────────────────────────
# 🔴 為什麼:FinMind 自 2026-07-18 起**連續 16 天、108 檔基本面全滅**,
# 而產線**完全沒有察覺,照常出片**(`fundamentals_yf.py:13` 自己記著「且零告警」)。
# 後果不是「片子少講一段」,是 TW_STOCK_CHECKUP_RULES 點名命令旁白依序講
# 營收→EPS→毛利→股利,而四項裡只有股利有「沒有就說沒有」的出口
# ⇒ **模型遵守規則就會用捏造去填**。6 支已公開片因此下架(2026-09-06)。
#
# 這是「外部資料源死了而下游沒有訊號」——和本檔原本在防的那一族同形,只是空值來自外部。
# ⚠️ 恢復也沒有訊號:缺項比例 07月 76% → 08月 8% → 09月 3%,沒有任何一次被記錄。
#
# 判準:**當天新算的股票裡,基本面缺項的比例**。不看絕對數(每天只算 16 檔,n 太小),
# 看比例並要求連續兩天,避開單日抖動。
FUND_KEYS = {"checkup_revenue_trend", "checkup_eps_trend", "checkup_gross_margin",
             "checkup_dividend_history", "checkup_valuation_position"}
FACTS = REPO / "youtube_channel" / "STUDIO" / "stock_checkup_facts.json"
UPSTREAM_FLOOR = 0.50     # 當天新算的股票中,基本面缺項比例超過這個就叫
UPSTREAM_MIN_N = 5        # 少於這個數不判(單日樣本太小)


def upstream_status():
    """回 (最近兩個有資料的日期各自的 (日期, 缺項比例, n))。讀不到回 []。"""
    import json as _json
    import collections as _c
    try:
        bc = _json.loads(FACTS.read_text(encoding="utf-8")).get("by_code") or {}
    except Exception:  # noqa: BLE001
        return []
    per = _c.defaultdict(lambda: [0, 0])
    for v in bc.values():
        d = (v.get("computed_at") or "")[:10]
        if not d:
            continue
        sk = {str(x.get("key", "")).split("__")[0] for x in (v.get("skipped") or [])}
        per[d][0] += 1
        per[d][1] += bool(FUND_KEYS & sk)
    out = []
    for d in sorted(per)[-2:]:
        n, miss = per[d]
        out.append((d, miss / n if n else 0.0, n))
    return out


def load_history():
    if SELFTEST:
        # 演習用**真實發生過的資料**:08-25 那天 16/16 全 0,當時零告警。
        zero = [{"date": "2026-08-25", "code": "T9%d" % i, "n_new_topics": 0} for i in range(16)]
        err = [{"date": "2026-08-25", "code": "TX", "n_new_topics": -1,
                "seed_error": "NameError: name 're' is not defined"}]
        healthy = [{"date": "2026-08-30", "code": "H%d" % i, "n_new_topics": 1} for i in range(16)]
        if SELFTEST_MODE == "err":
            return healthy + err            # 只引爆 -1 那條
        if SELFTEST_MODE == "zero":
            return healthy + zero           # 只引爆「連續 0」那條(-1 為 0 筆)
        if SELFTEST_MODE == "stale":
            # 🔴 2026-09-07 真實發生過的形狀:**今天零列**(不是全 0)。
            # 種題 05:50 因連續 5 次抓取失敗而中止,一列都沒寫,exit 0、log 記「✓ 完成」。
            # 舊判準看「最後一列」,而最後一列還是昨天那筆 16/16 ⇒ 判「✅ 正常」。
            # 零列和全 0 是兩件事,舊判準只涵蓋後者。
            old = (datetime.date.today() - datetime.timedelta(days=2)).isoformat()
            return [{"date": old, "code": "S%d" % i, "n_new_topics": 1} for i in range(16)]
        # 順序刻意是 err 在前、zero 在後:連續 0 是從**最後一筆往回數**的,
        # 把 err 放最後會把 run0 打斷成 0 —— 第一版就是這樣,"all" 其實只引爆了一條。
        return healthy + err + zero         # 兩條都引爆
    return json.loads(STATE.read_text(encoding="utf-8")).get("history") or []


def main():
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        hist = load_history()
    except Exception as e:
        line = f"[{now}] 🔴 讀不到 state,無法判斷(這不是「沒事」):{e!r}"
        record(line); alert("種題守望:讀不到帳本", line)
        return 1

    if not hist:
        line = f"[{now}] 🔴 history 是空的 —— 讀得到檔但沒有任何一輪紀錄"
        record(line); alert("種題守望:history 空的", line)
        return 1

    tail = hist[-40:]
    vals = [r.get("n_new_topics") for r in tail]
    errs = [r for r in tail if r.get("n_new_topics") == -1]

    # 連續 0:從最後一筆往回數
    run0 = 0
    for v in reversed(vals):
        if v == 0:
            run0 += 1
        else:
            break

    last_day = tail[-1].get("date", "?")
    # 🔴 新鮮度:history 的最後一列是不是今天的。
    # 2026-09-07 實據:種題 05:50 中止、**一列都沒寫**,本哨 07:00 讀「最後一列」讀到昨天那筆
    # 16/16,於是判「✅ 正常」。**零列在舊判準下結構上不可見。**
    # ⚠️ 這條和「連續 0」問的是兩件事:那條問「有跑但種不出來嗎」,這條問「今天到底有沒有跑」。
    stale_days = None
    try:
        _ld = datetime.date.fromisoformat(str(last_day))
        stale_days = (datetime.date.today() - _ld).days
    except Exception:  # noqa: BLE001
        stale_days = None
    today_rows = [r for r in tail if r.get("date") == last_day]
    ok_today = sum(1 for r in today_rows if (r.get("n_new_topics") or 0) >= 1)

    stat = (f"最後一輪 {last_day}"
            + (f"(距今 {stale_days} 天)" if stale_days else "")
            + f":{ok_today}/{len(today_rows)} 種到題"
            f"｜近 {len(tail)} 筆 連續 0={run0}(門檻 {K_ZERO})｜例外(-1)={len(errs)}")

    problems = []
    if stale_days is None:
        problems.append(f"🔴 最後一列的日期解析不出來({last_day!r})—— 判不了新鮮度,當成有問題")
    elif stale_days >= 1:
        problems.append(
            f"🔴 **今天(含)以來 history 一列都沒有**:最後一列停在 {last_day}(距今 {stale_days} 天)。"
            f"這不是「種出 0 題」,是**那一輪根本沒寫任何一列** —— 2026-09-07 的長相:"
            f"連續 5 次價格抓取失敗 → fails 達 MAX_FAILS → 中止整輪 → seeded_ok=0 → "
            f"last_run_date 不寫 → exit 0、local_cron 記「✓ 完成」,診斷訊息全印在 stdout 被丟掉。"
            f"**先看 logs/job_stderr.log 那支腳本那段,再看 STUDIO/stock_checkup_backlog.json 的 mtime。**")
    if errs:
        e0 = errs[-1]
        problems.append(f"🔴 種題丟例外 {len(errs)} 筆,最近一筆 {e0.get('code')}:"
                        f"{str(e0.get('seed_error'))[:90]} → 跑 seed_checkup_backfill.py 補種,**不要清 done**")
    if run0 >= K_ZERO:
        problems.append(f"🔴 連續 {run0} 檔種出 0 題(門檻 {K_ZERO})—— 09-05 之前這正是"
                        f"「LLM 全滅被 catch 成 return 0」的長相,那次靜默了一整個月")

    # 上游斷料:連續兩天缺項比例超標才叫
    up = [] if SELFTEST and SELFTEST_MODE not in ("upstream", "all") else upstream_status()
    if SELFTEST and SELFTEST_MODE in ("upstream", "all"):
        up = [("2026-07-18", 0.93, 14), ("2026-07-19", 1.00, 13)]   # 真實斷料窗的長相
    if up:
        stat += "｜上游 " + "、".join(f"{d} 缺{r:.0%}(n={n})" for d, r, n in up)
        bad_days = [x for x in up if x[2] >= UPSTREAM_MIN_N and x[1] > UPSTREAM_FLOOR]
        if len(bad_days) >= 2:
            problems.append(
                f"🔴 上游基本面斷料:連續兩天缺項比例 "
                f"{'、'.join(f'{d}={r:.0%}' for d, r, _ in bad_days)}(門檻 {UPSTREAM_FLOOR:.0%})"
                f" —— 2026-07-18 那次連續 16 天零告警,產線照常出片而模板命令旁白講不存在的數字,"
                f"結果是 6 支已公開片捏造財務數字。**先確認 FinMind/yfinance 是否可用,不要讓它繼續產。**")

    if problems:
        line = f"[{now}] {stat}｜" + "｜".join(problems)
        record(line)
        alert("種題守望:異常", line)
        return 1

    record(f"[{now}] ✅ 正常｜{stat}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
