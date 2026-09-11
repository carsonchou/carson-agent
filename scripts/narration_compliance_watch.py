# -*- coding: utf-8 -*-
"""narration_compliance_watch.py — 個股體檢旁白的「規則遵守率」守望(主頻道線,2026-09-05)

## 為什麼存在
2026-09-05 兩條新規則上線,而兩條都是「寫在模板裡、違反時不產生輸出」:
  · 收束句(`_checkup_summary_line`,確定性)——不合規只會是「沒產出」,沒有人在數覆蓋率
  · 業務介紹(`TW_STOCK_CHECKUP_RULES` ①b,純 prompt 層)——LLM 不照做完全靜默

實據:7 月有一條旁白規則的合規率是 **4%,持續整整一個月零訊號**
(8 月 54% / 9 月 89% / 最近 30 支 93%)。

🔴 **所以這支問的是「這個規則現在的遵守率是多少」,不是「有沒有出錯」。**
那兩個問句差很遠 —— 後者在 4% 的那個月裡**完全不會叫**,因為每一支片都成功產出了。

## 判準
只數**規則上線之後**產出的旁白(`RULE_DATE` 起),因為上線前的樣本必然不合規,
混進去會把分母稀釋成一個永遠慢慢爬升的數字 —— 那正是量測窗混進上線期的老坑。

| 規則 | 判準 | 地板 |
|---|---|---|
| 收束句 | 含「一句話收束今天的體檢」 | 50%(資料齊備率上限約 82%,留餘裕) |
| 業務介紹 | 含業務描述句(見 `_BIZ_PAT`) | 50%(上線前基線是 **3/20 = 15%**) |

樣本數不足(< `MIN_N`)時**只報數字不判定** —— n 小的時候比例會亂跳,
在那之上設門檻只會製造假警報。

## 正向輸出
每次跑都寫一行 log,合規的日子也寫 ⇒「沒輸出」永遠是異常。

## 出口碼(2026-09-10 拆開)
🔴 **在此之前 rc=1 同時代表「產線違規」和「哨自己壞了」,兩者分不出來。**
`rc=1` 於是變成一個沒有資訊的訊號:它可能是哨在盡責,也可能是哨瞎了。

| rc | 意思 | 誰該被修 |
|---|---|---|
| 0 | 合規,或樣本不足只報不判 | — |
| 1 | **產線違規**:遵守率低於地板 | 產線(主頻道線) |
| 2 | **哨自檢失敗**:判準認不出自己的範例句、或讀不到旁白樣本 | 這支哨 |
| 3 | **互查發現別支哨沉默**(見 `scripts/watch_crosscheck.py`) | 排程/那支哨 |

⚠️ rc=2 時**不會**有遵守率數字 —— 那正是重點:算不出來就不要吐一個安靜的假數字。

## 演習
`--selftest=summary|biz|both`:**每一條判準各自要有引爆輸入**。
(教訓來自同日的 `seeding_watch`:第一版只有一種 fixture,它引爆了一條而另一條
完全沒被走到,而沒被走到的那條才是覆蓋歷史真實失效的那條。)

用法:
  python scripts/narration_compliance_watch.py
  python scripts/narration_compliance_watch.py --selftest=biz
"""
import sys, re, datetime, pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = REPO / "youtube_channel" / "output"
LOG = REPO / "docs" / "ops" / "narration-compliance-watch.log"
sys.path.insert(0, str(REPO / "youtube_channel" / "scripts"))
sys.path.insert(0, str(REPO / "scripts"))   # 讓 import watch_crosscheck 不看「是誰啟動的」
import watch_crosscheck   # 互查在模組層 import:缺檔/壞檔在**啟動時**大聲失敗,不是在收尾時靜靜跳過

# 🔴 上線日設 09-06 不是 09-05:兩條規則是 09-05 **深夜** commit 的,
# 而 09-05 白天已經產了 11 支舊規則的片。設成 09-05 會把上線前的產出算進分母,
# 第一次跑就吐 0% 紅燈 —— 那正是本檔 docstring 自己寫的「量測窗混進上線期」,
# 而我在同一個檔案裡踩了一次。第一個完整的新規則批次是 09-06 06:07。
RULE_DATE = datetime.date(2026, 9, 6)
MIN_N = 8                               # 少於這個數只報不判
FLOOR_SUMMARY = 0.50
FLOOR_BIZ = 0.50

# ─────────────────────────────────────────────────────────────────────
# 🔴 2026-09-08:判準改成**從產線那一份長出來**,不再另抄一份。
#
# 為什麼改:盤點實測抓到這道哨已經在漂,而且是兩個具體缺口 ——
#   ① `_SUM_PAT` 原本寫死 `("一句話收束今天的體檢",)` **一種**措辭,
#      而產線 `produce_batch.py:1815` 認可**五種**(一句話收束/總結/整體而言/綜合來看/結論是)。
#      ⇒ 旁白自然帶出「總結…」的收尾時,**產線視為合規、本哨記成不合規**
#      (09-06 後 n=26 實測:sum_hit=10、**alt_only=1 被誤記**、neither=15)。
#   ② `_BIZ_PAT` 五條正則,**連 `TW_STOCK_CHECKUP_RULES` ①b 自己給的官方範例句
#      「台星科做積體電路測試服務」都零命中** —— 判準比它要執行的規則還窄。
#
# 修法(原則來自 prompt 洩漏閘門那道的修法:**判準要從被監控物身上長出來**):
#   · 收束句 → `from produce_batch import CHECKUP_SUMMARY_MARKERS`,誰改產線清單哨自動跟著變
#   · 業務介紹 → 規則是純 prompt 文字沒有可 import 的清單,所以改成**把規則自己給的範例句
#     抽出來當內建回歸語料**;檢查器對不上自己要執行的規則的範例 ⇒ **fail-closed 不報數字**。
#     (同 prompt 洩漏閘門用 31 支真實洩漏案例當語料、抓不到就 fail-closed 的機制。)
# ⚠️ import 失敗**不可以**靜默退回舊的抄本 —— 那正是漂的成因。失敗要大聲。
# ─────────────────────────────────────────────────────────────────────
_IMPORT_ERR = ""
try:
    from produce_batch import CHECKUP_SUMMARY_MARKERS as _SUM_PAT  # 單一真相來源
    from produce_batch import TW_STOCK_CHECKUP_RULES as _RULES_TEXT
except Exception as _e:  # noqa: BLE001
    _SUM_PAT, _RULES_TEXT, _IMPORT_ERR = (), "", f"{type(_e).__name__}: {_e}"


def _rule_examples() -> tuple:
    """從 `TW_STOCK_CHECKUP_RULES` ①b 的「例:」那行抽出官方範例句。

    **這就是回歸語料,而且它跟著規則走** —— 規則改了範例句、語料自動跟著改,
    不需要任何人記得同步。抽不到就回空,由 `_biz_selfcheck()` 判成 fail-closed。"""
    if not _RULES_TEXT:
        return ()
    m = re.search(r"例[:：]\s*((?:「[^」]+」\s*)+)", _RULES_TEXT)
    return tuple(re.findall(r"「([^」]+)」", m.group(1))) if m else ()


_BIZ_PAT = (r"這家公司主要[在從]?[^。]{6,}。", r"主要業務[是為]?[^。]{6,}。",
            r"靠(?:販售|賣|提供)[^。]{4,}(?:賺錢|營收)", r"從事[^。]{6,}(?:業務|生產|製造|研發)",
            # 🔴 2026-09-08 補:原本五條漏掉「做…服務/測試/設備」這個句型,
            # 導致規則自己的範例「台星科做積體電路測試服務」零命中。
            r"提供[^。]{4,}(?:服務|解決方案|設備|系統|產品)",
            r"[做搞][^。]{4,}(?:服務|測試|設備|系統|製造|代工|產品)",
            r"(?:生產|製造|銷售|研發)[^。]{4,}(?:產品|元件|設備|材料|系統)")


def _biz_selfcheck() -> tuple:
    """規則自己給的範例句,本檢查器抓不抓得到?回 (ok, 訊息)。

    🔴 這是這道哨的**陽性對照**:一個連自己要執行的規則的範例都認不出來的檢查器,
    算出來的「遵守率」是沒有意義的數字,**不可以拿去跟地板比**。"""
    if _IMPORT_ERR:
        return False, f"無法 import 產線常數({_IMPORT_ERR})—— 判準來源不可用"
    if not _SUM_PAT:
        return False, "產線收束句清單為空"
    ex = _rule_examples()
    if not ex:
        return False, "抽不到規則裡的官方範例句(規則格式可能改了)"
    miss = [s for s in ex if not any(re.search(p, s + "。") for p in _BIZ_PAT)]
    if miss:
        return False, f"規則自己的範例句有 {len(miss)}/{len(ex)} 條抓不到:{miss}"
    return True, f"陽性對照通過({len(ex)} 條官方範例全部命中);收束句認可 {len(_SUM_PAT)} 種措辭"

SELFTEST_MODE = next((a.split("=", 1)[1] if "=" in a else "both"
                      for a in sys.argv if a.startswith("--selftest")), None)
SELFTEST = SELFTEST_MODE is not None
# 推播失敗的演習模式(2026-09-09):留痕的陽性對照,兩條失敗路徑各一個。
DRILL_PUSH_MODES = ("pushfail", "pushraise")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def say(t):
    # ⚠️ 這個 except **刻意不留痕**,它是本輪的陰性對照:排程用 pythonw ⇒ `sys.stdout is None`
    # ⇒ `print(t)` 是**靜默 no-op 不丟例外**(實測),這條 except 在排程上不會被走到;
    # 真要留痕也只會變成每輪都叫的雜訊。同理上面 `sys.stdout.reconfigure` 那個 except。
    # **判準:留痕的對象是「本來應該成功的事」,不是「本來就預期失敗的事」。**
    try:
        print(t)
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
_SWALLOWED = []


def swallowed(what, e=None):
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


# 🔴 2026-09-09(驗證 §4.1):`_SWALLOWED` 原本是唯寫的 —— 判決行永遠不會說「這輪吞了東西」,
# 而推播失敗那條還排在判決行**後面** ⇒ 只看最後一行或 grep 判決行的人拿到「✅ 合規」。
# 兩條都補:①判決行帶件數 ②收尾再補一行。**exit code 不動**(它是排程在讀的穩定基準)。
# 這三份是刻意的複製,理由見 seeding_watch.swallowed() 的 docstring 與 WATCHDOG.md:116-127。
def swallow_suffix():
    if not _SWALLOWED:
        return ""
    return f"｜⚠️ 本輪吞掉 {len(_SWALLOWED)} 件:" + "; ".join(_SWALLOWED)[:200]


def swallow_epilogue():
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
    line += swallow_suffix()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    say(line)


def _push_and_trace(pusher, title, body):
    """推播 + 兩條失敗路徑的留痕。演習與正式**走同一份程式碼**(pusher 當參數傳)。"""
    try:
        if not pusher(title, body, tag="clipboard"):
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
        # 🔴 2026-09-09(驗證 §4.2):原本演習在碰 push 之前就 return ⇒ 留痕零常駐回歸。
        # 真 push 只在下面非 SELFTEST 分支才 import ⇒ 演習路徑上它不存在(禁令放入口)。
        if SELFTEST_MODE in DRILL_PUSH_MODES:
            _push_and_trace(_drill_push_false if SELFTEST_MODE == "pushfail"
                            else _drill_push_raise, title, body)
            return
        say("[DRILL] 演習不推播")
        return
    # 🔴 推播失敗原本**兩條路都到不了讀者**:①拋例外那條走 `say(...)`,而 say 在排程環境是
    # 靜默 no-op ⇒ 告警送不出去這件事本身也送不出去(`WATCHDOG.md` 09-06 記過,一直開著);
    # ②**不拋例外那條** —— `push()` 都沒設定/403/5xx 回 False,而這裡沒看回傳值 ⇒ 安靜當成功。
    try:
        from notify import push
    except Exception as e:
        swallowed("ntfy 匯入失敗 —— 手機不會響", e)
        return
    _push_and_trace(push, title, body)


def samples():
    if SELFTEST:
        good_sum = "……前面講完。一句話收束今天的體檢，它屬於電機機械，過去約15年。"
        good_biz = "……這家公司主要在提供半導體、面板產業的製程設備與解決方案。"
        plain = "……你知道嗎？這檔股票十五年報酬只有百分之七十二。"
        if SELFTEST_MODE == "summary":      # 只有收束句掉下去
            return [good_biz + plain] * 10 + [good_biz + good_sum] * 2, 0
        if SELFTEST_MODE == "biz":          # 只有業務句掉下去
            return [good_sum + plain] * 10 + [good_sum + good_biz] * 2, 0
        return [plain] * 12, 0              # 兩條都掉
    # 🔴 失敗形態(2026-09-08 修):這個 `except: continue` 原本把讀不掉的旁白檔靜靜丟掉,
    # 而丟掉的後果是 **n 變小** —— n 掉到 MIN_N 以下時,main() 會寫
    # 「⏳ 樣本不足只報不判」並 **return 0**。那是一句**看起來完全正常的話**。
    # ⇒ 這道哨可以在「每天一個檔都讀不到」的狀態下無限期回報樣本不足,
    #   而它和「今天真的還沒產片」在 log 上長得一模一樣。
    #   權限/編碼/磁碟問題會偽裝成「產線今天沒出片」,而後者不是這道哨該回報的事。
    out, unread = [], []
    for f in OUT.glob("L_個股體檢*.voice.txt"):
        try:
            if datetime.date.fromtimestamp(f.stat().st_mtime) < RULE_DATE:
                continue
            out.append(f.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:  # noqa: BLE001
            unread.append(f"{f.name}({type(e).__name__})")
            continue
    if unread:
        swallowed(f"讀不掉 {len(unread)} 支旁白,它們沒進樣本(n 因此變小,可能表現成「樣本不足」):"
                  + "、".join(unread[:3]) + ("…" if len(unread) > 3 else ""))
    return out, len(unread)


def main():
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # 🔴 陽性對照先跑,而且 **fail-closed**:判準本身認不出規則自己的範例句時,
    # 算出來的「遵守率」沒有意義 —— 那正是 08-25~09-03 那道 prompt 洩漏閘門的病
    # (瞎了三週、rc=0、log 一片乾淨)。這裡寧可吵也不要吐一個安靜的假數字。
    ok, msg = _biz_selfcheck()
    if not ok:
        line = f"[{now}] 🔴 判準自檢失敗,本輪不報遵守率(這不是「合規」):{msg}"
        record(line); alert("旁白合規守望:判準自檢失敗", line)
        return 2                      # 2 = 哨自檢失敗(不是產線違規)

    try:
        texts, n_unread = samples()
    except Exception as e:
        line = f"[{now}] 🔴 讀不到旁白,無法判斷(這不是「合規」):{e!r}"
        record(line); alert("旁白合規守望:讀不到樣本", line)
        return 2                      # 2 = 哨自己壞了(讀不到樣本 ≠ 產線違規)

    n = len(texts)
    n_sum = sum(1 for t in texts if any(k in t for k in _SUM_PAT))
    n_biz = sum(1 for t in texts if any(re.search(p, t) for p in _BIZ_PAT))
    r_sum = n_sum / n if n else 0.0
    r_biz = n_biz / n if n else 0.0
    # 「讀不掉 N 支」一律印,連 0 也印 —— 這一格消失或是非零,都要看得出來。
    # 理由同 seeding_watch 09-08 那個修法:**一格從 log 上靜靜不見,比一個壞數字更難發現。**
    stat = (f"{RULE_DATE} 起產出 {n} 支(讀不掉 {n_unread} 支)｜收束句 {n_sum}/{n}={r_sum:.0%}"
            f"(地板 {FLOOR_SUMMARY:.0%})｜業務介紹 {n_biz}/{n}={r_biz:.0%}(地板 {FLOOR_BIZ:.0%})")

    if n < MIN_N:
        # 🔴 這句「樣本不足」正是讀檔失敗會偽裝成的那句話,所以它必須自己講清楚可不可信。
        why = ("" if not n_unread else
               f" 🔴 但同一輪有 {n_unread} 支讀不掉 —— **「樣本不足」這句話這一輪不可信**,"
               f"先查那幾支檔案再信這個 ⏳(讀不掉的原因見上一行「吞掉但留痕」)")
        record(f"[{now}] ⏳ 樣本不足只報不判(n={n} < {MIN_N}){why}｜{stat}")
        return 0

    bad = []
    if r_sum < FLOOR_SUMMARY:
        bad.append(f"🔴 收束句遵守率 {r_sum:.0%} 低於地板 —— 它是確定性程式碼,掉下去代表"
                   f"`_checkup_summary_line` 拿不到事實或沒被呼叫")
    if r_biz < FLOOR_BIZ:
        bad.append(f"🔴 業務介紹遵守率 {r_biz:.0%} 低於地板 —— 那條規則只寫在 prompt 層,"
                   f"上線前基線是 3/20=15%,掉回那附近代表模型沒在照做")
    if bad:
        line = f"[{now}] {stat}｜" + "｜".join(bad)
        record(line); alert("旁白合規守望:遵守率掉了", line)
        return 1                      # 1 = 產線違規(哨是好的,它正在做它的工作)

    # 正向輸出把陽性對照的結果也帶上:「它今天有沒有能力叫」本身要看得見,
    # 不然「沒叫」與「叫不出來」在 log 上又長得一樣。
    record(f"[{now}] ✅ 合規｜{stat}｜{msg}")
    return 0


def xchk_broken(what):
    """互查收尾自己爆了 —— **最後一道**留痕。主通道是 log 檔,不是 stderr。

    `what` 可以是例外(從 `__main__` 的 `except BaseException` 來)或字串
    (從 `watch_crosscheck.crosscheck_tail` 的 `on_broken` 來)。

    🔴 2026-09-11 獨立驗證(新-1)推翻前一版。前一版是這一行::

            print(f"[XCHK-BROKEN] ...{_xe!r}", file=sys.stderr)

    而三支任務的 Action 都是 `pythonw.exe`,**兩種環境都到不了任何人眼前**:
      · 排程啟動(無 console、無繼承 handle)⇒ `sys.stderr is None`
        ⇒ `print(file=None)` 退回 `sys.stdout`(也是 None)⇒ **靜默 no-op**。
        「必須出聲」在唯一重要的那個環境裡變成不出聲。
      · 有繼承 handle 時 ⇒ 實測 `sys.stderr.encoding == 'cp950'`,而本 repo 的例外
        訊息到處帶 🔴 ⇒ `UnicodeEncodeError`。它拋在 `finally` 的 except 區塊裡
        ⇒ **取代 main() 原本那個例外,把根因換掉** —— 正是那行上面的註解說要避免的
        事,由那行自己造成。
    ⚠️ 本檔上面 100 行出頭就寫著「print 到 stderr 在這個環境靜默」,而我照樣寫了那行。
       ⇒ 教訓不是「要小心」,是**留痕的主通道一律是 log 檔**;stderr 只是互動下的
         第二條路,而且它自己編碼失敗時不准影響任何事。

    🔴 2026-09-11 第四輪獨立驗證【2/5】再推翻一次。前一版是「寫完就算數,失敗退
       stderr」,兩個洞:
         · `write()` 沒拋例外**不等於**那行在磁碟上 ⇒ 沒有回讀就沒有證據
           (memory `only-what-lands-on-disk-exists` 的機械版)。
         · 🔴 更重的那個:它和**剛剛失敗的那條 log 通道走同一個失敗點**。
           `watch_crosscheck` 爆掉的原因如果是「`docs/ops/` 這個目錄寫不進去」,
           那本函式寫同一個目錄也寫不進去,然後退到 stderr —— 而排程下
           `sys.stderr is None` ⇒ **整條最後防線靜默**,而且前一版那句
           `except BaseException: pass` 把這件事的唯一訊號也吃掉了。
       ⇒ 現在是三條路,**每條都寫完回讀**,回讀不到才換下一條:
           ① `LOG`(主通道)② `LOG.with_suffix(".broken.log")`(同目錄,治「主 log
           被鎖住 / 被寫壞」)③ `%TEMP%`(**換一個磁碟區**,治「`docs/ops/` 整個寫不進去」)
         退到備援時,把「前面哪幾條路失敗、錯誤是什麼」補寫進**活著的那一份**,
         否則下次有人只看到備援檔,不知道主通道為什麼沒有這一行。
         stderr 降成**附帶**通道:它不算留痕,失敗與否都不影響判定。
    ⚠️ 仍然治不了的,照實寫:整台機器磁碟滿、程序被 `kill -9`、或本行之前就當掉。
       那些要靠**帶外觀察者**(`CarsonQuant-UptimeMonitor`,目前 `TARGETS = []`
       ⇒ 還沒接上),不是靠這裡。本函式只保證「這支程序還活著而且 CPU 還在跑」時留得下痕。
    ⚠️ 回讀讀到的可能是 OS 快取而不是碟片(沒有 `fsync`)⇒ 它排除的是「路徑不可寫 /
       write 靜靜半途而廢」,不排除「寫完後斷電」。這是刻意的取捨:`fsync` 在最後一道
       防線裡多一個會拋的系統呼叫,而它擋的那個情境本來就得靠帶外觀察者。

    🔴 這裡**不准呼叫 `record()`**:`record()` 會呼叫 `watch_crosscheck.manual_prefix()`,
       而本函式觸發的前提就是 `watch_crosscheck` 那一側剛剛爆掉。最後一道防線不能
       依賴剛倒的那根柱子。
    🔴 也**不准抽成三支共用的模組**,理由同 `swallowed()`:它存在的意義就是在共用的
       東西壞掉時還活著。代價是改一次要改三份,這是已經權衡過的取捨。
    """
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    detail = repr(what) if isinstance(what, BaseException) else str(what)
    # 🔴 `_uniq`:本次呼叫唯一的識別,**放在行尾**,而且下面的回讀比對的是它、不是整行。
    #    2026-09-11 第五輪獨立驗證 (a-1) 抓到的:原本寫 `if line not in tail`,
    #    而 `line` 在**跨哨之間可能逐字相同** —— `stamp` 只到分鐘,而
    #    `detail = repr(what)`,`OSError.args` 只有 `(errno, strerror)`、**不含檔名**
    #    ⇒ 三支哨同一分鐘退到第三條路時(`%TEMP%` 那個檔名是三支**共用**的寫死字串),
    #    A 寫成功就足以讓 B 的回讀通過,而 B 自己那行從沒落地。
    #    ⇒ 原本的回讀量到的是「**這個字串**在檔案裡」,不是「**我寫的那行**在檔案裡」。
    #    ⚠️ 放行尾不是隨便放,它一次買到兩件事:
    #       · `detail` 可能很長,只有行尾的識別才留得在回讀的 64 KB 尾巴裡;
    #       · 看得到行尾 ⇒ 整行寫完了 ⇒ 順便抓得到「write 寫到一半靜靜斷掉」。
    try:
        import os as _os     # 三支哨不是每支都在模組層 import os,這裡就地拿(同 `_tf`)
        _pid = str(_os.getpid())
    except BaseException:
        _pid = "?"           # 拿不到就少一個維度;微秒仍然讓它幾乎不可能撞
    # (單行不是排版潔癖:回歸腳本的突變列要拿這個**字面**當目標,跨行的字串比對很脆。)
    _uniq = "#" + LOG.stem + ":" + _pid + ":" + datetime.datetime.now().strftime("%H%M%S.%f")
    # 🔴 `[XCHK] ` 這個字面前綴是**承重的**,不是裝飾(2026-09-11 兩名獨立驗證者各自抓到,
    #    其中一名跑了帶陰性對照的語料表):
    #    沒有它,這一行以 `[` + 時間戳開頭 ⇒ 命中 `watch_crosscheck.py:117` 的 `_TS`、
    #    又躲過 `:136` 的 `_SKIP_PREFIXES` ⇒ **被同伴當成今天的一筆排程讀數**。
    #    而本函式會觸發的前提正是「今天的 log 裡沒有真讀數」⇒ 同伴看到「今天有讀數」
    #    因此**閉嘴**,當天的沉默偵測整個失效。這是我 2026-09-11 `6aadb844` 自己種進去的。
    #    ⚠️ 演習**結構上**測不到這個形狀:`SELFTEST` 會加 `[DRILL] `,那本來就在
    #       `_SKIP_PREFIXES` 裡 ⇒ drill 路徑永遠不可能重現產線那一行的長相。
    #    ⚠️ 不准 `import watch_crosscheck` 去取 `XCHK_PREFIX`(見本函式 docstring:
    #       最後一道防線不能依賴剛倒的那根柱子)⇒ 這裡寫死字面,
    #       由 `watch_crosscheck_regression.py` 斷言這個字面 == 那個常數。
    line = ("[XCHK] " + ("[DRILL] " if SELFTEST else "")
            + f"[{stamp}] 🔴 [XCHK-BROKEN] 守望互查收尾自己爆了,"
              f"**今天沒有沉默偵測**(這不是「同伴都正常」):{detail} {_uniq}")

    def _land(path):
        """寫一行,然後**讀回來確認它在裡面**;讀不到就拋,讓上面換下一條路。

        回讀只讀尾巴 64 KB(位元組層 seek)⇒ 成本有界,log 長到幾百 MB 也不會爆記憶體;
        用 `errors="replace"` 解碼,因為切在多位元組字元中間是正常的,那不是失敗。

        🔴 比對的是行尾的 `_uniq`,**不是整行**(理由見上面 `_uniq` 那段註解:
           整行比對會被別支哨逐字相同的那一行餵成假陽性)。
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + chr(10))   # 不用反斜線字面:heredoc 會吃掉一層(memory heredoc-backslash-escaping-trap)
        with path.open("rb") as f:    # 另開一次 ⇒ 上面那個 with 關檔時已 flush
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 65536))
            tail = f.read().decode("utf-8", "replace")
        if _uniq not in tail:
            raise IOError("寫完回讀找不到自己那行:" + str(path))
        return path

    cands = [LOG, LOG.with_suffix(".broken.log")]
    try:
        import tempfile as _tf   # 三支哨不是每支都在模組層 import tempfile,這裡就地拿
        cands.append(pathlib.Path(_tf.gettempdir()) / "carson-watch-xchk-broken.log")
    except BaseException:
        pass    # 連 %TEMP% 都問不出來就少一條路,不影響前兩條

    landed, failed = None, []
    for cand in cands:
        try:
            landed = _land(cand)
            break
        except BaseException as e:
            failed.append(f"{cand}: {e!r}")

    if landed is not None and failed:
        try:
            with landed.open("a", encoding="utf-8") as f:
                # 這行也要帶 `[XCHK] `(理由同上:它一樣落在 LOG 裡,一樣會被同伴讀到)。
                # 獨立驗證實測:**只**加這條註腳行、不加主痕跡行,同伴一樣翻成靜音。
                f.write(f"[XCHK] [{stamp}] [XCHK-BROKEN] ↑ 上一行是**退到備援路徑**才寫成的;"
                        f"失敗的路:{'; '.join(failed)}" + chr(10))
        except BaseException:
            pass    # 這是註腳不是痕跡本身,它寫不進去不准把已經留成的痕跡變成沒留

    try:
        if sys.stderr is not None:
            enc = getattr(sys.stderr, "encoding", None) or "ascii"
            # encode/decode 先把編不了的字換掉 ⇒ cp950 遇到 emoji 不會拋。
            print(line.encode(enc, "replace").decode(enc, "replace"), file=sys.stderr)
    except BaseException:
        pass    # stderr 是**附帶**通道(排程下 sys.stderr is None,它本來就不出聲):
                # 它壞掉不准影響 rc、不准取代 main() 的根因,也不算留痕。

    # 🔴 回傳「到底有沒有留下痕跡」—— 讓回歸腳本斷言得到一個**具體簽章**,
    #    而不是只能斷言「沒拋例外」(那條件連「改掉標記字串」這種突變都殺不掉)。
    #    呼叫端(`except BaseException` 與 `on_broken=`)一律忽略它,行為不變。
    return landed


if __name__ == "__main__":
    import watch_crosscheck
    _rc = 1                      # main() 丟例外時的預設:例外不是「沒事」
    try:
        _rc = main()
    finally:
        # 收尾行放 finally:main() 中途丟例外時,已經吞掉的東西一樣要留得下來。
        swallow_epilogue()
        # 互查放在最後:**自己那行已經寫完了**才問「同伴最近一次該跑的時候有沒有留下行」。
        # 順序反過來會製造假告警競態;三個母體與已知邊界見 scripts/watch_crosscheck.py 的 docstring。
        # 🔴 互查也必須放 finally。原本它在 try/finally **之外** ⇒ main() 丟例外時
        # 控制流根本走不到那一行,互查整天不執行而且**沒有任何訊號**(09-10 獨立驗證 3-2)。
        # ⚠️ 更正一個錯誤的診斷:病不在「_rc 從沒被賦值」,在**控制流到不了那一行**。
        #    照「_rc 沒賦值」去修(在 try 前面給預設值)一個字都沒修到。
        try:
            _rc = watch_crosscheck.crosscheck_tail(_rc, "narration", record, alert,
                                                   on_broken=xchk_broken)
        except BaseException as _xe:
            # 不 re-raise:在 finally 裡 raise 會**取代** main() 原本那個例外,把根因換掉。
            # 但也絕不可以 pass —— 沉默偵測器沉默地壞掉正是它在治的病。
            # 🔴 不是 print 到 stderr —— 排程下 sys.stderr is None 會靜默 no-op,
            #    有 handle 時 cp950 編不了 🔴 會在這裡拋、取代 main() 的根因。見 xchk_broken。
            # 🔴 `xchk_broken()` 內部每一段都各自 try 過,所以「它不會拋」目前是真的 ——
            #    但那是一句**承重的**話,而它靠的是四段程式碼一直維持原樣。一旦被改壞,
            #    例外會從 `finally` 逃出去:①**取代 main() 原本的根因**、②下面那行
            #    `_rc = 4` 跑不到 ⇒ 互查壞掉這件事**靜默降級成 rc=0**。
            #    ⇒ 不要靠讀程式碼維持這個假設(memory `static-reading-vs-runtime-behaviour`),
            #      用一個 except 把它釘死。這裡真的只能 pass:最後一道防線的最後一層,
            #      它下面沒有別的路了,而 rc=4 在外面照樣設得到。
            try:
                xchk_broken(_xe)
            except BaseException:
                pass
            if _rc in (0, None):
                _rc = 4          # 4=互查機構自己壞了(≠同伴都正常)
    raise SystemExit(_rc)
