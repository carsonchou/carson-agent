# -*- coding: utf-8 -*-
"""quota_ceiling_watch.py — 配額天花板變化守望(基建線,2026-09-02)

為什麼存在:premises.md 第 3 條寫「核准可自驗:quota_meter 天花板變了就是核准」,
但沒有任何東西每天去看它——這支就是去看的那個。

設計約束(督導指令 + verify-ceiling-watch 驗證後修正):
  · 正向輸出:**每次跑都寫一行 log**,天花板沒變的日子也有——「沒輸出」因此永遠是異常。
  · log 先寫、print 後印(印壞了紀錄還在;cp950 炸點已被驗證員重現過)。
  · print 全程可失敗(pythonw 下 stdout=None),log 才是主要輸出通道。
  · assert_project() 回傳警告字串(不 raise),**要接住當警報**,不能默默比錯帳。
  · 比對直接用 effective_limit():它「忽略 floor」的 bug 已由 w9 修復(cefa9ba8,floor 只採
    撞牆日後的日子)。**不要在這裡再包 max(eff, 全期 floor)**——配額被調降時,舊高 floor 會把
    watch 值釘死在舊值,把 ⚠️ 下移遮成「無變化」,正是 cefa9ba8 避開的鏡像病。
  · 只讀 w9 的模組與帳本,不改它們;變化時推 ntfy(失敗不擋主流程)。

用法:python scripts/quota_ceiling_watch.py   (排程每天台北 15:20,配額日剛關帳後)
輸出:docs/ops/quota-ceiling-watch.log 追加一行 + 更新 .state.json + stdout(若有)
"""
import json, re, sys, datetime, pathlib, traceback

REPO = pathlib.Path(__file__).resolve().parent.parent
LOG   = REPO / "docs" / "ops" / "quota-ceiling-watch.log"
STATE = REPO / "docs" / "ops" / "quota-ceiling-watch.state.json"
sys.path.insert(0, str(REPO / "youtube_channel" / "scripts"))

# --selftest:演習模式。教訓(2026-09-02):驗證員手改 state 模擬提額,兩行 🎉 落在正式 log,
# 和真事件一模一樣——假證據落在自己指定的權威來源裡,比沒有守望更糟。
# 演習從此只准走這裡:每行帶 [DRILL] 前綴、用獨立 state 檔、永不推播。真實路徑永遠不產生 [DRILL]。
SELFTEST_MODE = next((a.split("=", 1)[1] if "=" in a else "up"
                      for a in sys.argv if a.startswith("--selftest")), None)  # None|"up"|"down"
SELFTEST = SELFTEST_MODE is not None
if SELFTEST:
    STATE = REPO / "docs" / "ops" / "quota-ceiling-watch.state.selftest.json"

try:  # 排程/重導向下編碼不保證 utf-8;stdout 可能是 None(pythonw)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def say(text: str) -> None:
    """print 的可失敗版:log 是主通道,stdout 只是順帶。

    ⚠️ 這個 except **刻意不留痕**,它是本輪的陰性對照:排程用 pythonw ⇒ `sys.stdout is None`
    ⇒ `print(t)` 是**靜默 no-op 不丟例外**(實測),這條 except 在排程上不會被走到;
    真要留痕也只會變成每輪都叫的雜訊。同理上面 `sys.stdout.reconfigure` 那個 except。
    **判準:留痕的對象是「本來應該成功的事」,不是「本來就預期失敗的事」。**"""
    try:
        print(text)
    except Exception:
        pass


# ── 吞掉但留痕(2026-09-08)────────────────────────────────────────────────
# 🔴 缺陷不是「吞」(記 log 失敗不該弄垮判準,那是對的),是**吞掉之後沒辦法知道它在吞**。
# ⚠️ 不可以照抄 `auditability_coverage` 那個「印到 stderr」的範本:那支是 local_cron 的 job
# (stderr 落 `logs/job_stderr.log`),而本支是 **Windows 排程工作、`pythonw.exe`、無任何重導向**。
# 2026-09-08 實測(detached 無 console):`sys.stdout`/`sys.stderr` **都是 None**;
# `print(msg, file=sys.stderr)` → **靜默 no-op**;`sys.stderr.write` → **AttributeError**;寫檔 → ✅。
# ⇒ 照抄範本會在唯一重要的那個環境裡完全靜默,而在互動終端測起來是好的 —— 那正是本輪要治的病。
# **主通道是 log 檔,stderr 只是互動/local_cron 下的第二條路。**
# (本檔的 `production_suffix` 早就示範了對的做法:讀不到就把「🔴 產量/庫存讀不到」綴進 log 行。)
_SWALLOWED = []


def swallowed(what: str, e: BaseException = None) -> str:
    """吞掉但留痕。判準(exit code 與上面的輸出)完全不受影響,只是不再靜默。"""
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
        pass
    try:
        if sys.stderr is not None:
            print("[warn] " + line, file=sys.stderr)
    except Exception:
        pass
    return msg


def record(line: str) -> None:
    if SELFTEST:
        line = "[DRILL] " + line
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    say(line)


PROD_CAP_HINT = 14   # 節流建議上限=可發布量÷良率(docs/inventory-throttle-brief-2026-09-03.md;w9 已同意方向)


def production_suffix(now: datetime.datetime) -> str:
    """當日/昨日產量 + 庫存,追加在守望行尾。節流「同意了」不等於「行為變了」
    (memory yt-autoloop-shorts-death-spiral)——這裡讓行為每天自己說話,沒事也印。
    口徑=ops_log 全日「渲染完成」行數(w9 採納的口徑)+ 上架部門自報「剩庫存」。"""
    try:
        opslog = REPO / "youtube_channel" / "STUDIO" / "ops_log.txt"
        text = opslog.read_text("utf-8", errors="replace")
        today, yest = now.strftime("%m-%d"), (now - datetime.timedelta(days=1)).strftime("%m-%d")
        cnt = lambda d: sum(1 for ln in text.splitlines()
                            if ln.startswith(f"[{d} ") and "渲染完成" in ln)
        # 新鮮度:數字旁沒有它的更新時刻,就分不出「沒變」和「沒在動」(09-03 教訓,
        # 人工挖了五分鐘才排除計數器凍結)。渲染取最後一行渲染完成的時戳、庫存取最後
        # 一行上架部門的時戳、log 本身取 mtime——三個來源各自標。
        last_of = lambda key: next((ln[1:15] for ln in reversed(text.splitlines()) if key in ln), "無")
        log_mt = datetime.datetime.fromtimestamp(opslog.stat().st_mtime).strftime("%m-%d %H:%M")
        inv = re.findall(r"剩庫存(\d+)", text)
        inv_s = f"{inv[-1]} 支(產線自報@{last_of('上架部門')})" if inv else "讀不到"
        return (f"｜長片渲染 昨{cnt(yest)}/今{cnt(today)}次(含重渲;末次@{last_of('渲染完成')},"
                f"log 活至 {log_mt};毛產出口徑見 throttle-brief)/建議上限 {PROD_CAP_HINT}｜庫存 {inv_s}")
    except Exception as e:                       # 讀不到也要說(dispatch §6 第零種)
        return f"｜🔴 產量/庫存讀不到:{e!r}"


def alert(title: str, body: str) -> None:
    if SELFTEST:
        say("[DRILL] 演習不推播")
        return
    # 🔴 推播失敗原本**兩條路都到不了讀者**:①拋例外那條走 `say(...)`,而 say 在排程環境是
    # 靜默 no-op ⇒ 告警送不出去這件事本身也送不出去(`WATCHDOG.md` 09-06 記過,一直開著);
    # ②**不拋例外那條** —— `push()` 都沒設定/403/5xx 回 False,而這裡沒看回傳值 ⇒ 安靜當成功。
    # 這一支尤其致命:天花板變化**只在 changed 的那一次推播**,漏掉就是漏掉,沒有第二次。
    try:
        from notify import push
        if not push(title, body, tag="chart_with_upwards_trend"):
            swallowed("ntfy 推播回報未送出(push() 回 False:topic 沒設定,或所有後端都失敗)"
                      " —— 手機不會響,而天花板變化只推這一次,log 這行是唯一痕跡")
    except Exception as e:
        swallowed("ntfy 推播丟例外 —— 手機不會響,而天花板變化只推這一次", e)


def main() -> int:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        import quota_meter as qm
        warn = qm.assert_project()          # 回傳字串不 raise:非空=帳本可能換了專案
        if warn:
            line = f"[{now}] 🔴 專案不一致,拒絕比對(比錯帳比沒比更糟):{warn}"
            record(line); alert("配額守望:專案不一致", line)
            return 1
        eff = qm.effective_limit()
        floor, ceil = qm.observed()
        cur = eff                           # 見檔頭:cefa9ba8 後直接信 effective_limit,別再包 max
        try:                                # 帳本日數:用來把「帳本遺失/重置」從「真調降」裡分出來
            days_n = len(json.loads(pathlib.Path(qm.STATE).read_text("utf-8")).get("days") or {})
        except Exception as e:
            # days_n=None 下游只在「天花板下移」那一支講得出來(:141),其餘分支完全不提它
            # ⇒ 帳本讀不到這件事,在沒有下移的日子是靜默的。這裡補上那條缺的路。
            days_n = None
            swallowed("quota_meter 帳本讀不到,days 筆數無法用來分辨「帳本遺失」與「真調降」", e)
    except Exception as e:
        record(f"[{now}] 🔴 讀不到 quota_meter:{e!r} —— 這本身是警報,不是「沒事」")
        say(traceback.format_exc())
        return 1

    # 🔴 失敗形態(2026-09-08 修,本輪三支裡最嚴重的一個):
    # 這個 `except: pass` 原本讓「state 檔壞掉」和「第一次跑」變成同一件事 ——
    # prev={} → base=None → 走「基準建立」分支 → **changed=False → 不推播** →
    # 然後把當前值寫回 state。所以:**天花板在那一天變了、而 state 剛好壞了,
    # 那次變化永遠不會被報告,下一輪起還以新值為基準 ⇒ 證據就此消失,而且不可回溯。**
    # log 上留下的是「基準建立」—— 一句第一次跑本來就該出現的、看起來完全正常的話。
    # ⚠️ 而這兩件事**分得開**:`STATE.exists()` 為真但解析失敗 = 壞掉,不是第一次。
    prev, prev_broken = {}, None
    if STATE.exists():
        try:
            prev = json.loads(STATE.read_text("utf-8"))
        except Exception as e:
            prev_broken = swallowed("state 檔存在但讀不掉 ⇒ 基準遺失(這不是第一次跑)", e)
    base = prev.get("effective")
    if SELFTEST:
        if SELFTEST_MODE == "down":     # 演習「下移+days 驟減」:走 ⚠️+帳本遺失標註路徑
            base = cur + 1234
            prev = {"days_n": (days_n or 0) + 40}
        else:                           # 演習「上移」:走 🎉 路徑
            base = cur - 1234

    if base is None and prev_broken:
        verdict = (f"🔴 **基準被迫重建,這不是第一次跑**:{prev_broken}。本輪把 watch={cur:,} 當成新基準"
                   f"收下(effective={eff:,}, floor={floor}, ceiling={ceil})—— 如果天花板今天剛好變了,"
                   f"**那次變化不會被報告,而且下一輪起以新值為基準 ⇒ 證據不可回溯地消失**。"
                   f"先看 {STATE.name} 是不是被截斷/寫壞(它就在 docs/ops/),再決定要不要把舊基準手動補回去。")
        changed = True          # ← 要推播:這是唯一一次講得出「基準是怎麼沒的」的機會
    elif base is None:
        verdict = f"基準建立:watch={cur:,}(effective={eff:,}, floor={floor}, ceiling={ceil})"
        changed = False
    elif cur > base:
        verdict = (f"🎉 天花板上移 {base:,} → {cur:,} —— 依 premises.md 第 3 條,"
                   f"這就是提額核准的證據(effective={eff:,}, floor={floor}, ceiling={ceil})")
        changed = True
    elif cur < base:
        verdict = f"⚠️ 天花板下移 {base:,} → {cur:,} —— 配額被調降?查 quota_meter 帳本"
        days_prev = prev.get("days_n")
        if days_n is not None and days_prev and days_n < days_prev - 5:
            verdict += f"(🔴 但 days 筆數 {days_prev}→{days_n} 驟減:更像帳本遺失/重置,不是真調降——先查帳本檔再信這個 ⚠️)"
        elif days_n is None:
            verdict += "(🔴 days 筆數讀不到:帳本檔可能遺失/壞損——先查帳本檔再信這個 ⚠️)"
        changed = True
    else:
        verdict = (f"無變化:watch={cur:,}(effective={eff:,}, floor={floor}, ceiling={ceil});"
                   f"提額若核准,產線成功花超舊牆當天 effective_limit 會上移(cefa9ba8 後含撞牆日後 floor)")
        changed = False

    record(f"[{now}] {verdict}{production_suffix(datetime.datetime.now())}")
    STATE.write_text(json.dumps({"effective": cur, "raw_effective": eff, "floor": floor,
                                 "ceiling": ceil, "days_n": days_n,
                                 "checked_at": now}, ensure_ascii=False), "utf-8")
    if changed:
        alert("配額天花板變化", verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
