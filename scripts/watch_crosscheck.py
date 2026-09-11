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
  該層**不准 pass**:呼叫該支哨自己的 `xchk_broken()`(**寫進 log 檔**,不是印到
  stderr —— 見 `crosscheck_tail` 的 docstring 與獨立驗證新-1),rc 原本是 0 就升成 **4**。
- 🔴 **相鄰規則已經廢掉,改成行序無關的認領**(2026-09-11 第三輪獨立驗證【2/5】)。
  歷史:曾經是「最後一筆同日讀數」→ 收緊成「只降級**緊接在上一行**的那筆」→ 現在是
  「每一則 `[MANUAL]` 註記認領同一天的一筆讀數,不看位置」。
  收緊那一版錯在**兩個失效方向不對稱,而我選了會靜音的那邊**:
    · 鬆的那版失效 ⇒ **誤叫**(把真排程讀數降級)。成本 = 有人多看一眼。
    · 緊的那版失效 ⇒ **靜音**(降級不觸發)。成本 = 這支哨那天等於不存在。
  而緊的那版的失效條件不是邊角,是**每一次人工補跑的必然形狀**:同一次執行裡
  `finally` 會先寫一行 `[XCHK]` 告警,夾在讀數和事後註記之間,把 `prev_was_sched` 打掉。
  ⇒ 我當初把它記成「演習行的邊角代價」,那句話是錯的,是主線。
  ⇒ 判準不對稱時先問「失效會往哪邊倒」,再問「命中率」
  (memory `fail-closed-criterion-is-explainability`)。這一格的出口仍然是 `WATCH_MANUAL=1`。
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
# ⚠️ 這張表**是冗餘的**(對 `_TS` 而言):`[DRILL] `/`[XCHK] ` 開頭的行本來就配不上
# `_TS`,因為 `_TS` 錨在行首。突變測試證實清成 `()` 判決不變。留著是因為它會在
# `_TS` 哪天被放寬成 `search` 的那一刻變成唯一的防線 —— 但**不要把它當成 M1 的修法**。
# 🔴 2026-09-11:M1 曾經**真的**靠它擋(靠 `prev_was_sched` 被它重設),而那條路已經
# 拆掉了,原因見 `last_sched_date()` 裡那段長註解。現在它回到「純冗餘的第二層」。
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
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(_SKIP_PREFIXES):
            # 演習行、以及**互查自己寫的行**,都不是讀數。
            # ⚠️ 這個分支**不承重**:`[DRILL] `/`[XCHK] ` 開頭的行本來就配不上錨在行首的
            #    `_TS`,清成 `()` 判決不變(突變實測)。真正承重的是下面那段認領。
            continue
        m = _MANUAL_TS.match(line)
        if m:
            manual_dates.append(m.group(1))
            continue
        m = _TS.match(line)
        if m:
            sched.append(m.group(1))
    # 🔴 降級(2026-09-11 第三輪獨立驗證【2/5】重寫):**每一則 `[MANUAL]` 註記,
    #    認領同一天的一筆讀數**。刻意不看行的位置。
    #
    #    為什麼不看位置:上一版是「只降級**緊接在上一行**的那筆」,而產線真實行序是
    #        讀數 → `[XCHK]` 告警(同一次執行,`finally` 寫的) → (之後)`[MANUAL]` 註記
    #    ⇒ `[XCHK]` 那行把 `prev_was_sched` 打掉 ⇒ 降級**永遠不觸發** ⇒ 靜音,
    #    而且和修之前逐位相同。實測 A/B(只差 `[XCHK]` 行的位置):
    #        讀數→註記→XCHK  ⇒ ('2026-09-09','2026-09-10') 會叫
    #        讀數→XCHK→註記  ⇒ ('2026-09-10','2026-09-10') **靜音**
    #    而「補跑」的因果鏈是閉合的:會有人補跑正是因為那天有哨沉默 ⇒ **那天互查必然
    #    叫過** ⇒ 中間插一行不是邊角情況,是每一次人工補跑的必然形狀。
    #
    #    🔴 為什麼不照驗證員給的第一個修法(讓 `[XCHK]` 分支不要動 `prev_was_sched`):
    #    突變實測,那個修法今天能過**只因為** `[XCHK] ` 剛好命中 `_SKIP_PREFIXES`;
    #    把那個「本檔註解自己宣告冗餘」的常數清成 `()`,`[XCHK]` 行掉到 else 分支,
    #    靜音就無聲無息地回來(突變 3 翻面、突變 4 又靜音)。那是把判準釘在會變的屬性上
    #    (memory `criteria-anchored-to-mutable-property`),失效方向是放寬。
    #
    #    這個寫法的**不變量(窄版,這才是真的)**:`[MANUAL]` 註記認領哪一筆讀數,
    #    只看日期、不看位置 ⇒ 註記行與 `[XCHK]` 行插在檔案的**任何位置**,
    #    判決與告警內文都逐字相同,那組 A/B 在定義上不可能再分岔。
    #    回歸有一列排列對照釘住它(`watch_crosscheck_regression.py` 的「M1b 排列」:
    #    兩行插到所有位置共 3,422 種,2026-09-11 全跑過一次 ⇒ 內文 1 種;常駐列抽 150 種)。
    #
    #    🔴 **不要把它讀成「輸出完全不依賴行序」** —— 這句話在 2026-09-11 之前就寫在這裡,
    #    後面還接著「回歸有一列洗牌對照釘住它」,而那一列**當時並不存在**(grep 零命中),
    #    宣稱本身也是假的:實測把整份 log(含讀數行)亂序洗 300 次,量到 **91 種**不同內文,
    #    因為 `sched[-1]` 取的是「檔案裡最後出現」的讀數,不是日期最大的那筆。
    #    ⇒ 本檔**承重一個具名假設:log 是 append-only 且時間遞增**。
    #    (刻意不改成 `max(sched)`:位置版碰到亂序會**誤叫**,max 版會被一行未來日期**消音**
    #     ⇒ 失效方向要留在會叫的那一邊,memory `criteria-anchored-to-mutable-property`。)
    #
    #    ⚠️ 剩下的不健全,講清楚:`_MANUAL_TS` 分不出「自己宣告的補跑讀數」
    #    (`WATCH_MANUAL=1` 產生的 `[MANUAL] [ts] 讀數`)和「事後補的註記行」——
    #    兩者長相一模一樣。所以同一天兩筆補跑只配一則註記時,會剩一筆被當成排程讀數
    #    ⇒ 仍然靜音。出口還是 `WATCH_MANUAL=1`:那條路上讀數行**自己**說得出它是誰,
    #    根本不需要認領(第一輪獨立驗證判它閉合)。
    for _d in manual_dates:
        for _i in range(len(sched) - 1, -1, -1):
            if sched[_i] == _d:
                del sched[_i]
                break
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
    # 🔴 免責原本只掛在 alert 那則,而「ok」是 99% 的情況 ⇒ 絕大多數時候讀 log 的人
    #    看不到這個系統的已知盲區(09-11 獨立驗證 3-4)。掛到這則上面來。
    return True, ("互查 ok:" + "、".join(notes)
                  + "｜⚠️ 這則 ok 的已知盲區:①三支全沉默那天**沒有人呼叫互查**,它也安靜"
                    "(拓樸缺陷,不是判準缺陷:直接餵過期語料呼叫它,它叫得很大聲)"
                    "②補跑沒帶 WATCH_MANUAL=1 會被讀成排程行"
                    "③超時被排程砍掉時連 finally 都不跑 ⇒ 這則根本不會出現")


def _broken(on_broken, msg):
    """把「互查收尾自己壞了」交給呼叫端的最後一道留痕。呼叫端沒給就退回守衛版 stderr。

    這裡的每一層都**不准往外拋**:本函式只在 `finally` 的收尾路徑上被呼叫,
    在那裡拋例外會取代 `main()` 原本那個例外、把根因換掉。
    """
    if on_broken is not None:
        try:
            on_broken(msg)
            return
        except BaseException:
            pass          # 連最後一道都壞了 ⇒ 掉到下面那條,總比整個換掉根因好
    try:
        if sys.stderr is not None:
            enc = getattr(sys.stderr, "encoding", None) or "ascii"
            print(msg.encode(enc, "replace").decode(enc, "replace"), file=sys.stderr)
    except BaseException:
        pass


def crosscheck_tail(rc, self_key, record, alert, now=None, on_broken=None):
    """三支哨共用的收尾。**在自己那行寫完之後**呼叫,不可以反過來。

    反過來的話自己那行還沒落地,同時在跑的兩支會互判對方缺席 —— 一個會製造假告警的競態。

    `record` / `alert` 由呼叫端傳進來(同 `seeding_watch._push_and_trace` 的作法):
    演習與正式因此走**同一份程式碼**,而不是在演習分支裡複製一份 ——
    複製出來的演習只證明得了複本會叫。

    `on_broken(訊息)` 也由呼叫端傳進來,而且**必須**傳:它是「連 record 都寫不進去」
    時的最後一道留痕,所以它得寫在**呼叫端自己的 log 檔**上(呼叫端才知道路徑),
    而不是寫在本模組裡 —— 本函式出問題的時候,本模組正是剛倒的那根柱子。
    🔴 2026-09-11 獨立驗證(新-1):前一版這裡是 `print(..., file=sys.stderr)`,
    而三支哨的 Action 是 `pythonw.exe` ⇒ 排程下 `sys.stderr is None`,`print(file=None)`
    退回同樣是 None 的 `sys.stdout` ⇒ **靜默 no-op**;有繼承 handle 時編碼是 `cp950`,
    訊息裡的 🔴 會拋 `UnicodeEncodeError`。**沒有一種環境會讓那行字出現在人眼前。**
    `on_broken=None` 時退回一條「先 encode(...,'replace') 再印」的守衛版 stderr,
    它只是不讓程式炸掉,**不算留痕** —— 呼叫端沒傳 on_broken 就是還沒接好。

    出口碼:**3 = 互查發現別支哨沉默**。只在 rc 原本是 0 時才升級,
    不覆蓋這支哨自己的告警碼(1=自己判出異常)。
    **4 = 互查機構自己壞了**(由三支哨的 `finally` 給,不是這裡給;同樣只在 rc==0 時升級)。
    ⚠️ **`rc != 3` 推論不出「隔壁哨沒事」**:本函式是 `3 if rc == 0 else rc`,
    只在這支哨自己 rc 原本是 0 時才升級。而 `narration` 目前**天天 rc=1**
    (連續四天遵守率低於地板)⇒ 它的互查結果**永遠不會出現在 rc 上**。
    這是常態不是邊角。而且全 repo 沒有任何東西讀 `LastTaskResult` ⇒
    rc 目前不是訊號通道,只是一個沒人收信的位址(09-11 獨立驗證 3-3 / Q4)。
    🔴 **搬進 `finally` 只治得了第二層裡的第一層**(09-11 獨立驗證 3-2「而且它有兩層」):
    第一層 = Action 是 `pythonw.exe`,traceback 無處落地(不在 log:`record()` 還沒被
    呼叫到;不在 console:沒有 console;不在事件檢視器:那裡只有 exit code 不是 traceback)
    ⇒ 「這支哨今天炸了」和「今天正常」在磁碟上長得一模一樣。`finally` 治這一層。
    第二層 = `ExecutionTimeLimit=PT15M`。卡死超時是**整個程序被殺**,走的不是例外路徑,
    **連 `finally` 都不跑** ⇒ 搬進 `finally` 對這一層無效,腳本內沒有任何修法。
    唯一出路是體制外觀測者,而那個現在是空殼:`CarsonQuant-UptimeMonitor` 的
    `monitor.py` 是 `TARGETS = []`(07-11 droplet 退役時註解掉),LastRunTime 停在
    2026/7/11 11:33、NumberOfMissedRuns=17664 —— 它自己沉默兩個月也沒有人收到訊號,
    和這次事故同一種病,只是發生在觀測層。**現在沒有任何 out-of-band heartbeat。**

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
    # 🔴 原本這裡是 `try: record(); alert() / except Exception: pass`,一個 except 包住兩個
    #    呼叫 ⇒ 有**兩種**壞法而且都靜音(09-11 獨立驗證 3-3):
    #      · record() 拋 ⇒ log 行和推播雙失,磁碟上完全沒有痕跡
    #      · 只有 alert() 拋 ⇒ 行落地了但手機沒響,下一個人讀 log 會**以為推播出去過**
    #    所以拆開,而且第二種要在 log 裡自己招認。
    xfail, landed = [], False
    try:
        record(line)
        landed = True
    except Exception as e:
        xfail.append(f"record 失敗 ⇒ log 行與推播雙失,磁碟上沒有痕跡:{e!r}")
    try:
        alert("守望互查:有哨沉默了", msg)
    except Exception as e:
        xfail.append(f"alert 失敗 ⇒ 手機沒響:{e!r}")
        if landed:
            try:
                record(f"{XCHK_PREFIX}[{stamp}] 🔴 上面那行互查告警**沒有推播出去**:{e!r}")
            except Exception:
                pass
    if xfail:
        _broken(on_broken, f"[XCHK-BROKEN] 互查收尾自己壞了:{'；'.join(xfail)}")
    return 3 if rc == 0 else rc


def judge_schedule(w, lines, now):
    """純函式:吃 PowerShell dump 的行,回 `(probs, notes)`。

    🔴 **刻意和 `subprocess` 拆開。** 不拆開的話,E / F / H / I 四個判準就是四句
    沒有儀器的宣稱 —— 而要用真排程去驗它們,得去正式機造一個同名工作、把工作停用、
    塞一個過期的 EndBoundary,那是**寫正式機**,不是驗證該付的代價。
    拆開之後 `watch_crosscheck_regression.py` 餵合成 dump 就驗得到,而合成的只是
    **儀器讀到的那串字**,判準本身是真的那一份(memory `load-bearing-line-needs-mutation`
    要的常駐突變列也才有地方掛)。

    dump 的格式(見 `check_schedule()` 裡那段 PowerShell):
        COUNT=<n>   PATH=<taskpath>   STATE=<state>
        TRIG=<enabled>|<start>|<end>|<cimclass>|<delay>
        INFO=<lastrun ISO>|<missedruns>|<lasttaskresult>
    """
    def many(tag):
        return [l.split("=", 1)[1] for l in lines if l.startswith(tag + "=")]

    probs, notes = [], []
    count = next((l.split("=", 1)[1] for l in lines if l.startswith("COUNT=")), "0")
    paths, states, trigs = many("PATH"), many("STATE"), many("TRIG")
    info = next((l.split("=", 1)[1] for l in lines if l.startswith("INFO=")), "")

    # (E) 恰好一個同名工作
    if count != "1":
        probs.append(f"同名工作有 {count} 個(TaskPath={paths})—— 陣列會讓 State "
                     f"變成 'Ready Disabled' 這種字串,舊判準會放它過")
    # (F) State 只認 Ready / Running
    state = states[0] if states else ""
    if state not in ("Ready", "Running"):
        probs.append(f"State={state or '?'}(只認 Ready / Running;Unknown 代表排程"
                     f"讀不到這個工作,而舊判準 != Disabled 會放它過)")

    # (I) 觸發器:Enabled + 時刻對 + EndBoundary 沒過期
    want = w["at"].strftime("T%H:%M:%S")
    live, expired = [], []
    for tr in trigs:
        f = (tr.split("|") + [""] * 5)[:5]
        en, sb, eb = f[0].strip(), f[1].strip(), f[2].strip()
        if en.lower() != "true" or want not in sb:
            continue
        if eb:
            try:
                gone = datetime.datetime.fromisoformat(eb).replace(tzinfo=None) < now
            except Exception:
                gone = True     # 讀不懂就當它過期 —— 失效方向往「叫」倒
            if gone:
                expired.append(eb)
                continue
        live.append(tr)
    if not live:
        probs.append(f"沒有任何「Enabled + StartBoundary 落在 {w['at'].strftime('%H:%M')}"
                     f" + EndBoundary 未過期」的觸發器"
                     + (f";有 {len(expired)} 個時刻對但已過期({expired})" if expired else ""))

    # (H) 🔴 排程自己說它上次跑在什麼時候 —— 和 log 那邊同一把尺(同一個 due_date)
    lr, missed, lastrc = (info.split("|") + ["", "", ""])[:3]
    due_dt = datetime.datetime.combine(due_date(w["at"], now), w["at"])
    if not lr:
        probs.append("排程說它**從來沒跑過**(LastRunTime 空)")
    else:
        try:
            last = datetime.datetime.fromisoformat(lr)
        except Exception:
            probs.append(f"LastRunTime 讀不懂:{lr!r}")
            last = None
        if last is not None and last < due_dt:
            probs.append(f"🔴 排程自己說上次跑是 {lr},而最近一次該跑完的是 "
                         f"{due_dt.isoformat(' ')} ⇒ **漏跑**。"
                         f"2026-09-10 那場事故就是這一格,而上一代這裡是綠的")

    notes.append(f"常數 {w['at'].strftime('%H:%M')} / {w['task']} / LastRun={lr or '?'} / "
                 f"due={due_dt.isoformat(' ')} / "
                 f"LastTaskResult={lastrc or '?'}(不當判準:narration 穩態就是 1) / "
                 f"MissedRuns={missed or '?'}(不當判準:歸零時機未驗)")

    # 不參與判定的觸發器(LogonTrigger 就落在這裡):照印
    for tr in trigs:
        f = (tr.split("|") + [""] * 5)[:5]
        if want in f[1]:
            continue
        notes.append(f"(附帶·不參與判定)type={f[3] or '?'} enabled={f[0]} "
                     f"start={f[1]} delay={f[4] or '-'}")
    want_delay = w.get("logon_delay")
    if want_delay:
        hit = [tr for tr in trigs
               if "Logon" in (tr.split("|") + [""] * 5)[3] and want_delay in tr]
        if not hit:
            probs.append(f"修(二) 的 LogonTrigger(Delay={want_delay})不在活的排程裡")
    return probs, notes


def old_judge_schedule(w, lines):
    """**第二代的判準,逐字保存,只給回歸腳本當陽性對照用。**

    它就是被【4/5】打掉的那一版:`State != Disabled` + 「有 Enabled 觸發器時刻對得上」,
    不問 `LastRunTime`、不問同名工作幾個、不看 `EndBoundary`。
    回歸腳本拿它和 `judge_schedule()` 在同一份 dump 上並排 ——
    **「新判準會叫」單獨不構成修好了**,還要證明舊判準在同一份 dump 上是綠的,
    否則「我修了 E/F/H/I」和「這四格本來就會叫」分不開。
    ⚠️ 不要「順手更新」這個函式:它是歷史紀錄,不是活的碼。
    """
    states = [l.split("=", 1)[1] for l in lines if l.startswith("STATE=")]
    trigs = [l.split("=", 1)[1] for l in lines if l.startswith("TRIG=")]
    want = w["at"].strftime("T%H:%M:%S")
    state = " ".join(states)        # $t 是陣列時 PowerShell 就是這樣攤平的
    live = [tr for tr in trigs
            if tr.split("|", 1)[0].strip().lower() == "true" and want in tr]
    return bool(live) and state.lower() != "disabled"


def check_schedule(now=None):
    """把上面的 `at` 常數對**活的**排程比一次,並且**問排程它上次到底有沒有跑**。

    ## 這支的病史(兩代,兩次都是「驗的東西不是要治的病」)

    第一代:比對是「`want` 這個字串在不在整份 XML 裡」。獨立驗證往活的 XML 塞
    `<Enabled>false</Enabled>`,它照樣回 match ⇒ 它驗的是某個字串在不在,
    不是那個觸發器活不活 —— 和它要治的病(靜默失效)同一種。

    🔴 第二代(2026-09-11 第三輪獨立驗證【4/5】):改成問結構化欄位之後,它**在
    2026-09-10 那場事故本身上是綠的**。實測活的排程(09-11 02:46 讀,唯讀):

        carson-seeding-watch             State=Ready  LastRun=09/09 07:00  Missed=1  rc=0
        carson-narration-compliance-...  State=Ready  LastRun=09/09 07:10  Missed=1  rc=1
        carson-quota-ceiling-watch       State=Ready  LastRun=09/10 15:20  Missed=0  rc=0

    兩支哨 09-10 整天沒跑,而**排程自己記著這件事**(`LastRunTime` 停在 09-09、
    `NumberOfMissedRuns=1`),就在同一趟 PowerShell 拿得到的欄位裡 ——
    而第二代一個都沒問。它治的是「常數漂了」,事故是「該跑沒跑」。
    ⇒ **一道檢查在它要治的那場事故上是綠的,是「檢查不會失敗」的一種**
    (memory `verification-that-cannot-fail`)。

    ## 現在問什麼(括號裡是驗證員的編號)

    1. 同名工作**恰好一個**(E)。同名工作躺在兩個 TaskPath 時 `$t` 是陣列,
       `$t.State` 會變成 `Ready Disabled` 這種字串 —— 而舊碼的判準是
       `state != "disabled"` ⇒ **一個被停用的孿生工作可以讓它綠燈**。
    2. `State` 必須是 `Ready` 或 `Running`(F)。舊碼寫 `!= Disabled`
       ⇒ `Unknown`(工作損壞、排程服務讀不到)**過關**。失效方向是放寬。
    3. 觸發器:Enabled、StartBoundary 落在那個時刻、**而且 EndBoundary 沒過期**(I)。
       過期的觸發器留在 XML 裡長得和活的一模一樣,但它不會再跑。
       EndBoundary 有值卻讀不懂 ⇒ 也算問題(往「叫」倒)。
    4. 🔴 **`LastRunTime` 不得早於 `due_date()` 算出來的那個時刻**(H)。
       這一格用的是**和 log 那一邊完全同一把尺**(同一個 `due_date`)⇒ 兩個獨立
       來源(排程自己的紀錄 vs log 落地的行)配同一個判準,對不上就是有一邊在騙人。

    ## 刻意**不**當判準的兩個欄位,理由寫在這裡而不是留在腦子裡

    - `LastTaskResult`:`narration` 的穩態就是 `rc=1`(它天天在告警,
      見施工圖 §3 註腳 (ii))⇒ 拿它當判準會**天天誤叫**,而天天誤叫等於靜音。
      照印不判。
    - `NumberOfMissedRuns`:它的**歸零時機我沒有驗過**。若它不會自己歸零,
      拿它當判準會變成永久紅燈,而永久紅燈也等於靜音。照印不判,並留一個
      可觀測的作業:09-11 07:00 那次跑完之後回來看它有沒有變 0 ——
      有,才可以把它升成判準。

    ## 這支**驗不了**什麼(不要拿它當修(二)的守衛)

    - 🔴 **它驗不了 LogonTrigger。** 判準是「StartBoundary 落在 `at` 這個時刻」,
      而 LogonTrigger 的 StartBoundary 是**註冊那一刻**,不是時刻常數 ⇒ 它只會
      被當成「不參與判定的觸發器」印出來。修(二)(登入補跑)上線之後要有人回來把
      `logon_delay` 填進 `WATCHES` 才會變成斷言 —— 在那之前這裡只**照印**型別與 Delay。
    - 它的輸出通道只有 **stdout**:本模組唯讀,不寫 log。⇒ 只能由人在 shell 裡跑;
      哪天把它排進 `pythonw`,`sys.stdout is None`,整支**靜默 no-op**
      (和新-1 同一個病)。要排程化就得先給它一條 log 通道。

    ⚠️ 還沒好的一半(照實寫):全 repo **沒有任何東西呼叫本函式** ——
    `grep check[-_]schedule` 只命中它自己的定義和施工圖。所以它是**手動引信**,
    而手動引信等於沒有引信。排進排程屬於新類型的正式機變更,要先問 Carson。
    """
    import subprocess
    now = now or datetime.datetime.now()
    ps = ("$ErrorActionPreference='Stop'; "
          "$all = @(Get-ScheduledTask -TaskName '{task}'); "
          "'COUNT=' + $all.Count; "
          "foreach ($x in $all) {{ 'PATH=' + $x.TaskPath; 'STATE=' + $x.State }} "
          "$t = $all[0]; "
          "foreach ($g in $t.Triggers) {{ "
          "$d = ''; if ($g.PSObject.Properties['Delay']) {{ $d = [string]$g.Delay }} "
          "'TRIG=' + $g.Enabled + '|' + $g.StartBoundary + '|' + $g.EndBoundary + '|' "
          "+ $g.CimClass.CimClassName + '|' + $d }} "
          "$i = Get-ScheduledTaskInfo -TaskName '{task}'; "
          "$lr = ''; if ($i.LastRunTime) {{ $lr = $i.LastRunTime.ToString('yyyy-MM-ddTHH:mm:ss') }} "
          "'INFO=' + $lr + '|' + $i.NumberOfMissedRuns + '|' + $i.LastTaskResult")
    rc = 0
    for key, w in WATCHES.items():
        try:
            cp = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps.format(task=w["task"])],
                capture_output=True, text=True, timeout=60)
        except Exception as e:
            print(f"{key}: 🔴 讀不到排程({e!r})")
            rc = 2
            continue
        lines = [l.strip() for l in cp.stdout.splitlines() if l.strip()]
        if not lines:
            print(f"{key}: 🔴 PowerShell 沒有回任何東西(returncode={cp.returncode}) "
                  f"stderr={cp.stderr.strip()[:200]!r}")
            rc = 2
            continue
        probs, notes = judge_schedule(w, lines, now)
        if probs:
            rc = 2
            print(f"{key}: 🔴 " + "；".join(probs))
        else:
            print(f"{key}: OK 常數 {w['at'].strftime('%H:%M')} 對到活的觸發器且沒有漏跑")
        for n in notes:
            print("      " + n)

    if rc == 0:
        print("note: 本函式沒有任何排程呼叫它 —— 這次是人手動跑的。手動引信等於沒有引信。")
        print("note: 它驗不了 LogonTrigger(判準錨在時刻常數,而 LogonTrigger 沒有時刻)"
              " ⇒ 不要拿它當修(二)的守衛。")
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
