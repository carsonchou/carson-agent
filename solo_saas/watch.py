# -*- coding: utf-8 -*-
"""numerus 觀察模式 —— 只報告不阻斷,把證據累積成帳本。

🔴 這支工具的存在理由:GATE_UPGRADE_CRITERIA.md 的三個條件如果只寫在 markdown 裡,
   它就是期望不是規則。這支把它變成**會產生輸出**的檢查:
     python watch.py            掃一次,新發現寫進帳本
     python watch.py --status   照判準算一次,印出「現在能不能升級」
     python watch.py --list     列出帳本裡每一條
     python watch.py --verdict <key> TRUE_POSITIVE|FALSE_ACCUSATION "為什麼"

🔴 它**永遠 exit 0**(只有 --verdict 參數寫錯會回 2)。不阻斷任何東西。
   --gate 不在這支裡,那是 cli.py 的事,而 cli.py 沒有掛上產線。

帳本 = solo_saas/ledger.json:
  runs           每次掃描的計數(**沒有樣本**和**準確**要分得開)
  findings       每一支 CONTRADICTED,含 human_verdict(預設 null = 未核對)
  first_seen     第一次看到它是什麼時候
  first_context  **第一次看到時**它落在哪個目錄 —— 判斷「其他閘門有沒有擋下」
                 的唯一依據,立了就不再改
  current_context 最近一次掃描時它在哪(會變,只拿來提示,不參與判準)
"""
import io
import json
import os
import sys
import time

# 🔴 本機 console 是 cp950,print 到「≥」就 UnicodeEncodeError 然後 exit 1。
# 隔壁 scripts/numerus_watch.py 有做這件事而這支沒有,結果 README 和它的 [ok]
# 訊息叫人跑的指令,在預設終端機直接崩 —— 一個只報告的東西不該有非 0 出口。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from numerus.check import CONTRADICTED, check_text

# 🔴 這兩個可覆寫是為了讓對照跑得起來 —— 一個永遠說「不可升級」的檢查
# 和一個正確說「不可升級」的檢查,輸出一模一樣。沒有沙箱就驗不出差別。
CORPUS = os.environ.get("NUMERUS_CORPUS") or r"D:\carson-agent\youtube_channel\output"
LEDGER = os.environ.get("NUMERUS_LEDGER") or os.path.join(HERE, "ledger.json")
EXT = ".voice.txt"
# 🔴 剛寫完的稿可能只寫到一半(memory yt-tts-partial-file-truncation:TTS 邊產
# 邊寫在**最終路徑**)。半截檔會產生假 CONTRADICTED,而 findings 只增不減
# ⇒ 那個假貨會永久卡在帳本裡,並且是**擋升級**的方向。等它靜置再看。
SETTLE_SECONDS = 600


def read(path):
    for enc in ("utf-8", "utf-8-sig", "cp950"):
        try:
            return io.open(path, encoding=enc).read()
        except (UnicodeDecodeError, LookupError):
            continue
    return ""


def load():
    """回傳 (帳本, 這本帳存不存在)。

    🔴 「存不存在」一定要傳出去:檔案不存在時當成空帳本,--status 會一路算到
    「未核對 0 條、誤指控 0 條 ⇒ 條件2 成立」。那不是報告,那是說謊 ——
    NUMERUS_LEDGER 指到一個打錯字的路徑就會踩到。"""
    if not os.path.exists(LEDGER):
        return {"runs": [], "findings": {}}, False
    return json.load(io.open(LEDGER, encoding="utf-8")), True


def save(d):
    """🔴 tmp → 讀回比對 → os.replace。memory write-truncates-before-it-fails:
    open(p,"w") 先截斷後寫入,中途拋例外原檔剩 0 bytes,而空帳本對下游是
    合法的「零筆」—— 零訊號。"""
    tmp = LEDGER + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1, sort_keys=True)
    back = json.load(io.open(tmp, encoding="utf-8"))
    assert len(back["findings"]) == len(d["findings"]), "讀回比對失敗,不覆蓋原帳本"
    os.replace(tmp, LEDGER)


def scan():
    """回傳 (findings, 因為還沒靜置而跳過的檔數)。

    findings = [(slug, ctx, claim, script_says, closest_label, closest_value)]"""
    out = []
    skipped = 0
    now = time.time()
    for dirpath, _, filenames in os.walk(CORPUS):
        rel = os.path.relpath(dirpath, CORPUS)
        # 🔴 這一格決定「其他閘門有沒有擋下它」。根目錄 = 現有閘門全部放行了。
        ctx = "PASSING" if rel == "." else rel
        for fn in sorted(filenames):
            if not fn.endswith(EXT):
                continue
            path = os.path.join(dirpath, fn)
            try:
                if now - os.path.getmtime(path) < SETTLE_SECONDS:
                    skipped += 1
                    continue
            except OSError:
                skipped += 1
                continue
            for f in check_text(read(path)):
                if f.verdict != CONTRADICTED:
                    continue
                best = min(f.candidates, key=lambda kv: abs(kv[1] - f.claim.amount))
                out.append((fn[:-len(EXT)], ctx, f.claim.raw,
                            f.claim.amount, best[0], best[1]))
    return out, skipped


def do_scan():
    d, _ = load()
    hits, skipped = scan()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    new = 0
    seen = {}       # 本輪同一 key 看到過哪些 ctx
    created = set() # 本輪才新建的 key
    for slug, ctx, raw, says, label, value in hits:
        key = "%s|%s" % (slug, raw)
        # ⚠️ 同一支稿可能同時存在於兩個目錄(複製而非搬移)。那時 current_context
        # 會變成 os.walk 的順序決定的 —— 一個不定值。取**最靠近出貨路徑**的那個:
        # 保守方向是「當它還在線上」,那會讓下面的位移警告印出來而不是被吃掉。
        prev = seen.get(key)
        seen[key] = "PASSING" if (ctx == "PASSING" or prev == "PASSING") else ctx
        ctx_now = seen[key]
        if key in d["findings"]:
            f = d["findings"][key]
            f["last_seen"] = now
            f["current_context"] = ctx_now
            # 同一輪裡才建立的紀錄,first_context 還在「第一次看到」的當下,
            # 允許往保守側修正一次;跨輪的一律不動。
            if key in created and ctx_now == "PASSING":
                f["first_context"] = "PASSING"
            # 舊 schema(只有 gate_context)就地搬成 first_context,搬完刪掉
            # 舊欄位 —— 兩個名字並存的話,下一個人不知道判準讀的是哪一個。
            f.setdefault("first_context", f.get("gate_context", ctx))
            f.pop("gate_context", None)
            continue
        new += 1
        created.add(key)
        d["findings"][key] = {
            "slug": slug, "claim": raw, "first_seen": now, "last_seen": now,
            # 🔴 first_context 立了就**不再改**。條件1 只認它。
            # 獨立驗證打穿的洞:原本每次掃描都拿「當下所在目錄」覆寫,而
            # human_verdict 是黏的 ⇒ 把一支已隔離、已判 TRUE_POSITIVE 的稿子
            # 複製/還原回 output/ 根目錄,它就翻成 PASSING 而舊判決留著,
            # --status 立刻說「可以升級」—— 用的正是 GATE_UPGRADE_CRITERIA.md
            # 白紙黑字寫「那支不算」的稿子。redo_defective_unpublished.py、
            # rescue_redo.py、人工還原都會造成這個位移。
            "first_context": ctx_now,
            "current_context": ctx_now,
            "script_says": says,
            "closest": {"formula": label, "value": value},
            "human_verdict": None,        # 🔴 null = 未核對。不是「沒問題」。
            "human_note": "",
        }
    d["runs"].append({"at": now, "contradicted": len(hits), "new": new,
                      "corpus": CORPUS})
    save(d)
    print("掃描 %s" % now)
    print("  CONTRADICTED 共 %d 條,其中新出現 %d 條" % (len(hits), new))
    if skipped:
        print("  (另有 %d 個檔 %d 秒內剛動過,還沒靜置,這輪不看)"
              % (skipped, SETTLE_SECONDS))
    for slug, ctx, raw, says, label, value in hits:
        print("  [%s] %s — 稿寫 %s,同段算得出 %s = %s"
              % (ctx, slug[:40], format(says, ",.0f"), label, format(value, ",.0f")))
    return 0


def do_status():
    """照 GATE_UPGRADE_CRITERIA.md 算一次。**這是判準的執行版本。**"""
    d, exists = load()
    if not exists:
        print("🔴 帳本不存在:%s" % LEDGER)
        print("   這不是「沒有誤報」,是**沒有帳**。先跑一次 python watch.py。")
        print("結論:**不可升級**(無從評估)")
        return 0

    fs = list(d["findings"].values())
    # 🔴 只認 first_context。理由見 do_scan() 裡那段。
    first_ctx = lambda f: f.get("first_context", f.get("gate_context"))
    shipped = [f for f in fs if first_ctx(f) == "PASSING"]
    unchecked = [f for f in fs if f["human_verdict"] is None]
    indep_tp = [f for f in shipped if f["human_verdict"] == "TRUE_POSITIVE"]
    false_acc = [f for f in fs if f["human_verdict"] == "FALSE_ACCUSATION"]
    moved = [f for f in fs if f.get("current_context")
             and f["current_context"] != first_ctx(f)]

    print("帳本:%s" % LEDGER)
    print("  掃描次數 %d,最近一次 %s"
          % (len(d["runs"]), d["runs"][-1]["at"] if d["runs"] else "(無)"))
    print("  CONTRADICTED 累計 %d 條(其中**第一次看到時**就在出貨路徑上 %d 條)"
          % (len(fs), len(shipped)))
    for f in moved:
        print("  ⚠️ %s 的所在目錄變過:%s → %s(判準仍綁在前者)"
              % (f["slug"][:36], first_ctx(f), f["current_context"]))
    print()

    c1 = len(indep_tp) >= 1
    print("條件1 ≥1 支獨立真陽性       :%s  (第一次看到就在出貨路徑上、且人工判為真 = %d)"
          % ("成立" if c1 else "不成立", len(indep_tp)))

    # 🔴 兩個恆真坑一起堵:
    #   ① 沒人核對 ⇒「誤報 0」自動成立。
    #   ② 一條樣本都沒有 ⇒「誤報 0」也自動成立,那是沒有樣本不是準確。
    if not fs:
        c2, why = False, "**一條 CONTRADICTED 都沒有** —— 沒有樣本不等於準確"
    elif false_acc:
        c2, why = False, "誤指控 %d 條" % len(false_acc)
    elif unchecked:
        c2, why = False, ("有 %d 條**還沒有人核對**,不是暫時無法判定,是不成立"
                          % len(unchecked))
    else:
        c2, why = True, "全部核對過且無誤指控"
    print("條件2 同期誤報 = 0          :%s  (%s)" % ("成立" if c2 else "不成立", why))
    print("條件3 重量①且仍可承受      :需人工重跑 tests/measure_delta.py,本工具不代答")
    print()
    print("結論:%s" % ("條件 1、2 成立,可以進入升級討論(條件 3 仍需人工重量)"
                      if (c1 and c2) else "**不可升級**,維持只報告不阻斷"))
    return 0


def do_verdict(argv):
    """python watch.py --verdict <key> TRUE_POSITIVE|FALSE_ACCUSATION "為什麼"

    🔴 判決要**人**下。這個入口只是把它記下來,不代人判。
    key 用 --status 或 --list 列出來的那一串。"""
    i = argv.index("--verdict")
    try:
        key, verdict = argv[i + 1], argv[i + 2]
    except IndexError:
        print('用法:--verdict <key> TRUE_POSITIVE|FALSE_ACCUSATION ["為什麼"]')
        return 2
    note = argv[i + 3] if len(argv) > i + 3 else ""
    if verdict not in ("TRUE_POSITIVE", "FALSE_ACCUSATION"):
        print("verdict 只能是 TRUE_POSITIVE 或 FALSE_ACCUSATION")
        return 2
    d, exists = load()
    if not exists or key not in d["findings"]:
        print("帳本裡沒有這個 key(%s)。現有的:" % LEDGER)
        for k in d["findings"]:
            print("  " + k)
        return 2
    f = d["findings"][key]
    f["human_verdict"] = verdict
    f["human_note"] = note
    f["verdict_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    # 判決當下綁的是哪個 context,一併記下來:日後有人爭議「這支算不算獨立」,
    # 看得到判決是對著哪個位置下的。
    f["verdict_context"] = f.get("first_context", f.get("gate_context"))
    save(d)
    print("已記:%s → %s" % (key, verdict))
    return 0


def do_list():
    d, exists = load()
    if not exists:
        print("帳本不存在:%s" % LEDGER)
        return 0
    for k, f in sorted(d["findings"].items()):
        print("%-12s %-9s %s"
              % (f.get("first_context", f.get("gate_context")),
                 f["human_verdict"] or "未核對", k))
    return 0


if __name__ == "__main__":
    if "--verdict" in sys.argv:
        sys.exit(do_verdict(sys.argv))
    if "--list" in sys.argv:
        sys.exit(do_list())
    sys.exit(do_status() if "--status" in sys.argv else do_scan())
