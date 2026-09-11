# -*- coding: utf-8 -*-
"""13 支設 private 的 dry-run —— 🔴 離線、零 API 呼叫、本檔沒有任何 videos().update。

讀 snapshot.json(prep.py 產出),對 13 支逐一:
  1. 用 build_body() 組出「會送出去的」完整 body
  2. 印 status 改前 → 改後 diff
  3. 斷言:除了 privacyStatus 以外全部相同,且 privacyStatus 真的從 public 變 private

⚠️ 真執行時 status 要從**寫入當下** videos.list 讀回,不能拿這份快照組 body
   (快照到執行之間任何人改過 status,拿快照送會把他的改動蓋回去)。
⚠️ 殘留洞:status.containsSyntheticMedia 是可寫欄位但 videos.list 不回傳 ⇒
   任何「讀回再送」的寫法都帶不到它。這是 API 的限制,不是這支腳本能補的。

另外跑兩列自我檢查,證明 diff 檢查器**會失敗**(否則「13/13 只差 privacyStatus」
和「檢查器恆過」分不開):
  N1 set_private_by_ids.py:79 的寫法 body.status = {"privacyStatus": ...} → 必須被抓出掉欄位
  N2 突變:把 embeddable 翻面 → 必須被抓出
"""
import io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

snap = json.load(io.open(os.path.join(HERE, "snapshot.json"), encoding="utf-8"))
cand = json.load(io.open(os.path.join(HERE, "candidates.json"), encoding="utf-8"))
items = snap["items"]
TARGET = "private"


def build_body(vid, status_now):
    """執行時唯一該用的組法:整包 status 帶回去,只換 privacyStatus。"""
    st = dict(status_now)
    st["privacyStatus"] = TARGET
    return {"id": vid, "status": st}


def status_diff(before, after):
    keys = sorted(set(before) | set(after))
    return {k: (before.get(k, "<缺>"), after.get(k, "<缺>"))
            for k in keys if before.get(k, "<缺>") != after.get(k, "<缺>")}


def check(before, body):
    """回傳錯誤清單;空 = 通過。"""
    errs = []
    d = status_diff(before, body["status"])
    extra = {k: v for k, v in d.items() if k != "privacyStatus"}
    if extra:
        errs.append("privacyStatus 以外有差異:%r" % extra)
    if d.get("privacyStatus") != ("public", TARGET):
        errs.append("privacyStatus 不是 public→%s:%r" % (TARGET, d.get("privacyStatus")))
    return errs


print("# dry-run —— 快照時間 %s,零 API 呼叫,零寫入\n" % snap["fetched_at"])
ok = 0
vids = [r["videoId"] for r in cand["videos"]]
for n, vid in enumerate(vids, 1):
    it = items.get(vid)
    if it is None:
        print("[%02d] %s  ❌ 快照裡沒有這支 —— 不送" % (n, vid)); continue
    before = it["status"]
    body = build_body(vid, before)
    errs = check(before, body)
    print("[%02d] %s  %s" % (n, vid, it["snippet"]["title"]))
    print("  送出 body = videos().update(part=\"status\", body=%s)"
          % json.dumps(body, ensure_ascii=False, sort_keys=True))
    for k, (a, b) in status_diff(before, body["status"]).items():
        print("  diff  %-24s %r → %r" % (k, a, b))
    same = [k for k in sorted(before) if k != "privacyStatus"]
    print("  不變  %s" % ", ".join("%s=%r" % (k, before[k]) for k in same))
    print("  判定  %s\n" % ("✅ 只差 privacyStatus" if not errs else "❌ " + "; ".join(errs)))
    ok += not errs

print("=" * 70)
print("13 支結果:%d/%d 只差 privacyStatus(public→%s)" % (ok, len(vids), TARGET))

# ---- 自我檢查:檢查器必須會失敗 ----
probe = vids[0]
before = items[probe]["status"]
n1 = {"id": probe, "status": {"privacyStatus": TARGET}}           # set_private_by_ids.py:79 的寫法
n2 = build_body(probe, before); n2["status"]["embeddable"] = not before.get("embeddable")
r1, r2 = check(before, n1), check(before, n2)
print("\n自我檢查(用 %s):" % probe)
print("  N1 只送 privacyStatus(set_private_by_ids.py:79 寫法) → %s" % ("被抓出 ✅ " + r1[0] if r1 else "❌ 沒抓到=檢查器壞了"))
print("  N2 突變 embeddable 翻面                               → %s" % ("被抓出 ✅ " + r2[0] if r2 else "❌ 沒抓到=檢查器壞了"))

# ---- 陰性對照(不送 body,只列出回讀時要比對的基準) ----
print("\n回讀基準(這些片不在批次內,T1/T2 時 status 必須與下列逐欄相同):")
for grp in ("negative_controls_public", "negative_controls_unlisted"):
    for c in cand[grp]:
        st = items[c["videoId"]]["status"]
        print("  [%s] %s  %s" % (grp.split("_")[-1], c["videoId"], json.dumps(st, sort_keys=True)))

allpass = ok == len(vids) and r1 and r2
print("\nDRYRUN_RESULT:", "PASS" if allpass else "FAIL")
sys.exit(0 if allpass else 1)
