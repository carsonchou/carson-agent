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
③ 🔴 **反方向被放掉的:三支全部沒跑的那一天,互查也是靜音的。**
   互查治的是「單支沉默」,**治不了「全部沉默」**。
   三支之中 `quota` 排 15:20(離開機/登入窗最遠),是這個設計唯一的支點。
   ⇒ **不要拿這道互查當「守望已完備」的證據。**
   它把單支沉默變成有訊號,把全部沉默留在原地 ——
   而全部沉默正是「機器整天沒開」那一天的長相。


人工補跑的處理(本次事故的核心誤讀)
====================================
🔴 **「今天有人補跑過」不等於「排程今天有跑」。** 合併計數會讓下一個人
把補跑讀成排程正常 —— 那正是 09-10 這一天差點發生的事。

判準:
- `[DRILL] ` 開頭 ⇒ **一律不算讀數**(演習不是讀數)。
- `[MANUAL] ` 開頭 ⇒ **不算排程行**;而且它會把**緊鄰在它上面、同一天的**那行
  讀數從「排程」降級為「人工」(09-10 的補跑就是這個長相:讀數行本身沒有前綴,
  由後面追加的 `[MANUAL]` 註記行指認它)。
- ⇒ 失效方向:含糊的情況一律往「**不算排程行**」倒,也就是往**會叫**倒。
  寧可多叫一次,不要把補跑讀成排程正常。
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
        if not line or line.startswith("[DRILL]"):
            continue
        m = _MANUAL_TS.match(line)
        if m:
            manual_dates.append(m.group(1))
            # 降級:緊鄰在上面、同一天的那筆排程讀數,其實是人工補跑的。
            if sched and sched[-1] == m.group(1):
                sched.pop()
            continue
        m = _TS.match(line)
        if m:
            sched.append(m.group(1))
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
            notes.append(f"{key}={got}")

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
    """
    now = now or datetime.datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M")
    try:
        ok, msg = crosscheck(self_key, now=now)
        if ok:
            return rc
        line = f"[{stamp}] {msg}"
    except Exception as e:
        # 互查自己壞掉時**必須出聲**:沉默偵測器沉默地壞掉,正是它在治的病。
        line = (f"[{stamp}] 🔴 守望互查丟例外 —— 今天的沉默偵測沒有生效"
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
