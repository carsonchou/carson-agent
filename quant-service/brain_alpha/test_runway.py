#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""runway.py 的回歸測試(2026-09-05)。

## 為什麼有這支
`runway.py` 算「還剩幾條交得出去的 alpha」= 跑道天數。方法是拿候選的日 PnL
對「已提交的池子」算 Pearson 相關,低於 0.7 才算交得出去。
self-correlation 是這條線唯一真正稀缺的資源,所以**把該擋的收下**代價很高。

原缺陷:建池子時 `p = fetch_pnl(...); if p: pool.append(...)`,而 `fetch_pnl`
有 5 條路徑回 `None`。任一條已提交 alpha 抓失敗 → 從池子消失 → 候選對池子的
最大相關被低估 → 誤收。獨立驗證員在 `.bak` 上實測:9 種壞法讓
**0.9988 級的真相關被算成 0.0078,rejected → accepted**。

## 這支的設計原則(踩過才寫下來的)
1. **測 `main()` 那條真實路徑**,不是只測 helper。
2. **行為測試,不是字串 grep**。第一版第 8 節用 grep 守「corr 回 None 不可以跳過」,
   獨立驗證員換個字面把 fail-open 寫回去 → **測試全過**。字串守衛只能當補充。
3. **陽性對照兩格**:該擋的擋下 **+ 該放行的仍放行**。只有前者的話,
   「一律中止」也會全綠。
4. **性質測試防錯位**:凡是 fetch 收下的最短序列,`corr` 一定算得出來。
   這樣換掉任何字面常數都抓得到(第一版就是 fetch 收 99 個差分而 corr 要 100)。

    python test_runway.py        # 全過印 ALL PASS,任一失敗 exit 1
"""
from __future__ import annotations

import io
import json
import random
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import brain_auto as B   # noqa: E402
import runway as R       # noqa: E402


class _NoAuth:
    """🔴 全域擋掉真實登入。

    `fetch_pnl_ex` 在收到 401 時會 `s.cookies.update(B.auth().cookies)` 重取 cookie。
    第一版沒有在模組層擋住 `B.auth`,於是測 401 那格**真的連上了 WorldQuant**
    (平台回 `400 {"captcha":["This field is required."]}`)。
    **測試碰得到正式帳號這件事,不可以靠每個區塊自己記得 stub。**
    `main()` 一開頭就把 `B.auth` 換成這個、`finally` 還原;`run()` 需要時再覆蓋
    成自己的 stub session。(不放模組層,否則任何 `import test_runway` 的程序
    都會被永久改掉 `B.auth`。)
    """

    cookies: dict = {}


random.seed(11)
N = 400
BASE = [random.gauss(0, 1) for _ in range(N)]        # 池成員 A_HIGH
OTHER = [random.gauss(0, 1) for _ in range(N)]       # 池成員 A_LOW
TWIN = [b + random.gauss(0, 0.05) for b in BASE]     # 候選:幾乎等於 A_HIGH
INDEP = [random.gauss(0, 1) for _ in range(N)]       # 候選:和誰都不像


def cumul(diffs):
    """runway 吃 [date, 累計 pnl] 再自己做差分,所以這裡要反過來累加。"""
    out, acc = [], 0.0
    for i, d in enumerate(diffs):
        acc += d
        out.append(["2025-%02d-%02d" % (i // 28 + 1, i % 28 + 1), acc])
    return out


PNL = {
    "A_HIGH": cumul(BASE), "A_LOW": cumul(OTHER),
    "C_TWIN": cumul(TWIN), "C_INDEP": cumul(INDEP),
    "A_THIN": cumul(BASE[:40]),                 # 觀測數不足
    "A_FLAT": cumul([0.0] * N),                 # 零變異
    "C_FLAT": cumul([0.0] * N),
    # 🔴 +1:N 列 records 只產生 N-1 個差分。這一格就是為了抓這種差一而寫的,
    #    而我第一版把它寫成 [:MIN_OBS] —— 它立刻 FAIL,證明這格對差一有反應。
    "A_EXACT": cumul(BASE[:R.MIN_OBS + 1]),     # 剛好 MIN_OBS 個差分
    "C_EXACT": cumul(OTHER[:R.MIN_OBS + 1]),
    # 🔴 整條有變異(前 300 天在動)但**最後 MIN_OBS 天完全沒動**。
    #    usable() 量整條 → True;corr() 截成最後 n 筆 → 該窗口變異 0 → 回 None。
    #    這就是「usable 是 corr 回 None 的補集」那個假不變式的反例。
    "A_TAILFLAT": cumul(BASE[:300] + [0.0] * R.MIN_OBS),
}
# 多個「確定撞」的候選,用來測告警會不會在本線的**常態**下常駐。
for _i in range(5):
    PNL["C_T%d" % _i] = cumul([b + random.gauss(0, 0.05) for b in BASE])


class Resp:
    def __init__(self, code, payload, retry_after="0"):
        self.status_code, self._p = code, payload
        self.headers = {"Retry-After": retry_after}

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    @property
    def text(self):
        return self._p if isinstance(self._p, str) else json.dumps(self._p)

    def json(self):
        return json.loads(self._p) if isinstance(self._p, str) else self._p


class Sess:
    """`broken[aid]` 可以是 HTTP 碼(int)或整個 payload(dict/str)。"""

    def __init__(self, active, broken=None, list_payload=None, list_code=200):
        self.active, self.broken = list(active), dict(broken or {})
        self.list_payload, self.list_code = list_payload, list_code
        self.cookies, self.hits = {}, {}

    def get(self, url, **k):
        if "/users/self/alphas" in url:
            # 平台契約(reconcile.py:18、:67-79):`?limit=1` 拿權威的 count,
            # 再用 `limit=100&offset=` 分頁。2026-09-05 起 runway 走
            # brain_auto.active_alpha_ids,所以 stub 也要照這個契約回。
            if self.list_payload is not None:
                return Resp(self.list_code, self.list_payload)
            if "limit=1&" in url or url.endswith("limit=1"):
                return Resp(self.list_code, {"count": len(self.active)})
            off = int(url.split("offset=")[1].split("&")[0]) if "offset=" in url else 0
            return Resp(self.list_code, {
                "count": len(self.active),
                "results": [{"id": a} for a in self.active[off:off + 100]]})
        aid = url.split("/alphas/")[1].split("/")[0]
        self.hits[aid] = self.hits.get(aid, 0) + 1
        if aid in self.broken:
            b = self.broken[aid]
            return Resp(b, {"detail": "nope"}) if isinstance(b, int) else Resp(200, b)
        return Resp(200, {"records": PNL[aid]})


def ledger(*cands):
    return {"k%d" % i: {
        "ok": True, "alpha_id": a,
        "expr": "ts_backfill(field_%s/close, 120)" % a.lower(),
        "result": {"evaluable_pass": True, "fitness": 1.5 - i * 0.1},
    } for i, a in enumerate(cands)}


class NoSleep:
    """停掉退避。測邏輯不測計時。

    ⚠️ 時間上界由 `runway.FETCH_DEADLINE`(牆鐘,預設 90 秒/條)決定,**不是**由
       重試次數決定 —— 每次要等多久是對方的 `Retry-After` 給的。
       (舊註解寫「最多 125 秒/條 ≈ 2 小時」,那是加 deadline 之前的數字,已作廢;
       獨立驗證員實測未設限時最壞是 360 秒/條、runway 73 條 ⇒ 7.3 小時。)
       第 7c 節有一格**故意用真的 sleep**,證明 deadline 真的夾住等待、
       不是被這個 stub 遮住。
    """

    def __init__(self, mod):
        self.mod, self.orig = mod, mod.time.sleep

    def __enter__(self):
        self.mod.time.sleep = lambda _: None
        return self

    def __exit__(self, *a):
        self.mod.time.sleep = self.orig


FAILURES = []
LAST_CACHE = None


def check(name, cond, detail=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  " + detail) if detail else ""))
    if not cond:
        FAILURES.append(name)


def plat_snapshot(*cands):
    """把 fixture 候選做成一份**平台快照**。

    🔴 2026-09-08:`runway` 的候選池改成「帳本 ∪ 平台快照」之後,不 stub 快照的話
       它會拿**真實的 9,784 條**組池,於是問一條 fixture 不認識的 alpha 的 PnL ⇒
       `KeyError`。那個紅燈長得像「runway 壞了」,實際是測試沒跟上池子的定義。
    ⚠️ 不可以 stub 成 `None` 或空 dict:前者讓 `main()` 直接 fail-closed 回 2,
       後者被 `load_snapshot()` 判成「0 筆快照」也回 None —— 兩種都會讓下面每一格
       拿到**對的碼、錯的理由**。
    """
    return {a: {"code": "ts_backfill(field_%s/close, 120)" % a.lower(),
                "sharpe": 1.5, "fitness": 1.5 - i * 0.1, "checks_n": 8,
                "fails": [], "pending": [], "dc": "2026-09-01T00:00:00-04:00",
                "status": "UNSUBMITTED"}
            for i, a in enumerate(cands)}


def run(active, cands, broken=None, argv=(), **kw):
    """跑**真品** runway.main(),回 (rc, 螢幕輸出)。全 stub,不連網、不真睡。"""
    import reconcile as RC
    orig = (B.auth, B.load_ledger, R.CACHE, sys.argv, RC.load_snapshot)
    buf = io.StringIO()
    ns = NoSleep(R); ns.__enter__()
    try:
        sess = Sess(active, broken, **kw)
        B.auth = lambda *a, **k: sess
        R.B.auth = B.auth
        B.load_ledger = lambda *a, **k: ledger(*cands)
        R.B.load_ledger = B.load_ledger
        # 平台側給同一批 fixture:池子 = 帳本 ∪ 平台,兩邊給同一組才等於原本的意圖。
        RC.load_snapshot = lambda *a, **k: (
            plat_snapshot(*cands),
            {"fetched_at": "stub", "count": len(cands), "expected": len(cands),
             "age_h": 0.0}, "")
        global LAST_CACHE
        LAST_CACHE = R.CACHE = Path(tempfile.mkdtemp()) / "pnl_cache.json"
        sys.argv = ["runway.py"] + list(argv)
        with redirect_stdout(buf):
            rc = R.main()
        return rc, buf.getvalue()
    finally:
        ns.__exit__()
        B.auth, B.load_ledger, R.CACHE, sys.argv = orig[:4]
        RC.load_snapshot = orig[4]
        R.B.auth, R.B.load_ledger = orig[0], orig[1]


def _sum_buckets(out):
    """從輸出解析四類數字。**正面式對帳**:斷言四類相加 == 候選數。

    🔴 原本第 5 節寫的是 `"對帳不符" not in out`(否定式)——
       把整段對帳 print 刪掉一樣會過。改成正面式之後,未來真有人漏掉一類會 FAIL。
       它仍然抓不到「把 print 整行刪掉」,那沒關係,寫清楚就好。
    """
    import re as _re
    m = _re.search(r"安全可交 (\d+) 條 \| 測不準 (\d+) 條 \| 確定撞 (\d+) 條 \| 沒量到 (\d+) 條", out)
    return None if not m else tuple(int(x) for x in m.groups())


def main() -> int:
    _orig_auth = B.auth
    B.auth = lambda *a, **k: _NoAuth()      # noqa: E731
    R.B.auth = B.auth
    try:
        return _main()
    finally:
        B.auth = _orig_auth
        R.B.auth = _orig_auth


def _main() -> int:
    print("=" * 76)
    print("1. 陽性對照 —— 沒有這兩格,「一律中止」也會全綠")
    print("=" * 76)
    rc, out = run(["A_HIGH", "A_LOW"], ["C_INDEP"])
    check("池子完整 + 候選不相關 → rc=0 且列入安全可交",
          rc == 0 and "安全可交 1 條" in out, "rc=%s" % rc)
    rc, out = run(["A_HIGH", "A_LOW"], ["C_TWIN"])
    check("池子完整 + 候選幾乎等於已提交的 → 確定撞(正確答案)",
          rc == 0 and "確定撞 1 條" in out, "rc=%s" % rc)
    rc, out = run(["A_HIGH", "A_LOW"], ["C_TWIN", "C_INDEP"])
    check("一好一壞 → 各歸各類", rc == 0 and "安全可交 1 條" in out and "確定撞 1 條" in out)

    print()
    print("=" * 76)
    print("2. 核心迴歸 —— 池子少一條不可以把 rejected 翻成 accepted")
    print("=" * 76)
    # 🔴 前四種是 HTTP 錯誤;後七種是 **HTTP 200 但 records 給不出資料** ——
    #    第一版把它們歸成我自己新發明的「資料不足」類別,排除掉並印
    #    「（真實資料條件，不影響判斷）」,而該候選對它的真相關是 ~1.0。
    #    用一條新路徑重造了同一個 bug。
    bad_bodies = {
        "HTTP 401": 401, "HTTP 500": 500, "HTTP 502": 502, "HTTP 429": 429,
        "records 空陣列": {"records": []},
        "records 為 null": {"records": None},
        "沒有 records 鍵": {"schema": {}},
        "records 只有 1 列": {"records": PNL["A_HIGH"][:1]},
        "records 只有 50 列": {"records": PNL["A_HIGH"][:50]},
        "200 帶 error": {"error": "boom"},
        "records 不是 list": {"records": "x"},
    }
    for label, body in bad_bodies.items():
        rc, out = run(["A_HIGH", "A_LOW"], ["C_TWIN"], broken={"A_HIGH": body})
        check("A_HIGH → %-16s → 中止 rc=2" % label, rc == 2, "rc=%s" % rc)
        check("A_HIGH → %-16s → 不產出任何 accept" % label,
              "安全可交" not in out and "不影響判斷" not in out)

    print()
    print("=" * 76)
    print("3. 「資料不足」也算池子不完整 —— 排除它 ≠ 它不影響結果")
    print("=" * 76)
    rc, out = run(["A_HIGH", "A_LOW", "A_THIN"], ["C_TWIN"])
    check("池子有一條觀測數不足 → 一樣中止 (rc=2)", rc == 2, "rc=%s" % rc)
    check("但理由分得出來(說得出是資料不足,不是沒量到)",
          "A_THIN" in out and "資料不足" in out)
    check("而且明說『排除它不等於它不影響結果』", "不等於它不影響結果" in out)
    rc, out = run(["A_HIGH", "A_LOW", "A_FLAT"], ["C_TWIN"])
    check("池子有零變異成員 → 中止,且說得出是零變異",
          rc == 2 and "零變異" in out, "rc=%s" % rc)

    print()
    print("=" * 76)
    print("4. --allow-incomplete-pool:可以硬跑,但輸出必須被標記")
    print("=" * 76)
    rc, out = run(["A_HIGH", "A_LOW"], ["C_TWIN"], broken={"A_HIGH": 500},
                  argv=["--allow-incomplete-pool"])
    check("加旗標 → 跑完 (rc=0)", rc == 0, "rc=%s" % rc)
    check("輸出明寫偏樂觀、不可直接拿去提交", "偏樂觀" in out and "不可直接" in out)
    check("⚠️ 而它確實會誤收(這正是原本的無聲行為,現在被標記了)",
          "安全可交 1 條" in out)

    print()
    print("=" * 76)
    print("5. 候選自己沒量到 → 不可以靜默消失(分母會悄悄變小)")
    print("=" * 76)
    rc, out = run(["A_HIGH", "A_LOW"], ["C_TWIN", "C_INDEP"], broken={"C_INDEP": 502})
    check("候選抓不到 → 列進『沒量到』而不是消失", "沒量到 1 條" in out)
    check("並且明說『不是確定撞,是沒問到』", "是沒問到" in out)
    b = _sum_buckets(out)
    check("四類合計 == 候選數【正面式對帳,不是 `\"對帳不符\" not in out`】",
          b is not None and sum(b) == 2, "實得 %r" % (b,))
    check("而且沒有對帳警告", "對帳不符" not in out)
    rc, out = run(["A_HIGH", "A_LOW"], ["C_TWIN", "C_FLAT"])
    check("零變異候選 → 歸沒量到,不毒化其他候選",
          rc == 0 and "沒量到 1 條" in out and "確定撞 1 條" in out, "rc=%s" % rc)
    check("零變異候選不會觸發 degenerate 告警(usable 在源頭擋掉了)",
          "理論上應該是 0" not in out)

    print()
    print("=" * 76)
    print("6. 性質測試:fetch 收下的最短序列,corr 一定算得出來")
    print("=" * 76)
    # 🔴 換掉任何字面常數都抓得到。第一版就是 fetch 收 99 個差分而 corr 要 100,
    #    導致剛好 100 筆 recs 的 alpha 讓 corr **恆回 None**。
    with NoSleep(R):
        d_exact, why_exact = R.fetch_pnl_ex(Sess(["A_EXACT"]), "A_EXACT", {})
        d_other, _ = R.fetch_pnl_ex(Sess(["C_EXACT"]), "C_EXACT", {})
    check("剛好 MIN_OBS 個差分 → fetch 收下", d_exact is not None, "why=%r" % (why_exact,))
    check("而 corr 對它算得出來(判準沒有錯開)",
          d_exact is not None and R.corr(d_exact, d_other) is not None)
    check("usable() 與 corr() 判準一致:usable 為真 ⇒ corr 非 None",
          R.usable(d_exact) and R.corr(d_exact, d_other) is not None)
    check("少一個就不收【陽性對照:門檻真的在動】",
          R.usable((d_exact or [])[:R.MIN_OBS - 1]) is False)

    print()
    print("=" * 76)
    print("7. 清單端點:results 給不出陣列不可以變成空池子")
    print("=" * 76)
    # 🔴 原本 `(r.json().get("results") or [])` —— null/缺鍵靜默變空清單
    #    ⇒ 池子空 ⇒ 每個候選最大相關 0 ⇒ **全部 accepted**。
    for label, payload, code in [
            ("HTTP 500", {"detail": "x"}, 500),
            ("results 為 null", {"count": 2, "results": None}, 200),
            ("沒有 results 鍵", {"count": 2, "other": 1}, 200),
            ("回傳不是 dict", "[]", 200)]:
        rc, out = run([], ["C_TWIN"], list_payload=payload, list_code=code)
        check("清單 %-14s → 中止 rc=2" % label, rc == 2, "rc=%s" % rc)
    # 🔴 2026-09-05:判準從「回滿 100 筆」這個代理訊號改成權威的 count。
    #    代理訊號在 {"count":250,"results":[50 筆]} 下會靜默放行一份偏小的池子,
    #    而池子偏小正是這支要修的 fail-open。
    rc, out = run([], ["C_TWIN"], list_payload={"count": 250, "results": [{"id": "A_HIGH"}] * 50})
    check("count=250 但只回 50 筆 → 中止(代理訊號會放行)", rc == 2, "rc=%s" % rc)
    rc, out = run([], ["C_TWIN"], list_payload={"count": 1001, "results": []})
    check("count 超過單 query 上限 1000 → 中止並指向 reconcile.py 的切片作法",
          rc == 2 and "reconcile.py" in out, "rc=%s" % rc)

    rc, out = run([], ["C_TWIN"], list_payload={"count": 2, "results": ["A_HIGH", "A_LOW"]})
    check("results 是 list 但每筆抽不出 id → 中止(不可以變成空池子)",
          rc == 2 and "抽不出 id" in out, "rc=%s" % rc)
    rc, out = run([], ["C_TWIN"], list_payload={
        "count": 3, "results": [{"id": "A_HIGH"}, {"noid": 1}, {"noid": 2}]})
    check("部分項目抽不出 id → 一樣中止(少掉的要被數出來)",
          rc == 2 and "抽不出 id" in out, "rc=%s" % rc)

    print()
    print("=" * 76)
    print("7b. corr 回 None 是資料條件 —— 不是「不相關」也不是 bug")
    print("=" * 76)
    # 🔴 這一格同時蓋掉獨立驗證員指出仍然存活的兩個變異:
    #    v2b(把 corr-None 的 fail-open 換個字面寫回去)、v12(拿掉那條告警)。
    #    反例本身也是它給的:usable() 量整條、corr() 量最後 n 筆,兩者必然分歧。
    check("反例成立:兩邊 usable 都為真,而 corr 回 None",
          R.usable(BASE[:300] + [0.0] * R.MIN_OBS)
          and R.usable(OTHER[:R.MIN_OBS])
          and R.corr(OTHER[:R.MIN_OBS], BASE[:300] + [0.0] * R.MIN_OBS) is None)
    rc, out = run(["A_TAILFLAT"], ["C_EXACT"])
    check("量不到的候選 → 歸『沒量到』,不是 accepted", "沒量到 1 條" in out)
    check("而且**不是** accepted(舊行為會把它收下)", "安全可交 0 條" in out)
    check("理由指名是哪一條池成員",
          "A_TAILFLAT" in out and "比較視窗內零變異" in out)
    check("告警說這是資料條件,不是 bug",
          "這是資料條件" in out and "不是 bug" in out)
    check("不再宣稱『理論上應該是 0』(那句話是被推翻的假不變式)",
          "理論上應該是 0" not in out)

    print()
    print("=" * 76)
    print("7c. 牆鐘 deadline —— 次數上限擋不住時間成本")
    print("=" * 76)
    # 🔴 「空 records 要重試」是本次新增的成本:最壞 6 次 × Retry-After 60 = 360 秒/條。
    #    而 brain_daily_pick(cron 12:20、15:00 結算)共用 fetch_pnl,19 條 ⇒ 1.9 小時。
    with NoSleep(R):
        _, why_dl = R.fetch_pnl_ex(Sess(["A_HIGH"], {"A_HIGH": {"records": []}}),
                                   "A_HIGH", {}, deadline=0)
        check("deadline 到期 → 立刻收工且說得出是 deadline",
              isinstance(why_dl, str) and "超過" in why_dl and "秒" in why_dl,
              "實得 %r" % (why_dl,))
        d_ok2, why_ok2 = R.fetch_pnl_ex(Sess(["A_HIGH"]), "A_HIGH", {}, deadline=90)
        check("正常情況不受影響【陽性對照】", d_ok2 is not None and why_ok2 == "")
    # 這一格**故意用真的 sleep**:要證明 deadline 真的夾住了等待,不是被 stub 遮住。
    import time as _t
    t0 = _t.monotonic()
    sess = Sess(["A_HIGH"], {"A_HIGH": {"records": []}})
    # 🔴 覆蓋 get 的時候要**保留計次**:第一版寫成純 lambda,結果 sess.hits 一直是
    #    空的,下面那格的對帳讀到 None —— 測試替身把要對帳的東西一起蓋掉了。
    def _get_ra30(url, **k):
        sess.hits["A_HIGH"] = sess.hits.get("A_HIGH", 0) + 1
        return Resp(200, {"records": []}, retry_after="30")
    sess.get = _get_ra30
    _, why_m = R.fetch_pnl_ex(sess, "A_HIGH", {}, deadline=0.6)
    el = _t.monotonic() - t0
    # 🔴 這個 deadline 是暫定值,**第一次真的撞到就是唯一一次免費的量測機會**。
    #    只說「超過 90 秒」的話,下一個人知道不夠卻不知道要調到多少。
    check("逾時訊息帶得出「試了幾次」與「伺服器要求等多久」",
          "試了" in why_m and "伺服器最後要求等 30" in why_m, "實得 %r" % (why_m,))
    # 🔴 次數本身要對帳,不能只驗字樣存在:把 `attempt` 寫成 `attempt + 1` 的差一
    #    測試會抓不到,而這個數字的用途正是給下一個人算 deadline 該調到多少 ——
    #    錯一次就少算一輪。不寫死「試了 2 次」(那是 timing 相依、會 flaky),
    #    改成和 session 實際發出的 GET 次數對帳。
    check("「試了 N 次」的 N == session 實際 GET 次數(差一會被抓到)",
          ("試了 %d 次" % sess.hits.get("A_HIGH", -1)) in why_m,
          "訊息=%r 實際 GET=%s" % (why_m, sess.hits.get("A_HIGH")))
    check("真的 sleep + Retry-After=30 → 0.6 秒 deadline 內收工",
          el < 4.0, "實耗 %.2f 秒(無 deadline 時 6×30=180 秒)" % el)
    check("FETCH_DEADLINE 是正數常數(不是靠環境變數在 import 期 float)",
          isinstance(R.FETCH_DEADLINE, float) and R.FETCH_DEADLINE > 0)

    print()
    print("=" * 76)
    print("7d. 中止訊息分「重跑會好」與「重跑不會好」")
    print("=" * 76)
    rc, out = run(["A_HIGH", "A_LOW"], ["C_TWIN"], broken={"A_HIGH": 500})
    check("暫時性失敗 → 歸『重跑會好』", "重跑會好" in out and "重跑不會好" not in out)
    rc, out = run(["A_HIGH", "A_LOW", "A_THIN"], ["C_TWIN"])
    check("永久性資料條件 → 歸『重跑不會好』", "重跑不會好" in out)
    check("並提示不要每次都帶旗標", "不要每次都帶旗標" in out)

    print()
    print("=" * 76)
    print("8. 簽章沒動 —— brain_daily_pick.py(cron 12:20)靠這四個")
    print("=" * 76)
    s = Sess(["A_HIGH"])
    v = R.fetch_pnl(s, "A_HIGH", {})
    check("fetch_pnl 仍回 list(不是 tuple;tuple 恆為 truthy 會讓相關度全歸零)",
          isinstance(v, list) and len(v) >= R.MIN_OBS, "型別 %s" % type(v).__name__)
    with NoSleep(R):
        check("fetch_pnl 失敗仍回 None",
              R.fetch_pnl(Sess(["A_HIGH"], {"A_HIGH": 500}), "A_HIGH", {}) is None)
        d_ex, why_ex = R.fetch_pnl_ex(Sess(["A_HIGH"], {"A_HIGH": 500}), "A_HIGH", {})
        check("fetch_pnl_ex 契約:data is None ⟺ reason 非空",
              d_ex is None and isinstance(why_ex, str) and why_ex != "")
        d_ok, why_ok = R.fetch_pnl_ex(Sess(["A_HIGH"]), "A_HIGH", {})
        check("成功時 reason 是空字串【陽性對照】", d_ok is not None and why_ok == "")
    check("load_cache 仍回 dict", isinstance(R.load_cache(), dict))
    check("corr 仍回 float / None",
          isinstance(R.corr(BASE, TWIN), float) and R.corr(BASE[:5], TWIN[:5]) is None)
    check("brain_daily_pick 的用法 abs(corr(d,e) or 1) 仍算得出來【陽性對照】",
          abs(R.corr(v, v) or 1) > 0.99)
    check("_retry_after 沒有第二份實作(統一用 brain_auto 那支)",
          not hasattr(R, "_retry_after") and "B._retry_after" in
          (ROOT / "runway.py").read_text(encoding="utf-8"))

    print()
    print("=" * 76)
    print("9. 三條耗盡路徑的 reason 要分得出來 + 非同步空 records 要重試")
    print("=" * 76)
    with NoSleep(R):
        reasons = {}
        for label, body in [("429", 429), ("401", 401),
                            ("空 body", ""), ("空 records", {"records": []})]:
            sess = Sess(["A_HIGH"], {"A_HIGH": body})
            _, why = R.fetch_pnl_ex(sess, "A_HIGH", {})
            reasons[label] = why
            check("%-10s → 重試到用完(打了 6 次)" % label,
                  sess.hits.get("A_HIGH") == 6, "實得 %s 次" % sess.hits.get("A_HIGH"))
        check("四種耗盡路徑的 reason 互不相同(不可以共用一句)",
              len(set(reasons.values())) == 4, "實得 %d 種" % len(set(reasons.values())))
        check("空 records 的 reason 說得出是非同步端點尚未算好",
              "非同步" in reasons["空 records"], "實得 %r" % reasons["空 records"])
        sess = Sess(["A_HIGH"])
        R.fetch_pnl_ex(sess, "A_HIGH", {})
        check("正常一次就拿到【陽性對照:重試不是永遠都在跑】",
              sess.hits.get("A_HIGH") == 1)

    print()
    print("=" * 76)
    print("10. 快取條目驗證要驗全部元素,而且 bool 不算數字")
    print("=" * 76)
    # 🔴 第一版只檢查前 5 個 ⇒ [1.0]*5+[None]*495 原樣回傳 → corr 丟 TypeError。
    #    而 isinstance(True, int) 為真 ⇒ [True]*500 也被收下。
    poisoned = {
        "前 5 個是數字、其餘 None": [1.0] * 5 + [None] * (N - 5),
        "全是 bool": [True] * N,
        "混入字串": [1.0] * (N - 1) + ["x"],
        "不是 list": "x" * N,
        "太短": [1.0] * 5,
    }
    for label, bad in poisoned.items():
        check("快取 %-22s → 不採用(重抓)" % label, R._clean_series(bad) is None)
    check("正常快取條目照常採用【陽性對照】",
          R._clean_series([1.0] * N) is not None)
    with NoSleep(R):
        sess = Sess(["A_HIGH"])
        cache = {"A_HIGH": [1.0] * 5 + [None] * (N - 5)}
        d, _ = R.fetch_pnl_ex(sess, "A_HIGH", cache)
        check("汙染的快取 → 丟掉重抓,不是原樣回傳", d is not None and None not in d)

    print()
    print("=" * 76)
    print("11. 快取寫入:壞掉要說話;不可以先截斷再序列化")
    print("=" * 76)
    orig_cache, _o = R.CACHE, sys.stderr
    try:
        R.CACHE = Path(tempfile.mkdtemp()) / "pnl_cache.json"
        check("不存在 → 空 dict,不吵", R.load_cache() == {})
        R.CACHE.write_text("{ 壞掉的 json", encoding="utf-8")
        err = io.StringIO(); sys.stderr = err
        try:
            c = R.load_cache()
        finally:
            sys.stderr = _o
        check("壞掉 → 回空 dict 但有 warn(不是靜默)",
              c == {} and "讀不得" in err.getvalue())
        R.CACHE.write_text('{"keep": [1, 2, 3]}', encoding="utf-8")
        before = R.CACHE.read_text(encoding="utf-8")
        err = io.StringIO(); sys.stderr = err
        try:
            R.save_cache({"bad": {1, 2}})        # set 不能 JSON 序列化
        finally:
            sys.stderr = _o
        check("序列化失敗 → 原檔一字未動(不是 0 bytes)",
              R.CACHE.read_text(encoding="utf-8") == before)
        check("而且有 warn", "序列化失敗" in err.getvalue())
        R.save_cache({"ok": [1, 2]})
        check("正常寫入照常成功【陽性對照】",
              json.loads(R.CACHE.read_text(encoding="utf-8")) == {"ok": [1, 2]})
    finally:
        R.CACHE, sys.stderr = orig_cache, _o

    print()
    print("=" * 76)
    print("12. 空池子 / 跑道數字被誤讀 / 走 continue 也要存快取")
    print("=" * 76)
    rc, out = run([], ["C_TWIN", "C_INDEP"], list_payload={"count": 0, "results": []})
    check("平台誠實回報零提交 → **不中止**(那時全部安全就是正確答案)", rc == 0, "rc=%s" % rc)
    check("但要明說這個結果沒有判別力", "沒有判別力" in out)
    b = _sum_buckets(out)
    check("空池子時四類仍然對得起來", b is not None and sum(b) == 2, "實得 %r" % (b,))

    # 🔴 陰性對照:本線的**常態**是「0 安全 / N 確定撞」(hybrid_miner.py:6 記著
    #    「fitness 前 50 的候選裡 48 條確定撞、0 條安全」)。第一版的條件寫成
    #    `unassessed > accepted`,在 accepted=0 時任何一條沒量到都會觸發 ⇒
    #    這個 ⚠️ 幾乎每次真跑都出現、退化成常駐雜訊。告警的價值等於它沉默得夠多。
    rc, out = run(["A_HIGH"], ["C_T0", "C_T1", "C_T2", "C_T3", "C_T4", "C_INDEP"],
                  broken={"C_INDEP": 502})
    check("5 撞 + 1 沒量到(本線常態)→ **不可以**印那個 ⚠️",
          "確定撞 5 條" in out and "沒量到 1 條" in out and "下界中的下界" not in out)
    # 陽性對照:真的大部分沒量到才該叫。
    rc, out = run(["A_HIGH"], ["C_T0", "C_T1", "C_T2", "C_INDEP"],
                  broken={"C_T1": 502, "C_T2": 502, "C_INDEP": 502})
    check("1 量到 + 3 沒量到 → 要印那個 ⚠️【陽性對照】", "下界中的下界" in out)
    check("而且比的是『量到的』不是『安全可交的』",
          "沒量到的（3）" in out and "量到的（1）" in out)
    # ⚠️ 這一輪是下面那格的前提(LAST_CACHE 是全域,取最後一次 run)。
    #    我上一版把它換成別的對照組,結果打壞了下面的斷言 —— 改區塊要看下游。
    rc, out = run(["A_TAILFLAT"], ["C_EXACT"])
    check("走 window-blind 的 continue 之後,快取仍然被存下來(不是白抓)",
          LAST_CACHE is not None and LAST_CACHE.exists()
          and "C_EXACT" in json.loads(LAST_CACHE.read_text(encoding="utf-8")),
          "cache=%s" % (LAST_CACHE.exists() if LAST_CACHE else None))

    print()
    if FAILURES:
        print("✗ %d 項未通過:%s" % (len(FAILURES), "; ".join(FAILURES)))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    raise SystemExit(main())
