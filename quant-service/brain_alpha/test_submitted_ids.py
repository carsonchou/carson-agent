#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`submitted_ids` 的回歸測試(2026-09-05)。

## 為什麼有這支
`submitted_ids()` 原本寫成:

    out = set()
    r = s.get(...)
    if r.ok and r.text.strip():        # ← 只在成功路徑填
        for a in (r.json().get("results") or []):
            out.add(a.get("id"))
    return out                          # ← 無條件回傳,字面上不是空值

失敗時回**空集合**,而下游把空集合讀成「一條都還沒交」:
`cand` 不排除任何已提交的、`done_nums` 空 ⇒ **分子去重整個失效**
⇒ **建議重複提交**。一個名額換不回來,而 self-correlation 是這條線唯一
真正稀缺的資源。

「查不到」和「查到是空的」在下游長得一模一樣 —— 那一族的教科書形狀。
(`scripts/scan_ambiguous_zero.py` 的判準命中這一族,但**抓不到這一型**:
累加器初始化為空、只在成功路徑填、無條件回傳,字面上不是空值。已回報基建線,
見 `docs/ops/2026-09-05_brain_to_infra.md`。)

## 這支的設計原則
1. **陽性對照最重要的那格**:「查到了,而且真的是空的」→ **必須放行**。
   開站第一天就是這樣。少了這格,「一律中止」也會全綠。
2. **測 `main()` 那條真實路徑**,不是只測 helper。
3. **入口擋死真實登入**——今天這條線的測試曾真的連上平台
   (`B.auth()` 是真的 POST),而**獨立驗證員在指出這件事的同一份報告裡也犯了同一個錯**。
   規則只寫在派工單上時,違反它不產生任何輸出。見 `docs/ops/dispatch.md` §6。

    python test_submitted_ids.py        # 全過印 ALL PASS,任一失敗 exit 1
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import brain_auto as B   # noqa: E402
import pick_next as P    # noqa: E402


class _NoAuth:
    """入口擋死真實登入。cookies 給空 dict,任何誤用都不會打到平台。"""

    cookies: dict = {}


class Resp:
    def __init__(self, code, payload):
        self.status_code, self._p = code, payload

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    @property
    def text(self):
        return self._p if isinstance(self._p, str) else json.dumps(self._p)

    def json(self):
        return json.loads(self._p) if isinstance(self._p, str) else self._p


class Sess:
    """`payload` 同時當 count 查詢與分頁查詢的回應。

    平台契約(reconcile.py:18、:67-79):`?limit=1` 拿 `count`,
    再用 `limit=100&offset=` 分頁。stub 依 URL 分派,並記錄呼叫次數。
    """

    def __init__(self, payload, code=200, raise_on_get=False, count=None):
        self.payload, self.code, self.raise_on_get = payload, code, raise_on_get
        self.count, self.cookies, self.hits = count, {}, []

    def get(self, url, **k):
        self.hits.append(url)
        if self.raise_on_get:
            raise OSError("connection reset")
        if "limit=1&" in url or url.endswith("limit=1"):
            if self.count is None:
                return Resp(self.code, self.payload)
            return Resp(self.code, {"count": self.count})
        return Resp(self.code, self.payload)


def ids_payload(*aids):
    """正常回應:count 與 results 一致。"""
    return {"count": len(aids), "results": [{"id": a} for a in aids]}


def paged(n, per=100):
    """造一個 n 筆、需要分頁的 session(每頁 per 筆)。"""
    all_ids = ["A%d" % i for i in range(n)]

    class _P(Sess):
        def get(self, url, **k):
            self.hits.append(url)
            if "limit=1&" in url or url.endswith("limit=1"):
                return Resp(200, {"count": n})
            off = int(url.split("offset=")[1].split("&")[0])
            return Resp(200, {"count": n,
                              "results": [{"id": a} for a in all_ids[off:off + per]]})

    return _P(None)


FAILURES = []


def check(name, cond, detail=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  " + detail) if detail else ""))
    if not cond:
        FAILURES.append(name)


def run_pick_next(payload, code=200, ledger=None):
    """跑**真品** pick_next.main(),回 (rc, 螢幕輸出)。全 stub,不連網。"""
    orig = (B.auth, B.load_ledger, sys.argv)
    buf = io.StringIO()
    try:
        B.auth = lambda *a, **k: Sess(payload, code)
        P.B.auth = B.auth
        B.load_ledger = lambda *a, **k: (ledger or {})
        P.B.load_ledger = B.load_ledger
        sys.argv = ["pick_next.py", "--check", "0"]
        with redirect_stdout(buf):
            rc = P.main()
        return rc, buf.getvalue()
    finally:
        B.auth, B.load_ledger, sys.argv = orig
        P.B.auth, P.B.load_ledger = orig[0], orig[1]


def _main() -> int:
    print("=" * 74)
    print("1. 陽性對照 —— 沒有這兩格,「一律中止」也會全綠")
    print("=" * 74)
    ids, why = P.submitted_ids_ex(Sess(ids_payload("A1", "A2", "A3")))
    check("正常清單 → 抽得出全部 id、reason 是空字串",
          ids == {"A1", "A2", "A3"} and why == "", "實得 %r / %r" % (ids, why))
    # 🔴 這一格是整支測試最重要的:「查到了,而且真的是空的」是**合法狀態**
    #    (開站第一天)。把它當錯誤 = 從 fail-open 翻成「一定叫」,同樣是壞的。
    ids, why = P.submitted_ids_ex(Sess({"count": 0, "results": []}))
    check("查到了、而且真的是空的(count=0)→ **放行**(不是錯誤)",
          ids == set() and why == "", "實得 %r / %r" % (ids, why))

    print()
    print("=" * 74)
    print("2. 「沒問到」的每一種都要回 None + 說得出是哪一種")
    print("=" * 74)
    cases = [
        ("HTTP 401", {"detail": "x"}, 401, "HTTP 401"),
        ("HTTP 500", {"detail": "x"}, 500, "HTTP 500"),
        ("body 空白", "   ", 200, "回應 body 是空的"),
        ("非 JSON", "<html>502</html>", 200, "回傳不是 JSON"),
        ("body 是 list", "[]", 200, "回傳不是 dict"),
        ("body 是 null", "null", 200, "回傳不是 dict"),
        ("results 為 null", {"count": 2, "results": None}, 200, "offset=0 這一頁沒有 results"),
        ("沒有 results 鍵", {"count": 2, "other": 1}, 200, "offset=0 這一頁沒有 results"),
        ("results 不是 list", {"count": 2, "results": "x"}, 200, "offset=0 這一頁沒有 results"),
        ("count 缺", {"results": [{"id": "A1"}]}, 200, "count 不是非負整數"),
    ]
    for label, payload, code, want in cases:
        ids, why = P.submitted_ids_ex(Sess(payload, code))
        check("%-16s → ids is None" % label, ids is None, "實得 %r" % (ids,))
        check("%-16s → reason 說得出種類" % label,
              isinstance(why, str) and why.startswith(want), "實得 %r" % (why,))
    ids, why = P.submitted_ids_ex(Sess(None, raise_on_get=True))
    check("連線拋例外 → ids is None 且 reason 非空",
          ids is None and isinstance(why, str) and why.startswith("連線失敗"))

    print()
    print("=" * 74)
    print("3. 少掉的東西一定要被數出來(靜默丟掉 = 清單偏小 = 同一個 fail-open)")
    print("=" * 74)
    # 🔴 原本 `out.add(a.get("id"))` 對抽不出 id 的項目靜默丟掉;
    #    清單偏小 ⇒ 已提交的被當成沒交過 ⇒ 建議重複提交。
    for label, payload, want_ in [
            ("id 直接是字串", {"count": 2, "results": ["A1", "A2"]}, "抽不出 id"),
            ("有的項目沒有 id", {"count": 2, "results": [{"id": "A1"}, {"noid": 1}]}, "抽不出 id"),
            ("id 是 null", {"count": 2, "results": [{"id": "A1"}, {"id": None}]}, "抽不出 id"),
            ("id 是數字", {"count": 2, "results": [{"id": "A1"}, {"id": 7}]}, "抽不出 id"),
            ("id 是空字串", {"count": 2, "results": [{"id": "A1"}, {"id": ""}]}, "抽不出 id"),
            # 重複 id:形狀合法,但 count 說 2 而只收集到 1 個不重複 ⇒ 清單對不上
            ("重複的 id", {"count": 2, "results": [{"id": "A1"}, {"id": "A1"}]}, "對不上"),
    ]:
        ids, why = P.submitted_ids_ex(Sess(payload))
        check("%-14s → 擋下並說得出原因" % label,
              ids is None and want_ in (why or ""), "實得 %r / %r" % (ids, why))
    # 🔴 判準改用權威的 count,不是「剛好回滿 100 筆」這個代理訊號。
    #    獨立驗證員實測代理訊號會在下面這種形狀下靜默放行一份偏小的清單。
    ids, why = P.submitted_ids_ex(Sess({"count": 250, "results": [{"id": "A1"}] * 50}))
    check("count=250 但只回 50 筆 → 擋下(代理訊號會放行,count 不會)",
          ids is None and ("對不上" in (why or "") or "分頁次數異常" in (why or "")),
          "實得 %r / %r" % (ids, why))
    ids, why = P.submitted_ids_ex(Sess({"count": 3, "results": [{"id": "A1"}, {"id": "A2"}]}))
    check("count 與實得筆數不符 → 擋下", ids is None, "實得 %r" % (why,))
    sp = paged(250)
    ids, why = P.submitted_ids_ex(sp)
    check("250 筆 → **照分頁抓完**(舊版會因為「回滿 100」而中止)",
          ids is not None and len(ids) == 250, "實得 %s / %r" % (len(ids or []), why))
    check("而且真的翻了頁(count 查詢 1 次 + 3 頁)", len(sp.hits) == 4, "實得 %d 次" % len(sp.hits))
    ids, why = P.submitted_ids_ex(Sess({"count": 1001, "results": []}))
    check("count 超過單 query 上限 1000 → 擋下並指向 reconcile.py 的切片作法",
          ids is None and "reconcile.py" in (why or ""), "實得 %r" % (why,))
    for bad_c in (None, "3", -1, True):
        ids, why = P.submitted_ids_ex(Sess({"count": bad_c, "results": []}))
        check("count=%-5r → 擋下" % bad_c, ids is None, "實得 %r" % (why,))

    print()
    print("=" * 74)
    print("4. 薄包裝 submitted_ids 簽章不動(brain_daily_pick.py:68 靠它)")
    print("=" * 74)
    check("成功 → 回 set", P.submitted_ids(Sess(ids_payload("A1"))) == {"A1"})
    check("真空清單 → 回空 set 且**不警告**(那是合法狀態)",
          P.submitted_ids(Sess({"count": 0, "results": []})) == set())
    err = io.StringIO()
    _o, sys.stderr = sys.stderr, err
    try:
        v = P.submitted_ids(Sess({"detail": "x"}, 500))
    finally:
        sys.stderr = _o
    check("失敗 → 仍回 set()(不是 None、不是 tuple)",
          isinstance(v, set) and v == set(), "型別 %s" % type(v).__name__)
    check("但**不是靜默**:stderr 有 warn 且點名 fail-open",
          "取不到已提交清單" in err.getvalue() and "fail-open" in err.getvalue(),
          "stderr=%r" % err.getvalue()[:70])

    print()
    print("=" * 74)
    print("5. 決策路徑要中止(跑真品 pick_next.main)")
    print("=" * 74)
    rc, out = run_pick_next({"detail": "x"}, 500)
    check("取不到清單 → rc=2,不產出建議", rc == 2 and "→ 交這兩條" not in out, "rc=%s" % rc)
    check("而且明說「不是一條都還沒交,是沒問到」", "是沒問到" in out)
    rc, out = run_pick_next({"count": 0, "results": []})
    check("真的空清單 → **不中止**(開站第一天)【陽性對照】", rc != 2, "rc=%s" % rc)

    print()
    print("=" * 74)
    print("7. brain_daily_pick(cron 12:20)的執行期覆蓋")
    print("=" * 74)
    # 🔴 獨立驗證員指出:第 6 節是**對原始碼打正則、而且錨在變數名 `done`**,
    #    所以把變數改名 + 放一行假的 _ex 呼叫就能溜過去,而整支測試對
    #    brain_daily_pick.py **零執行期覆蓋**。這一節補上真的跑。
    sys.path.insert(0, str(ROOT.parent.parent / "youtube_channel" / "scripts"))
    import brain_daily_pick as DP  # noqa: E402

    def run_daily(payload, code=200):
        o = (B.auth, B.track_score, B.load_ledger, sys.argv)
        buf2 = io.StringIO()
        # 🔴 2026-09-08:候選池改成「帳本 ∪ 平台快照」之後,這一節如果不 stub 快照,
        #    它會拿**真實的 9,784 條**去組池 → spread 19 條 → `_prefilter` 對每條
        #    輪詢 PnL ⇒ 這個測試從幾秒變成跑不完。**症狀是掛住不是紅燈**,
        #    而掛住的測試和「還沒跑完」在 CI 上長得一樣。
        #    stub 成**小而有效**的快照:回 None 的話 daily_pick 會 fail-closed 中止,
        #    下面的陽性對照就會拿到 rc=2 —— 那是對的碼、錯的理由,綠燈就不是斷言給的。
        import reconcile as RC
        _ols = RC.load_snapshot
        RC.load_snapshot = lambda *a, **k: (
            {"L%d" % i: {"code": "ts_backfill(f%d/close, 120)" % i, "sharpe": 1.5,
                         "fitness": 1.0 - i * 0.1, "checks_n": 8, "fails": [],
                         "pending": [], "dc": "2026-09-01T00:00:00-04:00"}
             for i in range(2)},
            {"fetched_at": "stub", "count": 2, "expected": 2, "age_h": 0.0}, "")
        try:
            B.auth = lambda *a, **k: Sess(payload, code)
            B.track_score = lambda *a, **k: {"submitted_records": []}
            # 🔴 帳本**不可以是空的**:空帳本會讓 brain_daily_pick 先撞到
            #    pre-existing 的 `max() arg is an empty sequence`(在
            #    `if not picks:` 守門之前)⇒ 下面 `rc == 2` 那句**根本求值不到**,
            #    綠燈就不是斷言給的。獨立驗證員實測:fail-open 版 + 空帳本 → EXC
            #    斷言構不到;fail-open 版 + 有料帳本 → rc=0,斷言乾淨抓到。
            B.load_ledger = lambda *a, **k: {
                "k%d" % i: {"ok": True, "alpha_id": "L%d" % i,
                            "label": "x|ds%d|y" % i,
                            "expr": "ts_backfill(f%d/close, 120)" % i,
                            "result": {"evaluable_pass": True, "fitness": 1.0 - i * 0.1}}
                for i in range(2)}
            # brain_daily_pick 是在 main() **裡面**才 `import brain_auto as B`,
            # 所以沒有模組層的 DP.B —— 改 brain_auto 模組本身就夠了(它拿到的是
            # 同一個模組物件)。P 有模組層的別名,要另外同步。
            P.B.auth, P.B.track_score, P.B.load_ledger = (
                B.auth, B.track_score, B.load_ledger)
            # poll_check 交給 stub:這一節測的是 submitted_ids 那道閘,不是 /check。
            _op = P.poll_check
            P.poll_check = lambda *a, **k: (None, "stub:不打平台")
            sys.argv = ["brain_daily_pick.py", "--dry"]
            with redirect_stdout(buf2):
                rc = DP.main()
            return rc, buf2.getvalue()
        finally:
            P.poll_check = _op
            RC.load_snapshot = _ols
            B.auth, B.track_score, B.load_ledger, sys.argv = o
            P.B.auth, P.B.track_score, P.B.load_ledger = o[0], o[1], o[2]

    rc, out = run_daily({"detail": "x"}, 500)
    check("取不到已提交清單 → rc=2(cron 中止,不挑片)", rc == 2, "rc=%s" % rc)
    check("而且明說「不是一條都還沒交,是沒問到」", "是沒問到" in out, "out=%r" % out[-160:])
    check("--dry 下不真的推播", "[dry]" in out or "不推播" in out, "out=%r" % out[-160:])
    # 陽性對照:真的空清單不可以被 submitted_ids 那道閘擋下。
    # ⚠️ 上面的帳本 stub **必須非空**,否則會先撞到 pre-existing 的
    #    `brain_daily_pick.py:206` `max(len(v) for v in order)`
    #    (在 `:218` 的 `if not picks:` 守門**之前**,帳本空時拋 ValueError)——
    #    那樣的話下面 `rc == 2` 那句**求值不到**,綠燈就不是斷言給的。
    #    獨立驗證員實測過這件事;先前這裡寫的是 try/except 容忍 ValueError,
    #    那個寫法連同它的註解都已經拿掉。
    rc, out = run_daily({"count": 0, "results": []})
    check("真的空清單 → **不中止**(開站第一天)【陽性對照】", rc != 2, "rc=%s" % rc)

    # 🔴 8-1:`count` 現在被當成「ACTIVE 的筆數」在用(靠 settlement_probe.py:69
    #    與 reconcile.py:70 交叉確認)。但**沒有東西釘住 count 必須跟著 status 濾**。
    #    哪天平台把 count 改成不理 filter 的總數(無 filter 時實測 5,193,
    #    見 settlement_probe.py:20),`active_alpha_ids` 會拿到 >1000,然後每天
    #    12:20 固定回「count=5193 超過單 query 上限 1000」中止 —— 而那是個
    #    **看起來完全合理的錯誤訊息**,沒有人會想到根因是 count 的語意變了。
    probe = Sess(ids_payload("A1"))
    P.submitted_ids_ex(probe)
    count_urls = [u for u in probe.hits if "limit=1&" in u or u.endswith("limit=1")]
    check("count 查詢真的發出去了", len(count_urls) == 1, "實得 %r" % (probe.hits,))
    check("count 查詢必須帶 status=(否則 count 量的不是同一個母體)",
          all("status=" in u for u in count_urls), "實得 %r" % (count_urls,))
    check("分頁查詢也必須帶 status=",
          all("status=" in u for u in probe.hits), "實得 %r" % (probe.hits,))

    print()
    print("=" * 74)
    print("6. 迴歸守衛:做「排除已提交」的呼叫端不可以用薄包裝")
    print("=" * 74)
    # 🔴 我先前寫的規格漏掉 brain_daily_pick.py:160,而它和 pick_next.main()
    #    用法完全相同 —— 只看了 :68 的 _prefilter 就推廣到整個檔案。
    #    這格用**行為之外的機械檢查**守住:凡是把結果指派給 `done` 的,
    #    一律必須解二元組(即走 _ex)。
    import re
    targets = [ROOT / "pick_next.py",
               ROOT.parent.parent / "youtube_channel" / "scripts" / "brain_daily_pick.py"]
    seen = 0
    for t in targets:
        check("呼叫端檔案存在:%s" % t.name, t.exists(), str(t))
        if not t.exists():
            continue
        for i, line in enumerate(t.read_text(encoding="utf-8").splitlines(), 1):
            s_ = line.split("#")[0]
            m = re.match(r"^\s*done\s*(,\s*\w+)?\s*=\s*.*submitted_ids", s_)
            if not m:
                continue
            seen += 1
            check("%s:%d `done` 走 _ex 並解二元組" % (t.name, i),
                  bool(m.group(1)) and "submitted_ids_ex" in s_, s_.strip()[:70])
    check("真的掃到呼叫端了【陽性對照:正則沒寫死成永遠找不到】",
          seen >= 2, "找到 %d 個" % seen)

    print()
    if FAILURES:
        print("✗ %d 項未通過:%s" % (len(FAILURES), "; ".join(FAILURES)))
        return 1
    print("ALL PASS")
    return 0


def main() -> int:
    # 🔴 入口擋死真實登入。今天這條線的測試曾真的連上 WorldQuant,
    #    而獨立驗證員在指出這件事的同一份報告裡也犯了同一個錯 ——
    #    「不要連平台」只寫在派工單上時,違反它不產生任何輸出。
    _orig = B.auth
    B.auth = lambda *a, **k: _NoAuth()   # noqa: E731
    P.B.auth = B.auth
    try:
        return _main()
    finally:
        B.auth = _orig
        P.B.auth = _orig


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    raise SystemExit(main())
