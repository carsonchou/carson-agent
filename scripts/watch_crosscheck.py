# -*- coding: utf-8 -*-
"""三支守望互查 —— 讓「單支沉默」變成有訊號。

背景:2026-09-10,`seeding` 與 `narration` 兩支哨整天沒被觸發,
而**沒有任何東西叫**。當時的結構是「哨沉默 = 沒有訊號」——
那正是這三支哨自己在治的病,換一個樓層復發。
成因與證據:`docs/ops/2026-09-10_watch_silence_rootcause.md`
施工圖:`docs/ops/2026-09-10_watch_fix_plan.md`

本模組**唯讀**:只讀三份 log,不寫 log、不推播。判決交給呼叫端的 record()/alert()。


🔴 告警設計說明 —— 三個母體(memory `gate-verification-population`)
================================================================
一道閘門的母體是「**全部會經過它的**」,不是「它新擋下的」。

① **今天會叫的**:把 seeding/narration 的 log 截回 59,289 / 17,589 bytes
   (= 2026-09-10 18:05 補跑前的真實磁碟內容),quota 15:20 那次跑起來 ⇒ **必須叫**。
② **全部會經過它的日子**:
   - **週末/連假**:三支都排每日,無特例。⚠️ 若日後改成只跑平日,這裡要同步改,
     否則每個週末誤叫;**改排程的人要一起改這裡**。
   - **機器整天沒開**:三支都沒跑 ⇒ 落入③,靜音。
   - **只有一支跑**:那一支會叫,指名另外兩支缺席 ⇒ 正確。
   - **早上 07:00 那一刻**:quota(15:20)今天本來就還沒跑 ⇒ 判準若寫成
     「今天有沒有行」會**每天誤叫**。所以判準是「**各支自己最近一次應該跑的時刻**
     之後有沒有留下行」,不是「今天」。
③ 🔴 **反方向被放掉的**(這一節是母體③,不要只讀①):
   - **三支全部沒跑的那一天,互查也是靜音的。**
     互查治的是「單支沉默」,**治不了「全部沉默」**。
     三支之中 `quota` 排 15:20(離開機/登入窗最遠),是這個設計唯一的支點。
   - **補跑沒帶 `WATCH_MANUAL=1` 而註記隔天才追加**(M2)⇒ 靜音。實測過,見下。
   - **補跑沒帶 `WATCH_MANUAL=1` 而註記和讀數之間插了別的行** ⇒ 靜音。實測過,見下。
   ⇒ **不要拿這道互查當「守望已完備」的證據。**
   它把單支沉默變成有訊號,把全部沉默留在原地 ——
   而全部沉默正是「機器整天沒開」那一天的長相。
   ⇒ 而人工補跑那兩格靠的是**人記得帶環境變數**,不是結構。


人工補跑的處理(本次事故的核心誤讀)
====================================
🔴 **「今天有人補跑過」不等於「排程今天有跑」。** 合併計數會讓下一個人
把補跑讀成排程正常 —— 那正是 09-10 這一天差點發生的事。

判準:
- `[DRILL] ` 開頭 ⇒ **一律不算讀數**(演習不是讀數)。
- `[MANUAL] ` 開頭 ⇒ **不算排程行**;而且它會把**緊鄰在它上面、同一天的**那行
  讀數從「排程」降級為「人工」(09-10 的補跑就是這個長相:讀數行本身沒有前綴,
  由後面追加的 `[MANUAL]` 註記行指認它)。
- `[XCHK] ` 開頭 ⇒ **一律不算讀數**(互查自己寫的行不是讀數,見下面 M1)。
- `WATCH_MANUAL=1` ⇒ `record()` 把 `[MANUAL] ` 打在**讀數行本身**,不依賴任何相鄰關係。
  補跑的人請帶這個環境變數;沒帶時才退回下面那條脆弱的相鄰規則。

🔴 09-10 獨立驗證推翻了本檔原本寫的一句話,原句照抄在這裡不刪:
   > 「⇒ 失效方向:含糊的情況一律往『不算排程行』倒,也就是往**會叫**倒。」
**這句是假的。** 實測兩種含糊情況都往**不叫**倒,而往不叫倒沒有任何訊號:

- **M1(已修,而且它是我自己造的)**:`crosscheck_tail()` 在互查失敗時呼叫 `record(line)`,
  而 `record()` 寫出來的是 `[2026-09-10 18:05] 🔴 守望互查:…` —— 一個**沒有前綴、
  完全符合 `_TS`** 的行。於是「互查叫過」本身被下一次互查讀成「今天有排程讀數」。
  因果鏈是閉合的:人會補跑正是因為那天有哨沉默 ⇒ 那天互查必然叫 ⇒ 補跑必然多寫這一行。
  09-10 躲過純粹因為 18:05 補跑時互查還沒上線。**修法:互查自己的行一律帶 `[XCHK] ` 前綴**,
  讓它在結構上不可能被當成讀數 —— 而不是靠 pop 一筆去猜。
  🔴 為什麼說「結構上」:`_TS` 錨在行首,前綴把時間戳擠開一格,那行就**配不上** `_TS`。
  這比 skip 清單強,因為它不需要任何一段程式碼記得去查表。突變測試見 `XCHK_PREFIX` 上方。
- **M2(只修了一半,照實寫)**:`[MANUAL]` 註記寫在隔天(晚上補跑、隔天早上才回來註記)⇒
  註記的日期和讀數的日期不相等 ⇒ 相鄰降級不發生 ⇒ 靜音。
  **註記行只帶「我被寫下的時間」,不帶「我在指誰」**,這個病相鄰規則治不了。
  出口是 `WATCH_MANUAL=1`,讓前綴打在讀數行本身。
  🔴 **但那是流程修法不是結構修法**:2026-09-11 拿真 log 當語料實測,
  補跑**沒帶** `WATCH_MANUAL` 時,M2 這個形狀**依然靜音**(和修之前一模一樣)。
  ⇒ 這一格能不能擋,取決於補跑的人記不記得帶環境變數。它還沒好。
- **M3(已修)**:互查收尾原本寫在 `try/finally` 的**外面** ⇒ `main()` 丟例外時
  控制流根本走不到那一行,互查整天不執行、而且沒有任何訊號。
  ⚠️ 我第一次把它診斷成「`_rc` 從沒被賦值」,那是**錯的診斷**:照那樣修
  (在 `try` 前面給 `_rc` 預設值)一個字都沒修到。病在控制流到不了那一行。
  修法=互查搬進 `finally`;而 `finally` 裡再包一層 `except BaseException`,
  因為在 `finally` 裡 raise 會**取代** `main()` 原本那個例外、把根因換掉。
  該層**不准 pass**:印 `[XCHK-BROKEN]` 到 stderr,rc 原本是 0 就升成 **4**。
- ⚠️ **相鄰規則收緊的代價,實測**:已收緊成「只降級**緊接在上一行**的那筆讀數」
  (原本是「最後一筆同日讀數」,中間插進東西就會抓錯人)。
  收緊治好了一格、也弄壞一格,兩格都用真 log 量過:
    · 治好:註記指的**不是**那筆真排程讀數時,舊碼會把真排程讀數降級 ⇒ 誤叫;新碼不會。
    · 弄壞:註記指的讀數**不緊鄰**(中間插一行演習)時,舊碼降級 ⇒ 叫;
      新碼不降級 ⇒ **靜音**(實測 got 從 09-09 變 09-10,判決從「叫」變「靜音」)。
  ⇒ 收緊的**淨方向是往靜音倒**,不是純改善。這一格的出口同樣是 `WATCH_MANUAL=1`。
"""
import datetime
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
OPS = REPO / "docs" / "ops"

# 🔴 這三個時刻是**排程工作 StartBoundary 的複本**,會漂(memory
# `criteria-anchored-to-mutable-property`)。用 `--check-schedule` 對活的排程比一次,
# 不要靠讀這段註解相信它還是對的。
WATCHES = {
    "seeding":   {"log": OPS / "seeding-watch.log",
                  "task": "carson-seeding-watch",
                  "at": datetime.time(7, 0)},
    "narration": {"log": OPS / "narration-compliance-watch.log",
                  "task": "carson-narration-compliance-watch",
                  "at": datetime.time(7, 10)},
    "quota":     {"log": OPS / "quota-ceiling-watch.log",
                  "task": "carson-quota-ceiling-watch",
                  "at": datetime.time(15, 20)},
}

GRACE = datetime.timedelta(minutes=60)   # 允許補跑/延遲;超過才算它錯過了

_TS = re.compile(r"^\[(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}")
_MANUAL_TS = re.compile(r"^\[MANUAL\]\s*\[(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}")

# 互查自己寫進 log 的行一律帶這個前綴。**這一格是承重的**:沒有它的話,
# 互查告警本身就是一筆長得像排程讀數的行(M1)。
# 🔴 承重的到底是哪一行,2026-09-11 用突變測試釘死了(結論和我原本寫的不一樣):
#   前綴的作用是**把時間戳從行首擠開** —— `_TS` 是 `^\[(\d{4}-...`,行首必須緊接日期,
#   所以 `[XCHK] [2026-09-11 ...]` 根本配不上 `_TS`。
#   實測:把 `_SKIP_PREFIXES` 清成 `()`,M1 那格**判決不變**(仍然會叫);
#         把 `XCHK_PREFIX` 改成 `""`,M1 那格**當場翻成靜音**。
#   ⇒ 承重的是這個常數與 `crosscheck_tail()` 裡那兩行 f-string,不是下面那張表。
XCHK_PREFIX = "[XCHK] "
# 讀數行**自己**要說得出「我是補跑」時用的環境變數。相鄰規則猜不到的事情,讓它自己講。
MANUAL_ENV = "WATCH_MANUAL"
# ⚠️ 這張表**目前是冗餘的**(對 `_TS` 而言):`[DRILL] `/`[XCHK] ` 開頭的行本來就配不上
# `_TS`,因為 `_TS` 錨在行首。突變測試證實清成 `()` 判決不變。留著是因為它會在
# `_TS` 哪天被放寬成 `search` 的那一刻變成唯一的防線 —— 但**不要把它當成 M1 的修法**。
_SKIP_PREFIXES = ("[DRILL]", XCHK_PREFIX.strip())


def manual_prefix():
    """補跑時 `WATCH_MANUAL=1` ⇒ 回傳 `"[MANUAL] "`,由三支哨的 `record()` 貼在行首。

    為什麼不靠相鄰的註記行:註記行只帶「我被寫下的時間」,不帶「我在指誰」。
    人晚上補跑、隔天早上才回來註記(M2)相鄰規則就失效,而且**往不叫倒**。
    """
    import os
    return "[MANUAL] " if os.environ.get(MANUAL_ENV) else ""


def last_sched_date(path):
    """回傳 (最後一筆**排程**讀數的日期, 最後一筆人工/註記行的日期)。

    讀不到檔 ⇒ (None, None);那本身就是異常,由呼叫端判。
    ⚠️ 唯讀,而且一次讀完 —— 這三份是活的 append-only 檔,不做讀-改-寫。
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None, None

    sched = []          # [date str],依出現順序
    manual_dates = []
    prev_was_sched = False      # 上一行「被採計成排程讀數」了嗎(相鄰降級只認真的相鄰)
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(_SKIP_PREFIXES):
            # 演習行、以及**互查自己寫的行**,都不是讀數。後者是 M1 的修法所在:
            # 少了它,「互查叫過」會被下一次互查讀成「今天有排程讀數」。
            prev_was_sched = False
            continue
        m = _MANUAL_TS.match(line)
        if m:
            manual_dates.append(m.group(1))
            # 降級:**緊接在上一行**、同一天的那筆讀數,其實是人工補跑的。
            # 🔴 收緊過:原本是「最後一筆同日讀數」,中間插進任何行都會抓錯人。
            if prev_was_sched and sched and sched[-1] == m.group(1):
                sched.pop()
            prev_was_sched = False
            continue
        m = _TS.match(line)
        if m:
            sched.append(m.group(1))
            prev_was_sched = True
        else:
            prev_was_sched = False
    return (sched[-1] if sched else None,
            manual_dates[-1] if manual_dates else None)


def due_date(at, now):
    """那支哨**最近一次應該跑完**的日期(含 GRACE)。

    now 還沒過今天的 at+GRACE ⇒ 期待落在昨天,不是今天。
    這一格就是「早上 07:00 不該去要求 quota(15:20)今天有行」的所在。
    """
    today_due = datetime.datetime.combine(now.date(), at) + GRACE
    return now.date() if now >= today_due else now.date() - datetime.timedelta(days=1)


def crosscheck(self_key, now=None):
    """回傳 (ok: bool, msg: str)。ok=False ⇒ 呼叫端要 record() + alert()。"""
    now = now or datetime.datetime.now()
    bad, notes = [], []
    for key, w in WATCHES.items():
        want = due_date(w["at"], now).isoformat()
        got, man = last_sched_date(w["log"])
        who = "自己" if key == self_key else "同伴"
        if got is None:
            bad.append(f"{key}({who}):讀不到 {w['log'].name} 或裡面沒有任何排程讀數")
        elif got < want:
            extra = (f",另有人工/註記行到 {man}(🔴 補跑不等於排程有跑)"
                     if man and man >= want else "")
            bad.append(f"{key}({who}):最後一筆排程讀數停在 {got},"
                       f"應該要有 {want}(排 {w['at'].strftime('%H:%M')}){extra}")
        else:
            # 🔴 不可以只印 got:早上 07:00 那一班 quota 的 want 是**昨天**,
            # 只印 `quota=昨天` 讀起來像「quota 昨天壞了但被容忍」。把 want 一起印,
            # 並分開「已跑」和「還沒到點」—— 兩者原本印成同一個長相。
            if want < now.date().isoformat():
                notes.append(f"{key}={got}(未到今日點,應到 {want})")
            else:
                notes.append(f"{key}={got}(已到 {want})")

    if bad:
        return False, ("🔴 守望互查:有哨沉默了 —— " + "；".join(bad)
                       + (f"｜正常的:{'、'.join(notes)}" if notes else "")
                       + "｜成因與修法見 docs/ops/2026-09-10_watch_silence_rootcause.md"
                       + "｜⚠️ 互查治不了「三支全沉默」,那天它也是安靜的")
    return True, "互查 ok:" + "、".join(notes)


def crosscheck_tail(rc, self_key, record, alert, now=None):
    """三支哨共用的收尾。**在自己那行寫完之後**呼叫,不可以反過來。

    反過來的話自己那行還沒落地,同時在跑的兩支會互判對方缺席 —— 一個會製造假告警的競態。

    `record` / `alert` 由呼叫端傳進來(同 `seeding_watch._push_and_trace` 的作法):
    演習與正式因此走**同一份程式碼**,而不是在演習分支裡複製一份 ——
    複製出來的演習只證明得了複本會叫。

    出口碼:**3 = 互查發現別支哨沉默**。只在 rc 原本是 0 時才升級,
    不覆蓋這支哨自己的告警碼(1=自己判出異常)。
    **4 = 互查機構自己壞了**(由三支哨的 `finally` 給,不是這裡給;同樣只在 rc==0 時升級)。
    ⚠️ `main()` 丟例外時,呼叫端會在 `finally` 呼叫本函式,但**回傳的 rc 會被丟掉** ——
    原本那個例外會繼續往外逃,行程以 traceback 收場(exit 1)。這是刻意的:
    根因比 rc 重要,而 exit 1 一樣是非零。告警行本身已經在這裡寫進 log 了。
    """
    now = now or datetime.datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M")
    try:
        ok, msg = crosscheck(self_key, now=now)
        if ok:
            return rc
        line = f"{XCHK_PREFIX}[{stamp}] {msg}"
    except Exception as e:
        # 互查自己壞掉時**必須出聲**:沉默偵測器沉默地壞掉,正是它在治的病。
        line = (f"{XCHK_PREFIX}[{stamp}] 🔴 守望互查丟例外 —— 今天的沉默偵測沒有生效"
                f"(這不是「同伴都正常」):{e!r}")
        msg = line
    try:
        record(line)
        alert("守望互查:有哨沉默了", msg)
    except Exception:
        pass
    return 3 if rc == 0 else rc


def check_schedule():
    """把上面的 `at` 常數對活的排程比一次 —— 常數會漂,漂了不會有人知道。"""
    import subprocess
    rc = 0
    for key, w in WATCHES.items():
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Export-ScheduledTask -TaskName '{w['task']}')"],
                capture_output=True, text=True, timeout=60).stdout
        except Exception as e:
            print(f"{key}: FAILED to read task ({e!r})"); rc = 2; continue
        want = w["at"].strftime("T%H:%M:%S")
        hit = want in out
        print(f"{key}: constant {w['at'].strftime('%H:%M')} "
              f"{'matches' if hit else 'DOES NOT MATCH'} StartBoundary in {w['task']}")
        if not hit:
            rc = 2
    return rc


if __name__ == "__main__":
    if "--check-schedule" in sys.argv:
        raise SystemExit(check_schedule())
    _self = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--self=")), "")
    ok, msg = crosscheck(_self)
    try:
        print(msg)
    except UnicodeEncodeError:          # cp950 主控台
        print(msg.encode("ascii", "replace").decode())
    raise SystemExit(0 if ok else 1)
