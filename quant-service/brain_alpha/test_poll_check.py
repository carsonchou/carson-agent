#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`/check` 輪詢與提交閘門的回歸測試（2026-09-05）。

## 為什麼有這支
`scripts/scan_ambiguous_zero.py` 掃到 `poll_check` 沒有檢查 `r.ok`。
執行期實測(獨立驗證員在 `--submit` 路徑跑出來的)：

    餵一個 401 的 DRF 錯誤 body
      → r.text 非空 → r.json() 成功 → 回一個 dict
      → 呼叫端 `if not data` 不觸發 → checks 折成 []
      → bad == [] → 印「全綠，送出提交…」→ **真的走到 POST /submit**
      → 與餵真全綠 body 的結果逐項相同

第二層更前面：**輪詢的終止條件是「body 非空」，不是「檢查解析完」**。
而 `SELF_CORRELATION` 在 Check Submission 算完之前恆為 PENDING
(`docs/ledger-platform-gap-20260905.md:120`)，所以 body 一非空就收工，
拿到的 PENDING 是**我們自己沒等完**，不是平台說它通過。

兩者都是 memory `verification-that-cannot-fail` 那一族：一個表示「沒事」的值
有超過一種路徑產生它，而下游只讀值不讀路徑。

## 這支測什麼
擋下的每一種「沒觀測到」，**外加陽性對照**——沒有陽性對照的話，
「一律回非 0」也會全綠通過，那種閘門壞在另一邊(一定叫 = 不會叫的親戚)。

    python test_poll_check.py        # 全過印 ALL PASS，任一失敗 exit 1
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import brain_auto as B      # noqa: E402
import pick_next as P       # noqa: E402
import submit_alpha as SA   # noqa: E402


# ── stub：不連網、不碰帳號 ──────────────────────────────────────────
class Resp:
    def __init__(self, code, body, retry_after="0"):
        self.status_code = code
        self._b = body
        self.headers = {"Retry-After": retry_after}

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    @property
    def text(self):
        return self._b

    def json(self):
        return json.loads(self._b)


class Sess:
    """依序吐 responses；用完之後一直吐最後一個。"""

    def __init__(self, *responses):
        self.q = list(responses)
        self.n = 0

    def get(self, *a, **k):
        r = self.q[min(self.n, len(self.q) - 1)]
        self.n += 1
        return r

    def post(self, *a, **k):
        raise AssertionError("POST_REACHED")   # 提交閘門若放行，這裡會炸出來


def body(*checks):
    return json.dumps({"is": {"checks": list(checks)}})


def ck(name, result, value=None):
    return {"name": name, "result": result, "value": value}


B_401 = '{"detail":"Authentication credentials were not provided."}'
B_403 = '{"detail":"You do not have permission."}'
B_PASS = body(ck("LOW_SHARPE", "PASS", 2.10), ck("SELF_CORRELATION", "PASS", 0.41))
B_FAIL = body(ck("LOW_SHARPE", "PASS", 2.10), ck("SELF_CORRELATION", "FAIL", 0.91))
B_PEND = body(ck("LOW_SHARPE", "PASS", 2.10), ck("SELF_CORRELATION", "PENDING"))
B_WARN = body(ck("LOW_SHARPE", "PASS", 2.10), ck("UNITS", "WARNING"))
B_NONAME = body({"result": "PASS", "value": 1.0})          # 缺 name 欄
B_EMPTY = json.dumps({"is": {"checks": []}})

FAILURES = []


def check(name, cond, detail=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  " + detail) if detail else ""))
    if not cond:
        FAILURES.append(name)


def gate(*responses):
    """跑**真品** submit_alpha.main() 的 --check 路徑，回 exit code。

    只換掉 `B.auth`（stub session）與 `B.CHECK_LOG`（改寫到暫存檔，
    否則測試會把垃圾寫進 repo 的 check_bodies.jsonl）。其餘全走真的程式碼。
    --check 模式在全綠時 return 0 且**不會**送出提交；stub 的 post() 會拋
    AssertionError，所以萬一走到 POST 這支測試會直接爆給你看。
    """
    orig_auth, orig_argv, orig_log = B.auth, sys.argv, B.CHECK_LOG
    tmp = Path(tempfile.gettempdir()) / "test_check_bodies.jsonl"
    try:
        B.auth = lambda *a, **k: Sess(*responses)
        SA.B.auth = B.auth
        B.CHECK_LOG = tmp
        sys.argv = ["submit_alpha.py", "--check", "TESTID"]
        return SA.main()
    finally:
        B.auth, SA.B.auth, sys.argv, B.CHECK_LOG = orig_auth, orig_auth, orig_argv, orig_log


def main() -> int:
    print("=" * 74)
    print("1. poll_check 契約：data is None ⟺ reason 是非空字串")
    print("=" * 74)
    cases = [
        ("401", Resp(401, B_401), "HTTP 401"),
        ("403", Resp(403, B_403), "HTTP 403"),
        ("500", Resp(500, "boom"), "HTTP 500"),
        ("200 非 JSON", Resp(200, "<html>502</html>"), "回傳不是 JSON"),
        ("200 body 是 list", Resp(200, "[]"), "回傳不是 dict"),
        ("200 body 是 null", Resp(200, "null"), "回傳不是 dict"),
        ("200 body 是字串", Resp(200, '"x"'), "回傳不是 dict"),
        ("200 body 是數字", Resp(200, "123"), "回傳不是 dict"),
        ("輪詢用完仍無 body", Resp(200, "   "), "逾時"),
    ]
    for label, resp, want in cases:
        d, why = B.poll_check(Sess(resp), "TESTID", tries=2)
        check("%-20s → data is None" % label, d is None, "實得 %r" % (d,))
        check("%-20s → reason 是非空字串且說得出種類" % label,
              isinstance(why, str) and why.startswith(want), "實得 %r" % (why,))

    print()
    print("=" * 74)
    print("2. 輪詢要等到檢查解析完（PENDING 不是收工訊號）")
    print("=" * 74)
    d, why = B.poll_check(Sess(Resp(200, B_PEND), Resp(200, B_PEND), Resp(200, B_PASS)),
                          "TESTID", tries=6)
    resolved = B.parse_checks(d) or {}
    check("PENDING → 繼續輪詢 → 拿到解析後的 body",
          d is not None and resolved.get("SELF_CORRELATION", {}).get("result") == "PASS",
          "實得 %r" % (resolved.get("SELF_CORRELATION"),))
    check("解析完 → reason 是空字串（契約：'' 才代表乾淨）", why == "", "實得 %r" % (why,))
    d2, why2 = B.poll_check(Sess(Resp(200, B_PEND)), "TESTID", tries=3)
    check("一直 PENDING → 輪詢用完仍交出 body（由 verdict 判，不在這層二度攔截）",
          d2 is not None)
    # 🔴 這一格是契約的重點：拿到 body 但沒等完，不可以和「平台真的算完了」同型。
    check("一直 PENDING → reason 非空，且說明是我們放棄不是平台判的",
          isinstance(why2, str) and why2 != "" and "我們放棄" in why2, "實得 %r" % (why2,))
    check("「解析完」與「我們放棄」分得出來", why != why2, "%r vs %r" % (why, why2))

    print()
    print("=" * 74)
    print("3. parse_checks / check_verdict")
    print("=" * 74)
    for label, b in [("空 checks", B_EMPTY), ("401 body", B_401),
                     ('{"is": null}', '{"is":null}'), ("{}", "{}")]:
        check("%-14s → parse_checks 回 None" % label, B.parse_checks(json.loads(b)) is None)
    # key 帶位置（"?0" 而不是 "?"）是刻意的：共用一個 "?" 會讓多個無名 check
    # 後蓋前，正是第 8 節那個 fail-open。
    check("缺 name 欄 → 不 KeyError，收成帶位置的 '?0'",
          (B.parse_checks(json.loads(B_NONAME)) or {}).get("?0") is not None)
    check("正常 body → 折得出 2 項【陽性對照】",
          len(B.parse_checks(json.loads(B_PASS)) or {}) == 2)
    for label, b, want_ok in [("全 PASS", B_PASS, True), ("有 FAIL", B_FAIL, False),
                              ("有 PENDING", B_PEND, False), ("有 WARNING", B_WARN, False)]:
        ok, why, _ = B.check_verdict(json.loads(b))
        check("verdict(%-10s) ok=%s" % (label, want_ok), ok is want_ok, "why=%r" % (why,))

    print()
    print("=" * 74)
    print("4. Retry-After 髒值不可以讓輪詢爆掉")
    print("=" * 74)
    for label, ra in [("abc", "abc"), ("負數", "-5"), ("HTTP-date", "Wed, 21 Oct 2015 07:28:00 GMT")]:
        try:
            v = B._retry_after(Resp(200, "{}", retry_after=ra), 0)
            check("Retry-After=%-10s → 回非負數 %s" % (label, v), isinstance(v, float) and v >= 0)
        except Exception as e:  # noqa: BLE001
            check("Retry-After=%-10s → 不拋例外" % label, False, repr(e))

    print()
    print("=" * 74)
    print("5. 提交閘門（跑真品 submit_alpha.main --check；走到 POST 會 AssertionError）")
    print("=" * 74)
    blocked = [
        ("401", Resp(401, B_401)), ("403", Resp(403, B_403)), ("500", Resp(500, "boom")),
        ("非 JSON", Resp(200, "<html>")), ("body 是 list", Resp(200, "[]")),
        ("body 是 null", Resp(200, "null")), ("空 checks", Resp(200, B_EMPTY)),
        ("is 為 null", Resp(200, '{"is":null}')), ("PENDING", Resp(200, B_PEND)),
        ("WARNING", Resp(200, B_WARN)),
    ]
    rcs = {}
    for label, resp in blocked:
        try:
            rc = gate(resp)
        except AssertionError as e:  # noqa: BLE001
            rc = "走到 POST！ %s" % e
        rcs[label] = rc
        check("%-14s → 擋下 (rc!=0)" % label, rc != 0, "rc=%s" % rc)

    rc_fail = gate(Resp(200, B_FAIL))
    check("真的有 FAIL → 擋下【陽性對照】", rc_fail != 0, "rc=%s" % rc_fail)
    rc_pass = gate(Resp(200, B_PASS))
    check("真的全綠 → 放行 (rc==0)【陽性對照：證明不是一律擋】", rc_pass == 0, "rc=%s" % rc_pass)

    print()
    print("=" * 74)
    print("6. exit code 分得出「不合格」與「沒觀測到」")
    print("=" * 74)
    check("FAIL → rc=1（要改式子）", rc_fail == 1, "rc=%s" % rc_fail)
    check("401 → rc=3（要換 token）", rcs["401"] == 3, "rc=%s" % rcs["401"])
    check("PENDING → rc=3（要再等）", rcs["PENDING"] == 3, "rc=%s" % rcs["PENDING"])
    check("FAIL 與 沒觀測到 的 rc 不同", rc_fail != rcs["401"],
          "%s vs %s" % (rc_fail, rcs["401"]))

    print()
    print("=" * 74)
    print("7. 三支工具共用同一份實作（不可以再分歧）")
    print("=" * 74)
    check("pick_next.poll_check is brain_auto.poll_check", P.poll_check is B.poll_check)
    check("submit_alpha.poll_check is brain_auto.poll_check", SA.poll_check is B.poll_check)
    check("pick_next.checks_of 空 checks 回 None",
          P.checks_of(json.loads(B_EMPTY)) is None)
    check("pick_next.checks_of 正常回 (result, value)【陽性對照】",
          (P.checks_of(json.loads(B_PASS)) or {}).get("SELF_CORRELATION") == ("PASS", 0.41))

    print()
    print("=" * 74)
    print("8. parse_checks 不可以丟掉任何一項（缺名字 / 同名重複都不行）")
    print("=" * 74)
    # 🔴 上一版寫 out[name or "?"] = c，後蓋前：兩個無名 check [FAIL, PASS]
    #    只留下 PASS → ok=True → 實測走到 POST /submit。
    two_noname = body({"result": "FAIL"}, {"result": "PASS"})
    pc = B.parse_checks(json.loads(two_noname)) or {}
    check("兩個無名 check → 兩項都保留", len(pc) == 2, "實得 %d 項" % len(pc))
    ok8, why8, _ = B.check_verdict(json.loads(two_noname))
    check("兩個無名 check（FAIL 在前）→ verdict 擋下", ok8 is False, "why=%r" % (why8,))
    rc8 = gate(Resp(200, two_noname))
    check("同上 → 閘門擋下（不可以走到 POST）", rc8 != 0, "rc=%s" % rc8)
    dup = body(ck("SELF_CORRELATION", "FAIL", 0.9), ck("SELF_CORRELATION", "PASS", 0.4))
    check("同名重複（FAIL 在前）→ 兩項都保留",
          len(B.parse_checks(json.loads(dup)) or {}) == 2)
    check("同名重複 → verdict 擋下", B.check_verdict(json.loads(dup))[0] is False)
    notdict = json.dumps({"is": {"checks": ["x", 3, None]}})
    check("checks 裡有非 dict 項目 → 收成非 PASS 佔位，擋下",
          B.check_verdict(json.loads(notdict))[0] is False)

    print()
    print("=" * 74)
    print("9. 判定規則只有一份（三個呼叫端對同一份 body 必須答案相同）")
    print("=" * 74)
    for label, b in [("全 PASS", B_PASS), ("有 FAIL", B_FAIL), ("有 PENDING", B_PEND),
                     ("有 WARNING", B_WARN), ("result=null", body(ck("X", None))),
                     ("兩個無名", two_noname), ("同名重複", dup)]:
        data = json.loads(b)
        raw = B.parse_checks(data)
        v_ok = B.check_verdict(data)[0]                    # submit_alpha 走這條
        v_np = B.non_pass(raw)                             # brain_daily_pick 走這條
        v_pn = B.non_pass(P.checks_of(data))               # pick_next 走這條
        check("%-12s → 三者一致" % label,
              (v_ok is (not v_np)) and v_np == v_pn,
              "verdict_ok=%s non_pass=%s pick_next=%s" % (v_ok, v_np, v_pn))

    print()
    print("=" * 74)
    print("10. 迴歸守衛：每個 poll_check 呼叫端都必須解二元組")
    print("=" * 74)
    # 🔴 2026-09-05 就是這一類漏改打死了每天 12:20 的排程：tuple 恆為 truthy，
    #    `if not d` 不觸發、`d.get` 不存在，成功與失敗路徑**都** AttributeError。
    #    grep 只在 brain_alpha/ 裡找是抓不到 youtube_channel/ 那個呼叫端的。
    import re
    targets = [ROOT / "pick_next.py", ROOT / "submit_alpha.py",
               ROOT.parent.parent / "youtube_channel" / "scripts" / "brain_daily_pick.py"]
    call = re.compile(r"^\s*(?!#)(.*?)=\s*(?:[\w.]*\.)?poll_check\(")
    unpack = re.compile(r"^\s*\w+\s*,\s*\w+\s*$")
    seen = 0
    for t in targets:
        check("呼叫端檔案存在：%s" % t.name, t.exists(), str(t))
        if not t.exists():
            continue
        for i, line in enumerate(t.read_text(encoding="utf-8").splitlines(), 1):
            m = call.match(line)
            if not m or "poll_check =" in line:
                continue
            seen += 1
            check("%s:%d 解二元組" % (t.name, i), bool(unpack.match(m.group(1))), line.strip()[:70])
    check("真的掃到呼叫端了【陽性對照：正則沒寫死成永遠找不到】", seen >= 3, "找到 %d 個" % seen)

    # 🔴 第二個守衛：呼叫端不可以**自己再寫一次判定規則**。
    #    第三輪存活的變異就是這個：把 pick_next 的 `bad` 改回 `v[0] == "FAIL"`
    #    測試抓不到，因為第 9 節測的是函式庫 `B.non_pass`，而規則寫在 main() 行內。
    #    跟打死 cron 那次同型：規則活在沒有測試讀得到的呼叫端。
    inline = []
    for t in targets:
        if not t.exists():
            continue
        for i, line in enumerate(t.read_text(encoding="utf-8").splitlines(), 1):
            s = line.split("#")[0]
            if "ck.items()" in s and ('"FAIL"' in s or '"PASS"' in s):
                inline.append("%s:%d" % (t.name, i))
    check("沒有呼叫端自己比對 result（判定只能走 B.non_pass / B.check_verdict）",
          not inline, "違規：%s" % (inline or "無"))
    for t in targets:
        if t.exists():
            src_t = t.read_text(encoding="utf-8")
            check("%s 有走共用判定" % t.name,
                  ("non_pass(" in src_t) or ("check_verdict(" in src_t))

    print()
    print("=" * 74)
    print("12. 哨兵值與髒設定不可以變成「全部通過」或殺掉 import")
    print("=" * 74)
    # C'：parse_checks 用 None 表示「讀不到」。若 non_pass(None) 回 []，
    #     「讀不到」就等於「全部通過」—— 正是這整批要消滅的形狀。
    try:
        B.non_pass(None)
        check("non_pass(None) 會 raise（不可以回 []）", False, "竟然回了 %r" % (B.non_pass(None),))
    except ValueError:
        check("non_pass(None) 會 raise（不可以回 []）", True)
    except Exception as e:  # noqa: BLE001
        check("non_pass(None) 會 raise ValueError", False, repr(e))
    for junk in ("x", 5, [1]):
        try:
            B.non_pass(junk)
            check("non_pass(%r) 會 raise" % (junk,), False)
        except (TypeError, ValueError):
            check("non_pass(%r) 會 raise" % (junk,), True)

    # F'：「一項都不丟」沒有斷言 → 該變異存活，而它是承重的。
    mixed = json.dumps({"is": {"checks": [
        ck("LOW_SHARPE", "PASS", 2.0), "garbage", None, {"result": "PASS"}]}})
    pcm = B.parse_checks(json.loads(mixed)) or {}
    check("checks 有 4 項 → parse_checks 也要有 4 項（一項都不丟）",
          len(pcm) == 4, "實得 %d 項" % len(pcm))
    check("非 dict 項目 → 擋下（不是丟掉當作沒看到）",
          B.check_verdict(json.loads(mixed))[0] is False)
    # E'：show() 曾自己重讀 body，遇到非 dict 項目 AttributeError 崩掉。
    try:
        rc12 = gate(Resp(200, mixed))
    except AttributeError as e:  # noqa: BLE001
        rc12 = "AttributeError: %s" % e
    check("混入非 dict 項目 → 閘門正常擋下，不是吐 traceback",
          rc12 in (1, 3), "rc=%s" % rc12)

    # 額外1：deadline 環境變數的髒值不可以殺掉 import，也不可以靜默變成 0。
    import os as _os
    for raw, expect_default in [("abc", True), ("0", True), ("-5", True),
                                ("", True), ("0.5", True), ("300", False)]:
        _old = _os.environ.get("BRAIN_CHECK_DEADLINE")
        try:
            if raw == "":
                _os.environ.pop("BRAIN_CHECK_DEADLINE", None)
            else:
                _os.environ["BRAIN_CHECK_DEADLINE"] = raw
            v = B._env_deadline(180.0)
            good = (v == 180.0) if expect_default else (v == 300.0)
            check("BRAIN_CHECK_DEADLINE=%-5r → %s" % (raw, "退回預設" if expect_default else "採用"),
                  good and v > 0, "實得 %r" % (v,))
        finally:
            if _old is None:
                _os.environ.pop("BRAIN_CHECK_DEADLINE", None)
            else:
                _os.environ["BRAIN_CHECK_DEADLINE"] = _old

    # 🔴 會殺掉 cron 的是**模組層那一行** `CHECK_DEADLINE = _env_deadline()`，
    #    不是上面測的 helper。實測把它改回裸 float() 之後上面那組仍然全過 ——
    #    要抓得真的帶著髒 env import 一次。
    import subprocess
    for raw, want_die in [("abc", False), ("0", False), ("300", False)]:
        env = dict(_os.environ)
        env["BRAIN_CHECK_DEADLINE"] = raw
        env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run(
            [sys.executable, "-c", "import brain_auto as B; print(B.CHECK_DEADLINE)"],
            cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120)
        want = "300.0" if raw == "300" else "180.0"
        check("子行程帶 BRAIN_CHECK_DEADLINE=%-4s import → 不死且值合理" % raw,
              r.returncode == 0 and want in (r.stdout or ""),
              "rc=%s out=%r" % (r.returncode, (r.stdout or "").strip()[:40]))

    # A'(a)：告警要分得出 PENDING / FAIL —— non_pass 只回 key 不夠。
    rr = B.results_of(B.parse_checks(json.loads(B_PEND)))
    check("results_of 拿得到 result 本身（告警才分得出 PENDING vs FAIL）",
          rr.get("SELF_CORRELATION") == "PENDING", "實得 %r" % (rr,))

    print()
    print("=" * 74)
    print("11. 輪詢有整體 deadline（次數上限擋不住時間，等多久是平台決定的）")
    print("=" * 74)
    import time as _t
    t0 = _t.monotonic()
    d11, why11 = B.poll_check(Sess(Resp(200, B_PEND, retry_after="30")), "TESTID",
                              tries=35, deadline=1.0)
    el = _t.monotonic() - t0
    check("永遠 PENDING + Retry-After=30 → 1 秒 deadline 內收工",
          el < 5.0, "實耗 %.2f 秒（無 deadline 時上界 35×30=1050 秒）" % el)
    check("deadline 到了仍交出 body（由 verdict 判，不在這層二度攔截）", d11 is not None)
    check("deadline 停的要說出自己的名字（含 deadline 與放寬方式）",
          isinstance(why11, str) and "deadline" in why11 and "BRAIN_CHECK_DEADLINE" in why11,
          "實得 %r" % (why11,))
    # deadline 預設值是猜的（repo 內沒有真實 /check 耗時資料），所以必須可覆蓋 ——
    # 一個猜出來的常數如果太短，會靜默餓死挑片器而看起來像「今天沒有好候選」。
    check("deadline 可用環境變數覆蓋（不是寫死的常數）",
          isinstance(B.CHECK_DEADLINE, float))

    print()
    if FAILURES:
        print("✗ %d 項未通過：%s" % (len(FAILURES), "; ".join(FAILURES)))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    raise SystemExit(main())
