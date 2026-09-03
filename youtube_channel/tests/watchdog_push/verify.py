#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""local_cron_watchdog 的推播降頻驗收 —— crash-loop 要看得見,單一事故不准被升級。

背景:基建線沙箱實測 V2 發現「第二次重啟零通知」。舊版 `_push()` 在同因冷卻
(3600s)內直接 return,**連被擋都不記 log**,於是 crash-loop 長成:每次救援都成功、
log 全記錄但沒有人讀、Carson 每小時只收到一則不含次數的孤立推播 —— 迴圈不可見。

用法:cd youtube_channel && .venv/Scripts/python.exe tests/watchdog_push/verify.py
全程 stub 掉 notify.push 與時間,不推真推播、不碰真狀態檔。
"""
import json
import pathlib
import sys
import tempfile
import time

sys.path.insert(0, "scripts")
import local_cron_watchdog as w  # noqa: E402
import notify  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

tmp = pathlib.Path(tempfile.mkdtemp())
w.PUSH_STATE = tmp / "push.json"
sent, logs = [], []
w._log = lambda m: logs.append(m)
notify.push = lambda t, b, tag=None: (sent.append((t, b)), True)[1]
NOW = [time.time()]
w.time.time = lambda: NOW[0]

fails = 0


def check(label, cond, extra=""):
    global fails
    fails += 0 if cond else 1
    print(f"  {'PASS' if cond else '**FAIL**'}  {label}{('  ' + extra) if extra else ''}")


print("【一】crash-loop:每 5 分鐘一次,連續 2 小時(24 次事件)")
for i in range(24):
    w._push("restarted", "⚠️ 排程器被重啟", f"第 {i + 1} 次事件的原始內文")
    NOW[0] += 300
for t, _ in sent:
    print(f"     📱 {t}")
check("推播則數介於 4~8(舊版 2 則、每次都推是 24 則)", 4 <= len(sent) <= 8, f"實得 {len(sent)}")
check("第 2 則起都帶次數", all("連續第" in t for t, _ in sent[1:]))
check("被擋的每一次都有記 log(舊版靜默 return)",
      sum("冷卻中" in m for m in logs) == 24 - len(sent),
      f"{sum('冷卻中' in m for m in logs)} 筆")

print("\n【二】單一事故不得被誤升級")
w.PUSH_STATE.unlink(missing_ok=True)
sent.clear()
w._push("hung", "⚠️ 卡死", "單一事件")
NOW[0] += 7200
w._push("hung", "⚠️ 卡死", "兩小時後又一次")
check("相隔兩小時的兩次 → 兩則普通推播,都不帶「連續第」",
      len(sent) == 2 and all("連續第" not in t for t, _ in sent), str([t for t, _ in sent]))

print("\n【三】舊格式狀態檔(裸 epoch)原地升級,不炸也不清狀態")
w.PUSH_STATE.write_text(json.dumps({"restarted": NOW[0] - 10}), encoding="utf-8")
sent.clear()
w._push("restarted", "t", "b")
st = json.loads(w.PUSH_STATE.read_text(encoding="utf-8"))["restarted"]
check("升級成 dict、算成第 2 次、送出升級推播",
      isinstance(st, dict) and st["n"] == 2 and len(sent) == 1 and "第 2 次" in sent[0][0],
      json.dumps(st, ensure_ascii=False))

print("\n【四】推播失敗不得記冷卻(否則等於自己靜音一小時)")
w.PUSH_STATE.unlink(missing_ok=True)
sent.clear()
notify.push = lambda t, b, tag=None: False
w._push("failed", "x", "y")
check("後端回失敗 → 狀態檔不落地", not w.PUSH_STATE.exists())

print(f"\n合計 FAIL={fails}")
raise SystemExit(1 if fails else 0)
