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

演習模式(每一條判準各要有自己的引信,而且**兩個方向都要有**):
| 模式 | 引爆什麼 | 期望 |
|---|---|---|
| `err` | 種題丟例外(-1) | 叫 |
| `zero` | 連續 K 個 0 | 叫 |
| `stale` | 今天零列(不是全 0) | 叫 |
| `all` | err + zero + 上游斷料 | 叫 |
| `upstream` | 注入斷料窗的長相(不碰事實庫) | 叫 |
| `unreadable` | **事實庫讀不到**(沙箱路徑指向不存在的檔) | 叫 |
| `empty` | **事實庫讀得到但判不出**(`by_code` 空) | 叫 |
| `upstream_ok` | **陰性對照**:沙箱裡放一份健康事實庫 | **不叫** |

`unreadable` / `empty` / `upstream_ok` 三個模式會把 `FACTS` monkeypatch 到臨時沙箱,
並在收尾用**正式機檔案的指紋(存在/大小/mtime_ns)前後比對**斷言它沒被動過;
沙箱沒生效就 `AssertionError` 當場炸,不是印一行警告靠人看。
(`STUDIO/stock_checkup_facts.json` 是 17MB 單檔,直到 2026-09-08 才被納入 snapshot 清單。)

用法:
  python scripts/seeding_watch.py              # 正式(排程每天台北 07:00,05:50 那輪跑完之後)
  python scripts/seeding_watch.py --selftest   # 演習:用預期會叫的輸入引它一次
  python scripts/seeding_watch.py --selftest=upstream_ok   # 陰性對照:確認它不是恆叫
"""
import sys, json, pathlib, datetime, collections, tempfile, shutil

REPO = pathlib.Path(__file__).resolve().parent.parent
STATE = REPO / "youtube_channel" / "STUDIO" / "stock_checkup_daily_state.json"
LOG = REPO / "docs" / "ops" / "seeding-watch.log"
sys.path.insert(0, str(REPO / "youtube_channel" / "scripts"))
sys.path.insert(0, str(REPO / "scripts"))   # 讓 import watch_crosscheck 不看「是誰啟動的」
import watch_crosscheck   # 互查在模組層 import:缺檔/壞檔在**啟動時**大聲失敗,不是在收尾時靜靜跳過

# 演習模式:err|zero|all。**每一條判準各要有自己的引爆輸入** ——
# 第一版只有一種 fixture,它引爆了 -1 那條而「連續 0」那條完全沒被走到,
# 而後者才是覆蓋歷史真實失效(08 月那一個月)的那條。
# 「哨叫了」不等於「每一條判準都會叫」。
SELFTEST_MODE = next((a.split("=", 1)[1] if "=" in a else "all"
                      for a in sys.argv if a.startswith("--selftest")), None)
SELFTEST = SELFTEST_MODE is not None
K_ZERO = 5          # 連續幾個 0 才算異常(校準見檔頭)

# 會把 FACTS 換到沙箱的演習模式。前兩個該叫、第三個**不該叫**(陰性對照)。
# 沒有陰性對照時,「該叫的都叫了」和「這條判準恆叫」分不開 —— 那是 memory
# `verification-that-cannot-fail` 的第零種:輸出長得跟成功一樣的檢查。
DRILL_FACT_MODES = ("unreadable", "empty", "upstream_ok")

# 推播失敗的演習模式(2026-09-09 加)。這兩個模式是「留痕會不會叫」的**陽性對照** ——
# pushfail = push() 回 False(不拋例外那條);pushraise = 後端丟例外那條。
# 兩條都必須在 log 裡長出「吞掉但留痕」+ 判決行後綴 + 收尾行,否則留痕是壞的。
DRILL_PUSH_MODES = ("pushfail", "pushraise")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def say(t):
    # ⚠️ 這個 except **刻意不留痕**,而且它是本輪的陰性對照:
    # 排程用 pythonw ⇒ `sys.stdout is None` ⇒ `print(t)` 是**靜默 no-op 不丟例外**(實測),
    # 所以這條 except 在排程上根本不會被走到;真要留痕也只會變成每輪都叫的雜訊。
    # 同理上面那個 `sys.stdout.reconfigure` 的 except(stdout 是 None → AttributeError → 每輪必中)。
    # **判準:留痕的對象是「本來應該成功的事」,不是「本來就預期失敗的事」。**
    try:
        print(t)
    except Exception:
        pass


# ── 吞掉但留痕(2026-09-08)────────────────────────────────────────────────
# 🔴 `try: <告警> except: pass` 的缺陷**不是「吞」** —— 記 log 失敗不該弄垮判準,那個設計是對的。
# 缺陷是**吞掉之後沒有任何辦法知道它在吞**。09-08 實據:`auditability_coverage` 的 `log_ops`
# 筆誤被吞掉,上線兩天 ops_log 0 筆,而它每天準時跑、rc=0、看起來完全正常。
#
# ⚠️ 但這三支哨**不可以照抄** `auditability_coverage` 那個「印到 stderr」的範本。
# 那支是 local_cron 的 job(stderr 落 `logs/job_stderr.log`、stdout 從 09-08 起落 `logs/jobout/`);
# 這三支是 **Windows 排程工作、走 `pythonw.exe`、Actions 裡沒有任何重導向**(實查排程定義)。
# 2026-09-08 實測(detached 無 console,重現排程環境):
#   `sys.stdout is None` ✅ / `sys.stderr is None` ✅
#   `print(msg, file=sys.stderr)` → **靜默 no-op**(file=None 退回 sys.stdout,而它也是 None)
#   `sys.stderr.write(msg)`       → **AttributeError**
#   寫檔                          → ✅ 有效(這也是這三支的 log 每天長得出來的唯一原因)
# ⇒ 照抄範本,會在**唯一重要的那個環境裡完全靜默**,而在互動終端測起來是好的。
#   那正是本輪要治的病本身。**所以主通道是 log 檔,stderr 只是互動/local_cron 下的第二條路。**
_SWALLOWED = []


def swallowed(what, e=None):
    """吞掉但留痕。判準(exit code 與上面的輸出)完全不受影響,只是不再靜默。

    🔴 **這個函式在三支哨裡各有一份,是刻意的,不要抽成共用模組。**
    理由見 `youtube_channel/deploy/WATCHDOG.md:116-127`:這三支的設計前提就是
    「和被監視的東西平行、不依賴產線」——抽成共用模組會讓哨依賴一個會被改的東西,
    而那個東西壞掉時,三支哨會**同時**變啞(它們正是為了偵測產線變啞而存在的)。
    再加一條(2026-09-09):母體還可能長到 6~9 支,共用模組的風險隨支數放大。
    ⇒ 代價是改一次要改三份。**這是已經權衡過的取捨,不是待清理的重複碼。**
    """
    msg = f"{what}" + (f"({type(e).__name__}: {e})" if e is not None else "")
    _SWALLOWED.append(msg)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    line = (("[DRILL] " if SELFTEST else "") + f"[{stamp}] ⚠️ 吞掉但留痕:{msg}"
            " —— 判準不受影響,但這行代表那件事沒被記錄/沒送出,請修。")
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass          # log 也寫不進去就真的沒路了,下面 stderr 是最後一條
    try:
        if sys.stderr is not None:
            print("[warn] " + line, file=sys.stderr)
    except Exception:
        pass
    return msg


# ── 🔴 2026-09-09:留痕要出現在**讀者的視線裡**,不是只存在於檔案某處 ───────────
# 獨立驗證(docs/ops/2026-09-09_verify_c09a2486.md §4.1)推翻了上面那段的完成度:
# `_SWALLOWED` 原本是**唯寫**的 —— 只有 `= []` 和 `.append()`,全 repo 沒有任何地方讀它。
# 後果不是「少一個功能」,是**留痕看不見**:判決行永遠不會說「這輪吞了東西」,
# 留痕是**另一行**,而推播失敗那條還排在判決行**後面**
# ⇒ 只看最後一行、或 grep 判決行的人,拿到的是「✅ 正常」。
# ⚠️ 那正是這支哨要治的病本身,只換了一層:從「訊號不存在」變成「訊號在讀者視線外」。
# 兩條都補:①`record()` 一律把件數綴進判決行;②收尾再補一行,讓 **log 的最後一行**
# 一定講得出這輪有沒有吞掉東西(判決行之後才發生的吞掉只能靠這條)。
# ⚠️ **exit code 不動** —— 它是排程/watchdog 在讀的穩定基準,這一輪不同時動兩個變數
# (派工單 §五.2 同樣的理由)。要升級成 rc≠0 請單獨開一棒,並先列出誰在讀它。
def swallow_suffix() -> str:
    """給判決行用的後綴。沒吞東西時回空字串(不製造每輪必中的雜訊)。"""
    if not _SWALLOWED:
        return ""
    return (f"｜⚠️ 本輪吞掉 {len(_SWALLOWED)} 件:"
            + "; ".join(_SWALLOWED)[:200])


def swallow_epilogue() -> None:
    """收尾行:確保「這輪吞了東西」是 log 的最後一行,而不是被判決行蓋過去。"""
    if not _SWALLOWED:
        return
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    line = (("[DRILL] " if SELFTEST else "")
            + f"[{stamp}] ⚠️ 本輪收尾:吞掉 {len(_SWALLOWED)} 件(含判決行之後才發生的,"
              f"例如推播失敗)—— " + "; ".join(_SWALLOWED)[:300])
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def record(line):
    # 補跑時 WATCH_MANUAL=1 ⇒ 前綴打在**讀數行本身**,不靠後面追加的註記行去指認它
    # (註記行只帶「我被寫下的時間」,不帶「我在指誰」—— 隔天才註記就失效,而且往不叫倒)。
    line = watch_crosscheck.manual_prefix() + line
    if SELFTEST:
        line = "[DRILL] " + line
    line += swallow_suffix()          # 判決行自己要說得出「這輪吞了東西」
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    say(line)


def _push_and_trace(pusher, title, body):
    """推播 + 兩條失敗路徑的留痕。**演習與正式走同一份程式碼** ——
    把 pusher 當參數傳進來,而不是在演習分支裡複製一份判斷:
    複製出來的演習只證明得了複本會叫,證明不了本體會叫。"""
    try:
        if not pusher(title, body, tag="seedling"):
            swallowed("ntfy 推播回報未送出(push() 回 False:topic 沒設定,或所有後端都失敗)"
                      " —— 手機不會響,log 這行是唯一痕跡")
    except Exception as e:
        swallowed("ntfy 推播丟例外 —— 手機不會響", e)


def _drill_push_false(*_a, **_k):
    return False


def _drill_push_raise(*_a, **_k):
    raise RuntimeError("演習:模擬推播後端丟例外")


def alert(title, body):
    if SELFTEST:
        # 🔴 2026-09-09 常駐回歸(驗證 §4.2):原本演習**在碰 push 之前就 return**,
        # 於是 13 個演習模式的留痕實測全是 0 —— 唯一證明「留痕會叫」的東西是驗證員
        # 當場手搭的 harness,repo 裡沒有、排程裡也沒有。
        # memory `gate-blind-while-target-evolves`:閘門上線後要有東西**定期證明它還抓得到已知案例**。
        # ⚠️ 真 `push` 只在下面非 SELFTEST 的分支才 import ⇒ 演習路徑上它根本不存在,
        #    不是靠「記得不要呼叫」。這是把禁令放在**入口**,不是放在心裡(dispatch.md §6)。
        if SELFTEST_MODE in DRILL_PUSH_MODES:
            _push_and_trace(_drill_push_false if SELFTEST_MODE == "pushfail"
                            else _drill_push_raise, title, body)
            return
        say("[DRILL] 演習不推播")
        return
    # 🔴 推播失敗原本有**兩條路都到不了讀者**,兩條都在這五行裡:
    # ① 拋例外那條 → 原本走 `say(...)`,而 say 在排程環境是靜默 no-op
    #    ⇒「告警送不出去」這件事本身也送不出去。`WATCHDOG.md` 09-06 就記過這個洞
    #    (「log 有紅字而手機沒響」),而它從那天起一直開著。
    # ② **不拋例外那條** → `push()` 任一後端成功才回 True、都沒設定/403/5xx 回 False,
    #    而這裡**根本沒看回傳值** ⇒ topic 沒設、被封、網路斷,都會安靜地當成推播成功。
    #    (`notify.push` 自己的診斷是 `print`,在 pythonw 下同樣是 no-op ⇒ 那層也看不到。)
    try:
        from notify import push
    except Exception as e:
        swallowed("ntfy 匯入失敗 —— 手機不會響", e)
        return
    _push_and_trace(push, title, body)



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
    """回 `(rows, err)`。

    rows = 最近兩個有資料的日期各自的 `(日期, 缺項比例, n)`;err = None。
    判不出來時回 `([], "為什麼判不出來")` —— **空集合一律配一句理由,不留無聲的空。**

    🔴 2026-09-08 修的失敗形態:舊版讀不到事實庫時回 `[]`,而 `main()` 用 `if up:`
    接它 ⇒ **整個上游段落從 log 裡消失**:不報錯、不推播、exit 0,那一行照樣寫「✅ 正常」。
    也就是說,事實庫被改名 / 被鎖 / 寫壞的那一天,這道哨會從「每天回報上游缺項比例」
    無聲地退化成「每天回報種題那三條」,而**兩種日子的 log 行只差一個看不出來的欄位**。
    同一支腳本裡種題那三條壞掉會出聲,只有上游這條不會。
    ⚠️ 方向:**讀不到 ≠ 上游健康。** 判不出來就必須說判不出來,不可以 fail-open 成沒事。
    這正是 09-06 捏造事故的形狀(FinMind 斷 16 天、108 檔全滅、零告警),
    差別只在那次是資料變空,這次連告警的入口都不見了。

    ⚠️「讀不到」比「丟例外」寬,而舊版只有例外那條路徑:
    `by_code` 是空的、或條目全都沒有 `computed_at`,都**不會丟例外**,舊版一樣回 `[]`。
    所以下面三個出口分開寫,錯誤訊息也分開 —— 修的人要知道是檔案不見了還是內容變了。
    """
    import json as _json
    import collections as _c
    try:
        raw = FACTS.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return [], f"讀不到事實庫 {FACTS.name}({FACTS}):{e!r}"
    try:
        bc = _json.loads(raw).get("by_code") or {}
    except Exception as e:  # noqa: BLE001
        return [], f"事實庫 {FACTS.name} 解析失敗({len(raw)} bytes):{e!r}"
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
    if not out:
        return [], (f"事實庫 {FACTS.name} 讀得到({len(raw)} bytes)但判不出上游:"
                    f"by_code {len(bc)} 筆、其中帶 computed_at 的 0 筆")
    return out, None


# ── 演習沙箱:上游那條的引信與陰性對照(2026-09-08)──────────────────────
# 🔴 不可以拿正式機的事實庫做演習:17MB 單檔,而它的自動備份今天才補上。
# 隔離的做法是**在入口把 FACTS 換掉**,不是靠下游函式自律 —— 派工單/註解層的
# 「絕對不要碰正式機」被違反時不產生任何輸出,那是期望不是規則(dispatch.md §6)。
# 所以下面配一組**會產生輸出的**斷言:換沒換成功當場 AssertionError,
# 收尾再拿正式機檔案的指紋前後比對,不一致就把 rc 蓋成 9。
PROD_FACTS = FACTS
_DRILL_DIR = None
_PROD_FP = None


def _fingerprint(p):
    """(存在, 大小, mtime_ns) —— 只 stat 不讀,17MB 檔也是零成本。"""
    try:
        st = p.stat()
        return (True, st.st_size, st.st_mtime_ns)
    except FileNotFoundError:
        return (False, None, None)


def _drill_setup(mode):
    global FACTS, _DRILL_DIR, _PROD_FP
    _PROD_FP = _fingerprint(PROD_FACTS)
    _DRILL_DIR = pathlib.Path(tempfile.mkdtemp(prefix="seeding_watch_drill_"))
    if mode == "unreadable":
        FACTS = _DRILL_DIR / "does_not_exist.json"          # 檔案不見了
    elif mode == "empty":
        FACTS = _DRILL_DIR / "facts_empty.json"             # 讀得到但沒東西可判
        FACTS.write_text('{"by_code": {}}', encoding="utf-8")
    elif mode == "upstream_ok":
        # 陰性對照:12 檔分佈在今天/昨天各 6 檔,每天只有 1 檔缺基本面
        # ⇒ 缺項 17% < 門檻 50%、n=6 ≥ MIN_N ⇒ **應該不叫**。
        # 這條和 `upstream` 模式的差別:那個直接注入算好的 tuple,
        # 完全沒走到 upstream_status() 的剖析;這條走完整條路徑。
        today = datetime.date.today()
        bc = {}
        for i in range(12):
            d = (today - datetime.timedelta(days=i % 2)).isoformat()
            key = "checkup_dividend_history" if i < 2 else "checkup_crash_2020"
            bc["D%d" % i] = {"computed_at": d + "T09:00:00",
                             "skipped": [{"key": "%s__D%d" % (key, i)}]}
        FACTS = _DRILL_DIR / "facts_ok.json"
        FACTS.write_text(json.dumps({"by_code": bc}), encoding="utf-8")
    assert FACTS != PROD_FACTS, "沙箱沒生效:FACTS 還指著正式機"
    assert str(FACTS).startswith(str(_DRILL_DIR)), f"FACTS 不在沙箱內:{FACTS}"
    say(f"[DRILL] 沙箱 FACTS={FACTS}")
    say(f"[DRILL] 正式機 FACTS={PROD_FACTS}｜開跑指紋 {_PROD_FP}")


def _drill_teardown():
    """回 True/False = 隔離成立/被破;沒跑演習回 None。"""
    global FACTS
    if _DRILL_DIR is None:
        return None
    after = _fingerprint(PROD_FACTS)
    ok = (after == _PROD_FP)
    say(f"[DRILL] 正式機 FACTS 收尾指紋 {after} → "
        + ("未被動過 ✅" if ok else "🔴 被動過!演習汙染了正式機"))
    FACTS = PROD_FACTS                    # 還原,免得同 process 後續呼叫沿用沙箱
    assert FACTS == PROD_FACTS
    shutil.rmtree(_DRILL_DIR, ignore_errors=True)
    return ok


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
        if SELFTEST_MODE in DRILL_FACT_MODES:
            # 上游那三個模式要把種題那三條全部餵成健康,**唯一還會動的變數只剩上游**。
            # 日期必須是今天:用 `healthy`(08-30)會先被新鮮度那條攔下,
            # 陰性對照就變成「叫了,但不是為了我在測的那件事」—— 那不叫陰性對照。
            td = datetime.date.today().isoformat()
            return [{"date": td, "code": "N%d" % i, "n_new_topics": 1} for i in range(16)]
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
    if SELFTEST and SELFTEST_MODE in DRILL_PUSH_MODES:
        # 明確注入,讓這個演習**只**取決於它要測的那件事(推播失敗留痕),
        # 而不是搭別條判準的便車 —— 別條判準哪天被修好,這個演習就會靜靜地不再引爆。
        problems.append("🔴 演習:注入假異常以引爆 alert() 的推播失敗路徑(不碰真的 push)")
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
    # 🔴 三種來源分開,因為它們是三件不同的事,而舊版把後兩種壓成同一個空 list:
    #   ① 演習注入的斷料長相  ② 這輪演習不測上游  ③ 真的去讀事實庫(可能判不出來)
    # 壓成同一個空 list 的後果不是判錯,是**那一格從 log 上消失**,而消失沒有形狀。
    up, up_err, up_skip = [], None, None
    if SELFTEST and SELFTEST_MODE in ("upstream", "all"):
        up = [("2026-07-18", 0.93, 14), ("2026-07-19", 1.00, 13)]   # 真實斷料窗的長相
    elif SELFTEST and SELFTEST_MODE in ("err", "zero", "stale") + DRILL_PUSH_MODES:
        up_skip = "本次演習不測(這幾個模式不測上游)"
    else:
        up, up_err = upstream_status()

    if up_skip:
        stat += f"｜上游 {up_skip}"       # 明寫「沒測」,而不是讓這一格靜靜不見
    elif up_err:
        stat += "｜上游 🔴 判不出來"
        problems.append(
            f"🔴 上游狀態判不出來,**這不是「沒事」**:{up_err}"
            f" —— 事實庫是 17MB 單檔,讀不到就等於這道哨對上游斷料失明,"
            f"而失明的長相和健康的長相在舊版 log 上一模一樣(整段消失、照樣 exit 0)。"
            f"**先確認該檔存在且是完整 JSON**,再確認 05:50 那輪有沒有寫進去;"
            f"要復原看 snapshot_studio 的快照(2026-09-08 才納入清單,更早的沒有備份)。")
    else:
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
    # 沙箱在**入口**建立、在 finally 還原:main() 中途丟例外也不會把 FACTS 留在沙箱上。
    if SELFTEST and SELFTEST_MODE in DRILL_FACT_MODES:
        _drill_setup(SELFTEST_MODE)
    import watch_crosscheck
    _rc, _iso = 1, None          # main() 丟例外時的預設:例外不是「沒事」
    try:
        _rc = main()
    finally:
        _iso = _drill_teardown()
        # 收尾行放 finally:main() 中途丟例外時,已經吞掉的東西一樣要留得下來。
        swallow_epilogue()
        if _iso is False:
            say("[DRILL] 🔴 隔離失敗 → rc=9(演習結果不採信)")
            _rc = 9
        # 互查放在最後:**自己那行已經寫完了**才問「同伴最近一次該跑的時候有沒有留下行」。
        # 順序反過來會製造假告警競態;三個母體與已知邊界見 scripts/watch_crosscheck.py 的 docstring。
        # 🔴 互查也必須放 finally。原本它在 try/finally **之外** ⇒ main() 丟例外時
        # 控制流根本走不到那一行,互查整天不執行而且**沒有任何訊號**(09-10 獨立驗證 3-2)。
        # ⚠️ 更正一個錯誤的診斷:病不在「_rc 從沒被賦值」,在**控制流到不了那一行**。
        #    照「_rc 沒賦值」去修(在 try 前面給預設值)一個字都沒修到。
        try:
            _rc = watch_crosscheck.crosscheck_tail(_rc, "seeding", record, alert)
        except BaseException as _xe:
            # 不 re-raise:在 finally 裡 raise 會**取代** main() 原本那個例外,把根因換掉。
            # 但也絕不可以 pass —— 沉默偵測器沉默地壞掉正是它在治的病。
            print(f"[XCHK-BROKEN] 守望互查收尾自己爆了,今天沒有沉默偵測:{_xe!r}", file=sys.stderr)
            if _rc in (0, None):
                _rc = 4          # 4=互查機構自己壞了(≠同伴都正常)
    raise SystemExit(_rc)
