# -*- coding: utf-8 -*-
"""D4 單向閂的行為測試。沙箱:SCORE_LOG 指到暫存檔、notify 攔截不真送。
不碰正式的 score_history.jsonl,不打平台。"""
import io, json, sys, tempfile
from pathlib import Path
sys.path.insert(0, r'D:\carson-agent\quant-service\brain_alpha')
import brain_auto as B

tmp = Path(tempfile.mkdtemp()) / "score_history.jsonl"
B.SCORE_LOG = tmp

sent = []
def fake_notify(title, body):
    sent.append((title, body))
    return fake_notify.ok   # 回管道名字串,和真品同型;回 True 會被閂的 == 比較擋掉
B.notify = fake_notify

def run(consultant, level="GOLD", sub=13, notify_ok=True):
    """模擬一次 track_score 的尾段:建 rec → _sentinel → 落盤。"""
    fake_notify.ok = "brain_bot" if notify_ok else ""
    rec = {"ts": "T", "level": level, "submitted_total": sub,
           "competitions": [], "consultant_http": consultant, "src": "test"}
    errs = []
    B._sentinel(rec, errs)
    with tmp.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec, errs

def check(label, cond):
    print(("  PASS  " if cond else "  ***FAIL*** ") + label)
    return cond

allok = True
print("--- 1. 端點仍 403:閂不該叫(安全預設不產生噪音) ---")
before = len(sent); r, e = run(403)
allok &= check("沒有推播", len(sent) == before)
allok &= check("閂沒扣上", not r.get("consultant_notified"))

print("--- 2. 翻成 200:閂該叫一次,並扣上 ---")
before = len(sent); r, e = run(200)
allok &= check("推了一則", len(sent) - before == 1)
allok &= check("標題是顧問權限", "顧問權限已開" in sent[-1][0])
allok &= check("閂扣上了", r.get("consultant_notified") is True)

print("--- 3. 再跑一次 200:不該重複叫(閂已扣) ---")
before = len(sent); r, e = run(200)
allok &= check("沒有再推", len(sent) == before)

print("--- 4. 閂被刪掉(檔案回捲/損毀):方向該是重推,不是靜默 ---")
lines = [l for l in tmp.read_text(encoding="utf-8").splitlines() if l.strip()]
kept = [l for l in lines if not json.loads(l).get("consultant_notified")]
tmp.write_text("\n".join(kept) + "\n", encoding="utf-8")
before = len(sent); r, e = run(200)
allok &= check("重推一則(不是靜默)", len(sent) - before == 1)

print("--- 5. notify 失敗:閂不該扣上,下次要能重試 ---")
tmp.write_text("", encoding="utf-8")
before = len(sent); r, e = run(200, notify_ok=False)
allok &= check("有嘗試推", len(sent) - before == 1)
allok &= check("閂沒扣上", not r.get("consultant_notified"))
allok &= check("錯誤有記錄", any("consultant latch" in x for x in e))
before = len(sent); r2, e2 = run(200, notify_ok=True)
allok &= check("下一次重試並成功扣上", len(sent) - before == 1 and r2.get("consultant_notified") is True)

print("--- 6. edge:找不到 notified 時取最後一行,值相同 → 靜默 ---")
before = len(sent); r, e = run(200, level="GOLD", sub=13)
allok &= check("沒有推播", len(sent) == before)

print("--- 7. edge:level 變動 → 該叫,成功後標 notified ---")
before = len(sent); r, e = run(200, level="GRANDMASTER", sub=13)
allok &= check("推了一則", len(sent) - before == 1)
allok &= check("標題是分數更新", "分數更新" in sent[-1][0])
allok &= check("標了 notified", r.get("notified") is True)

print()
print("總結:" + ("全部通過" if allok else "有 FAIL,設計或實作有問題"))
sys.exit(0 if allok else 1)
