# -*- coding: utf-8 -*-
"""13 支設 private 的執行腳本 —— 預設 dry-run;只有 --apply 才送 videos.update。

寫法照抄隔壁上過正式機的 youtube_channel/scripts/zombie_sweep.py:413-415
(07-15 用同一種寫法設過 17 支 private):
    status = dict(m["status"]); status["privacyStatus"] = "private"
    yt.videos().update(part="status", body={"id": vid, "status": status}).execute()
差別只在下面這幾條承重行為,每一條都是程式碼、都有 --self-test 的突變列:

  1. 硬清單   只收 candidates.json 的 13 支;載入時核對 md5 + 逐支常數 HARD13。
              清單外的 id 在入口和送出前各過一次 guard_id(同一個函式)→ 丟例外。
              9YbTzPfXz6A 另設 --include-9ybt,預設關(Carson 還沒判)。
  2. 寫入當下讀回  先一次 videos.list(part=status,snippet,≤50 支,1 unit),
              用讀回的 status 組 body、只換 privacyStatus;讀回已非 public → 跳過、記錄、不送。
              videos.list 沒回的 id → 跳過、記錄、不送。
  3. 冪等     時間戳 jsonl(apply_log.jsonl,每行 ts/run_id),逐支 sent → ok|err,skip 另記;
              每行 flush + fsync。重跑:已 ok 的不讀不送;有「sent 無結果」或 Google err 的 → 整批不跑,
              要人看過(不自動重送)。
  4. 配額     quota_meter 客戶端擋(YT_QUOTA_ENFORCE=1 本地帳本)→ 第一次就整批中止,
              訊息寫明「本地帳本擋的,不是 Google」。本檔不讀也不改任何門檻 / ENFORCE。
  5. Google 端任何錯誤(含真的 quotaExceeded)→ 記 err、整批停、不重送。
     execute(num_retries=0)。⚠️ 函式庫層仍有兩個本檔擋不到的重送分支,見交付文件
     (httplib2 __init__.py:1400-1409 舊連線 BadStatusLine 重送一次;google_auth_httplib2 :232 401 換 token 重送)。
  6. dry-run  預設;service 外面再包一層 _NoWrite,dry-run 下任何 videos().update 都丟例外。

⚠️ 殘留洞:status.containsSyntheticMedia 可寫但 videos.list 不回傳 ⇒ 讀回再送帶不到它(見交付文件 A)。

用法:
  python set_private_13.py --self-test       離線、零 API、零 service 建構
  python set_private_13.py                   dry-run:1 次 videos.list(1 unit),零 update
  python set_private_13.py --apply           🔴 真送(本輪不准執行)
"""
import argparse, datetime, hashlib, io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
YC = os.path.normpath(os.path.join(HERE, "..", "..", "..", "youtube_channel"))
CAND_PATH = os.path.join(HERE, "candidates.json")
LOG_PATH = os.path.join(HERE, "apply_log.jsonl")

# candidates.json 的 md5(先把 CRLF 正規化成 LF,免得 checkout 設定不同就誤判)
CAND_MD5 = "747699bc6e3f1c6ccf0b1d0c0a2e15b1"
HARD13 = (
    "MuXiM5IqVQQ", "TDbm4XR5pYk", "cObU5NcFT-I", "I8F83sPFKWg", "_Cc49y7ZAeM",
    "tN56crKxwJE", "mvDrUnxEjWs", "vwEaoo3Txjw", "UTuMMyvdQ5U", "DhX2uNzjZ-o",
    "OyprNxjrIBQ", "nHwP_cyy_hc", "xjQPW3sTY28",
)
NINE = "9YbTzPfXz6A"          # 待 Carson 另判;只有 --include-9ybt 才進允許清單
TARGET = "private"
DRY_TAG = "DRY-RUN"

LOCAL_MSG = ("🔴 本地帳本擋的,不是 Google:quota_meter 在送出前拒絕(YT_QUOTA_ENFORCE=1 的本地帳本判定額度不足),"
             "這一筆沒有離開本機。整批中止;門檻 / ENFORCE 不准改,等帳本換日或由督導決定。[%s] 原訊息:%s")
GOOGLE_MSG = "🔴 Google 回錯誤 —— 整批停下、不重送。[%s] %s"


class Stop(Exception):
    """整批停下(exit code 非 0)。"""


class IdNotAllowed(Stop):
    pass


class LocalLedgerAbort(Stop):
    pass


class GoogleAbort(Stop):
    pass


class CheckAbort(Stop):
    pass


class Blocked(Stop):
    pass


class DryRunWriteAttempt(Stop):
    pass


def now_iso():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec="seconds")


# ---------------------------------------------------------------- 1. 硬清單
def load_allowed(path, include_9ybt):
    raw = io.open(path, "rb").read()
    md5 = hashlib.md5(raw.replace(b"\r\n", b"\n")).hexdigest()
    if md5 != CAND_MD5:
        raise Stop("🔴 candidates.json md5 = %s,不是 %s —— 清單被動過,不跑" % (md5, CAND_MD5))
    cand = json.loads(raw.decode("utf-8"))
    ids = tuple(v["videoId"] for v in cand["videos"])
    if ids != HARD13:
        raise Stop("🔴 candidates.json 的 videos 與 HARD13 不一致:%r" % (ids,))
    pend = [p["videoId"] for p in cand.get("pending_carson_separate", [])]
    if pend != [NINE]:
        raise Stop("🔴 pending_carson_separate 不是 [%s]:%r" % (NINE, pend))
    return HARD13 + (NINE,) if include_9ybt else HARD13


def guard_id(vid, allowed):
    """清單外的 id 一律丟例外。run() 入口逐支呼叫、_send() 送出前再呼叫一次(同一個函式)。"""
    if vid not in allowed:
        raise IdNotAllowed("🔴 清單外的 id:%r(允許清單 %d 支)—— 不送" % (vid, len(allowed)))


# ---------------------------------------------------------------- 2. body(照 zombie_sweep.py:413-415)
def build_body(vid, status_now):
    st = dict(status_now)
    st["privacyStatus"] = TARGET
    return {"id": vid, "status": st}


def status_diff(before, after):
    keys = sorted(set(before) | set(after))
    return {k: (before.get(k, "<缺>"), after.get(k, "<缺>"))
            for k in keys if before.get(k, "<缺>") != after.get(k, "<缺>")}


def check(before, body):
    """送出前最後一道:除了 privacyStatus public→private 以外全部相同。回傳錯誤清單,空 = 通過。"""
    errs = []
    d = status_diff(before, body["status"])
    extra = {k: v for k, v in d.items() if k != "privacyStatus"}
    if extra:
        errs.append("privacyStatus 以外有差異:%r" % extra)
    if d.get("privacyStatus") != ("public", TARGET):
        errs.append("privacyStatus 不是 public→%s:%r" % (TARGET, d.get("privacyStatus")))
    return errs


# ---------------------------------------------------------------- 3. 冪等帳
class LogWriter:
    def __init__(self, path, run_id):
        self.f = io.open(path, "a", encoding="utf-8")      # append,不截斷
        self.run_id = run_id

    def write(self, vid, event, **kw):
        rec = dict(kw, ts=now_iso(), run_id=self.run_id, videoId=vid, event=event)
        self.f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
        self.f.flush()
        os.fsync(self.f.fileno())

    def close(self):
        self.f.close()


def read_log(path):
    if not os.path.exists(path):
        return []
    rows = []
    with io.open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                raise Stop("🔴 %s 第 %d 行不是完整 JSON(上次可能寫到一半)—— 人工看過再跑" % (path, n))
    return rows


def log_state(rows):
    """回傳 (已 ok 的 id, 要人看的 id→最後一筆)。
    要人看 = 最後一筆是 sent(送了沒結果)或 err(local_quota 除外:那筆沒離開本機)。"""
    done, last = set(), {}
    for r in rows:
        vid, ev = r.get("videoId"), r.get("event")
        if ev == "ok":
            done.add(vid)
        if ev in ("sent", "ok", "err"):
            last[vid] = r
    blocked = {}
    for vid, r in last.items():
        if vid in done:
            continue
        if r["event"] == "sent" or (r["event"] == "err" and r.get("kind") != "local_quota"):
            blocked[vid] = r
    return done, blocked


# ---------------------------------------------------------------- 4/5. 送出
def _is_local_refusal(exc, qe_types):
    return bool(qe_types) and isinstance(exc, tuple(qe_types))


def _send(yt, body, allowed, lw, qe_types):
    vid = body["id"]
    guard_id(vid, allowed)
    lw.write(vid, "sent", body=body)
    try:
        resp = yt.videos().update(part="status", body=body).execute(num_retries=0)  # 50 quota
    except Exception as exc:  # noqa: BLE001
        if _is_local_refusal(exc, qe_types):
            lw.write(vid, "err", kind="local_quota", detail=str(exc)[:300])
            raise LocalLedgerAbort(LOCAL_MSG % (vid, str(exc)[:200]))
        lw.write(vid, "err", kind="google", detail=repr(exc)[:500])
        raise GoogleAbort(GOOGLE_MSG % (vid, repr(exc)[:300]))
    got = ((resp or {}).get("status") or {}).get("privacyStatus")
    if got != TARGET:
        lw.write(vid, "err", kind="response_mismatch", detail=json.dumps(resp, ensure_ascii=False)[:500])
        raise GoogleAbort(GOOGLE_MSG % (vid, "回應 privacyStatus=%r" % got))
    lw.write(vid, "ok", resp_status=resp.get("status"))
    return True


def _note(lw, out, vid, event, **kw):
    out("  [%s] %s %s" % (event, vid, json.dumps(kw, ensure_ascii=False, sort_keys=True)))
    if lw is not None:
        lw.write(vid, event, **kw)


def run(yt, targets, allowed, apply, log_path, qe_types=(), out=print):
    targets = list(targets)
    for vid in targets:
        guard_id(vid, allowed)
    if len(set(targets)) != len(targets) or len(targets) > 50:
        raise Stop("🔴 targets 重複或超過一批 50 支:%d" % len(targets))
    done, blocked = log_state(read_log(log_path))
    if blocked:
        raise Blocked("🔴 帳上有 %d 支送了沒結果 / Google 回過錯:%s —— 不自動重送,人工確認後再處理"
                      % (len(blocked), sorted(blocked)))
    todo = [v for v in targets if v not in done]
    res = {"already_ok": len(targets) - len(todo), "ok": 0, "would_send": 0, "skip": 0}
    for v in targets:
        if v in done:
            out("  [已 ok] %s —— 帳上已 ok,不讀、不送" % v)
    if not todo:
        out("全部已 ok,本輪零 API 呼叫")
        return res

    try:
        resp = yt.videos().list(part="status,snippet", id=",".join(todo)).execute(num_retries=0)  # 1 quota
    except Exception as exc:  # noqa: BLE001
        if _is_local_refusal(exc, qe_types):
            raise LocalLedgerAbort(LOCAL_MSG % ("videos.list", str(exc)[:200]))
        raise GoogleAbort(GOOGLE_MSG % ("videos.list", repr(exc)[:300]))
    items = {it.get("id"): it for it in ((resp or {}).get("items") or [])}
    stray = sorted(set(items) - set(todo))
    if stray:
        out("  ⚠️ videos.list 回了沒要的 id(忽略、不送):%s" % stray)

    lw = LogWriter(log_path, now_iso()) if apply else None
    try:
        for n, vid in enumerate(todo, 1):
            it = items.get(vid)
            if it is None:
                _note(lw, out, vid, "skip", reason="missing_from_readback")
                res["skip"] += 1
                continue
            st = it.get("status") or {}
            priv = st.get("privacyStatus")
            if priv != "public":
                _note(lw, out, vid, "skip", reason="not_public", privacyStatus=priv)
                res["skip"] += 1
                continue
            body = build_body(vid, st)
            errs = check(st, body)
            if errs:
                _note(lw, out, vid, "err", kind="check", detail=errs)
                raise CheckAbort("🔴 %s body 檢查失敗,整批停:%s" % (vid, errs))
            out("[%02d] %s  %s" % (n, vid, (it.get("snippet") or {}).get("title", "")))
            out("  body = %s" % json.dumps(body, ensure_ascii=False, sort_keys=True))
            for k, (a, b) in status_diff(st, body["status"]).items():
                out("  diff  %-24s %r → %r" % (k, a, b))
            if not apply:
                out("  %s:不送" % DRY_TAG)
                res["would_send"] += 1
                continue
            _send(yt, body, allowed, lw, qe_types)
            res["ok"] += 1
    finally:
        if lw is not None:
            lw.close()
    return res


# ---------------------------------------------------------------- 6. dry-run 的寫入封鎖
class _NoWrite:
    """dry-run 時包住真 service:只放行 videos().list,其餘任何呼叫都丟例外。"""

    def __init__(self, yt):
        self._yt = yt

    def videos(self):
        return _NoWriteVideos(self._yt.videos())

    def __getattr__(self, name):
        raise DryRunWriteAttempt("🔴 dry-run 不准呼叫 service.%s" % name)


class _NoWriteVideos:
    def __init__(self, v):
        self._v = v

    def list(self, **kw):
        return self._v.list(**kw)

    def __getattr__(self, name):
        raise DryRunWriteAttempt("🔴 dry-run 不准呼叫 videos().%s" % name)


def build_parser():
    ap = argparse.ArgumentParser(description="13 支設 private(預設 dry-run)")
    ap.add_argument("--apply", action="store_true", help="🔴 真的送 videos.update")
    ap.add_argument("--include-9ybt", action="store_true", help="把 9YbTzPfXz6A 納入(預設關;Carson 未判)")
    ap.add_argument("--self-test", action="store_true", help="離線自我檢查 + 突變列")
    return ap


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)
    if a.self_test:
        if a.apply:
            ap.error("--self-test 不能配 --apply")
        return self_test()
    allowed = load_allowed(CAND_PATH, a.include_9ybt)
    os.chdir(YC)
    sys.path.insert(0, os.path.join(YC, "scripts"))
    import daily_publish as dp
    import quota_meter as qm
    print("# set_private_13  %s  模式=%s  允許 %d 支  include_9ybt=%s" % (now_iso(), "APPLY" if a.apply else DRY_TAG,
                                                                       len(allowed), a.include_9ybt))
    print("# candidates md5=%s(已核)  log=%s" % (CAND_MD5, LOG_PATH))
    print("# quota_meter(唯讀):ENFORCE=%s RESERVE=%s remaining=%s" % (qm.ENFORCE, qm.RESERVE, qm.remaining()))
    yt = dp.get_service()
    if not a.apply:
        yt = _NoWrite(yt)
    code = 0
    try:
        res = run(yt, list(allowed), allowed, a.apply, LOG_PATH, (qm.QuotaExhausted,))
        print("RESULT:", json.dumps(res, ensure_ascii=False, sort_keys=True))
    except LocalLedgerAbort as e:
        print(e); code = 3
    except GoogleAbort as e:
        print(e); code = 4
    except Blocked as e:
        print(e); code = 5
    except CheckAbort as e:
        print(e); code = 6
    except Stop as e:
        print(e); code = 2
    print("# quota_meter remaining(事後,唯讀)=%s" % qm.remaining())
    return code


# ======== SELF-TEST(不屬於正式路徑;突變只作用在本行以上的原始碼) ========
def self_test():
    """離線自我檢查。做法:讀本檔原始碼 → 對「標記以上」做字串突變 → exec 成獨立模組 → 對 stub service 跑情境。
    判準獨立於腳本自己的 check():送出去的 body 由這裡另外逐欄比對讀回值。"""
    import copy, shutil, tempfile, types
    sys.path.insert(0, os.path.join(YC, "scripts"))
    import quota_meter                                   # 只拿 QuotaExhausted 類別;不 install、不建 service
    QE = (quota_meter.QuotaExhausted,)

    src = io.open(os.path.abspath(__file__), encoding="utf-8").read()
    mark = "# ======" + "== SELF-TEST"
    prod = src[:src.index(mark)]

    cand = json.load(io.open(CAND_PATH, encoding="utf-8"))
    E13 = tuple(v["videoId"] for v in cand["videos"])            # 判準用的 13 支(來自檔案,不來自受測模組)
    snap = json.load(io.open(os.path.join(HERE, "snapshot.json"), encoding="utf-8"))["items"]
    s9 = json.load(io.open(os.path.join(HERE, "snapshot_9YbT.json"), encoding="utf-8"))["items"]
    ST = {v: snap[v]["status"] for v in E13}
    ST[NINE] = s9[NINE]["status"]
    OUTSIDE = "ZZZZZZZZZZZ"
    ST_OUT = dict(ST, **{OUTSIDE: dict(ST[E13[0]])})

    class HttpErrorStub(Exception):
        pass

    class StubYT:
        def __init__(self, statuses, fail_update_at=None, fail_exc=None, fail_list_exc=None):
            self.st = copy.deepcopy(statuses)
            self.orig = copy.deepcopy(statuses)
            self.lists, self.wire, self.attempts = [], [], []
            self.fail_update_at, self.fail_exc, self.fail_list_exc = fail_update_at, fail_exc, fail_list_exc

        def videos(self):
            return StubVideos(self)

    class Req:
        def __init__(self, fn):
            self.fn = fn

        def execute(self, num_retries=0):
            return self.fn()

    class StubVideos:
        def __init__(self, p):
            self.p = p

        def list(self, part, id):
            def f():
                self.p.lists.append((part, tuple(id.split(","))))
                if self.p.fail_list_exc is not None:
                    raise self.p.fail_list_exc
                return {"items": [{"id": v, "status": dict(self.p.st[v]), "snippet": {"title": "t-" + v}}
                                  for v in id.split(",") if v in self.p.st]}
            return Req(f)

        def update(self, part, body):
            def f():
                self.p.attempts.append(copy.deepcopy(body))
                if self.p.fail_update_at == len(self.p.attempts):
                    if isinstance(self.p.fail_exc, QE):          # 本地帳本:在送出前丟,沒上線
                        raise self.p.fail_exc
                    self.p.wire.append(copy.deepcopy(body))       # Google 錯:已經上線
                    raise self.p.fail_exc
                self.p.wire.append(copy.deepcopy(body))
                self.p.st[body["id"]] = dict(body["status"])
                return {"id": body["id"], "status": dict(body["status"])}
            return Req(f)

    def rows(path):
        return [json.loads(l) for l in io.open(path, encoding="utf-8")] if os.path.exists(path) else []

    def wire_ok(yt):
        """獨立判準:每個上線的 body 必須是讀回值只換 privacyStatus public→private。"""
        bad = []
        for b in yt.wire:
            o = yt.orig.get(b["id"])
            if o is None:
                bad.append("%s 不在 stub 母體" % b["id"]); continue
            ks = set(o) | set(b["status"])
            d = [k for k in ks if o.get(k) != b["status"].get(k)]
            if d != ["privacyStatus"] or o["privacyStatus"] != "public" or b["status"]["privacyStatus"] != "private":
                bad.append("%s 上線 body 與讀回差 %s" % (b["id"], sorted(d)))
        return bad

    def expect_raise(fn, cls):
        try:
            fn()
        except cls as e:
            return None, e
        except Exception as e:  # noqa: BLE001
            return "丟的是 %s 不是 %s:%s" % (type(e).__name__, cls.__name__, str(e)[:80]), e
        return "沒丟 %s" % cls.__name__, None

    silent = lambda *_a, **_k: None

    def S1(m, tmp):  # 正常:13 支全送,body 只差 privacyStatus
        f, yt, lg = [], StubYT(ST), os.path.join(tmp, "s1.jsonl")
        try:
            m.run(yt, E13, m.load_allowed(CAND_PATH, False), True, lg, QE, silent)
        except Exception as e:  # noqa: BLE001
            f.append("run 丟 %s:%s" % (type(e).__name__, str(e)[:90]))
        if len(yt.lists) != 1:
            f.append("videos.list 次數 %d ≠ 1" % len(yt.lists))
        if [b["id"] for b in yt.wire] != list(E13):
            f.append("上線 %d 支 ≠ 13 支依序" % len(yt.wire))
        f += wire_ok(yt)
        if sum(r["event"] == "ok" for r in rows(lg)) != 13:
            f.append("帳上 ok %d ≠ 13" % sum(r["event"] == "ok" for r in rows(lg)))
        return f

    def S2(m, tmp):  # 清單外 id / 9YbT 未開旗標 / candidates 被改
        f = []
        yt = StubYT(ST_OUT)
        err, _ = expect_raise(lambda: m.run(yt, E13[:2] + (OUTSIDE,), E13, True,
                                            os.path.join(tmp, "s2.jsonl"), QE, silent), m.IdNotAllowed)
        if err:
            f.append("清單外 id:" + err)
        if any(b["id"] not in E13 for b in yt.attempts) or yt.lists:
            f.append("清單外 id 有流量:list %d、update %s" % (len(yt.lists), [b["id"] for b in yt.attempts]))
        yt9 = StubYT(ST)
        err, _ = expect_raise(lambda: m.run(yt9, (NINE,), m.load_allowed(CAND_PATH, False), True,
                                            os.path.join(tmp, "s2b.jsonl"), QE, silent), m.IdNotAllowed)
        if err or yt9.attempts:
            f.append("9YbT 未開旗標:%s,update %d" % (err, len(yt9.attempts)))
        if m.load_allowed(CAND_PATH, True) != E13 + (NINE,) or m.load_allowed(CAND_PATH, False) != E13:
            f.append("load_allowed 回傳不對")
        bad = os.path.join(tmp, "cand_tampered.json")
        c2 = copy.deepcopy(cand); c2["videos"][0]["videoId"] = OUTSIDE
        io.open(bad, "w", encoding="utf-8").write(json.dumps(c2, ensure_ascii=False))
        err, _ = expect_raise(lambda: m.load_allowed(bad, False), m.Stop)
        if err:
            f.append("candidates 被改:" + err)
        return f

    def S3(m, tmp):  # 讀回已非 public → 跳過、記錄、不送;其餘照送
        f, st = [], copy.deepcopy(ST)
        st[E13[0]]["privacyStatus"] = "private"
        st[E13[1]]["privacyStatus"] = "unlisted"
        yt, lg = StubYT(st), os.path.join(tmp, "s3.jsonl")
        try:
            m.run(yt, E13, E13, True, lg, QE, silent)
        except Exception as e:  # noqa: BLE001
            f.append("run 丟 %s:%s" % (type(e).__name__, str(e)[:90]))
        sent = [b["id"] for b in yt.attempts]
        if E13[0] in sent or E13[1] in sent:
            f.append("已非 public 的仍被送:%s" % [v for v in E13[:2] if v in sent])
        if sent != list(E13[2:]):
            f.append("其餘 11 支應照送,實送 %d" % len(sent))
        sk = {r["videoId"] for r in rows(lg) if r["event"] == "skip"}
        if sk != set(E13[:2]):
            f.append("skip 紀錄 %s ≠ 那 2 支" % sorted(sk))
        return f

    def S4(m, tmp):  # 冪等:跑完再跑,讀回仍 public(快取舊值 / 被改回)也不重送
        f, lg = [], os.path.join(tmp, "s4.jsonl")
        m.run(StubYT(ST), E13, E13, True, lg, QE, silent)
        yt2 = StubYT(ST)
        try:
            m.run(yt2, E13, E13, True, lg, QE, silent)
        except Exception as e:  # noqa: BLE001
            f.append("重跑丟 %s:%s" % (type(e).__name__, str(e)[:90]))
        if yt2.attempts or yt2.lists:
            f.append("重跑有流量:list %d、update %d(重送了)" % (len(yt2.lists), len(yt2.attempts)))
        return f

    def S5(m, tmp):  # 本地帳本擋:第一次就整批中止,訊息寫明不是 Google;事後可續跑
        f, lg = [], os.path.join(tmp, "s5.jsonl")
        yt = StubYT(ST, fail_update_at=1, fail_exc=QE[0]("quota exhausted:videos.update 需 50,今日剩 12"))
        err, e = expect_raise(lambda: m.run(yt, E13, E13, True, lg, QE, silent), m.LocalLedgerAbort)
        if err:
            f.append("update 被擋:" + err)
        elif "本地帳本擋的,不是 Google" not in str(e):
            f.append("訊息沒寫「本地帳本擋的,不是 Google」")
        if len(yt.attempts) != 1 or yt.wire:
            f.append("擋下後還有嘗試:attempts %d、上線 %d" % (len(yt.attempts), len(yt.wire)))
        yt_l = StubYT(ST, fail_list_exc=QE[0]("quota reserve:videos.list 需 1"))
        err, _ = expect_raise(lambda: m.run(yt_l, E13, E13, True, os.path.join(tmp, "s5l.jsonl"), QE, silent),
                              m.LocalLedgerAbort)
        if err or yt_l.attempts:
            f.append("list 被擋:%s,update %d" % (err, len(yt_l.attempts)))
        yt3 = StubYT(ST)
        try:
            m.run(yt3, E13, E13, True, lg, QE, silent)
        except Exception as ex:  # noqa: BLE001
            f.append("本地擋之後續跑丟 %s" % type(ex).__name__)
        if [b["id"] for b in yt3.wire] != list(E13):
            f.append("本地擋之後續跑應送 13,實送 %d" % len(yt3.wire))
        return f

    def S6(m, tmp):  # Google 錯(含真 quotaExceeded):停、不重送、不被當成本地帳本;重跑被擋
        f, lg = [], os.path.join(tmp, "s6.jsonl")
        yt = StubYT(ST, fail_update_at=3, fail_exc=HttpErrorStub('<HttpError 403 "quotaExceeded">'))
        err, e = expect_raise(lambda: m.run(yt, E13, E13, True, lg, QE, silent), m.GoogleAbort)
        if err:
            f.append("Google 錯:" + err)
        elif "本地帳本" in str(e):
            f.append("Google 的 quotaExceeded 被寫成本地帳本")
        ids = [b["id"] for b in yt.attempts]
        if len(ids) != 3 or len(set(ids)) != len(ids):
            f.append("錯誤後的嘗試 %s(應恰 3 次、不重複)" % ids)
        yt2 = StubYT(ST)
        err, _ = expect_raise(lambda: m.run(yt2, E13, E13, True, lg, QE, silent), m.Blocked)
        if err or yt2.attempts or yt2.lists:
            f.append("Google 錯之後重跑:%s,list %d、update %d" % (err, len(yt2.lists), len(yt2.attempts)))
        return f

    def S7(m, tmp):  # dry-run 預設、不寫帳、_NoWrite 擋 update
        f, lg = [], os.path.join(tmp, "s7.jsonl")
        if m.build_parser().parse_args([]).apply:
            f.append("預設 apply=True")
        yt = StubYT(ST)
        res = m.run(m._NoWrite(yt), E13, E13, False, lg, QE, silent)
        if yt.attempts or len(yt.lists) != 1 or os.path.exists(lg) or res.get("would_send") != 13:
            f.append("dry-run:update %d、list %d、寫了帳=%s、would_send=%s"
                     % (len(yt.attempts), len(yt.lists), os.path.exists(lg), res.get("would_send")))
        err, _ = expect_raise(lambda: m._NoWrite(yt).videos().update(part="status", body={}), m.DryRunWriteAttempt)
        if err:
            f.append("_NoWrite 沒擋 update:" + err)
        return f

    def S8(m, tmp):  # 帳上「sent 無結果」→ 整批不跑
        f, lg = [], os.path.join(tmp, "s8.jsonl")
        io.open(lg, "w", encoding="utf-8").write(json.dumps({"videoId": E13[0], "event": "sent"}) + "\n")
        yt = StubYT(ST)
        err, _ = expect_raise(lambda: m.run(yt, E13, E13, True, lg, QE, silent), m.Blocked)
        if err or yt.attempts or yt.lists:
            f.append("sent 無結果:%s,list %d、update %d" % (err, len(yt.lists), len(yt.attempts)))
        return f

    def S9(m, tmp):  # videos.list 沒回的 → 跳過不送
        f, st = [], copy.deepcopy(ST)
        del st[E13[5]]
        yt, lg = StubYT(st), os.path.join(tmp, "s9.jsonl")
        m.run(yt, E13, E13, True, lg, QE, silent)
        if E13[5] in [b["id"] for b in yt.attempts] or len(yt.attempts) != 12:
            f.append("沒讀回的那支被送或總數不對:%d" % len(yt.attempts))
        return f

    SCEN = [("S1 正常13支", S1), ("S2 清單外/9YbT/清單被改", S2), ("S3 讀回已非public", S3), ("S4 重跑冪等", S4),
            ("S5 本地帳本擋", S5), ("S6 Google錯", S6), ("S7 dry-run", S7), ("S8 sent無結果", S8), ("S9 讀回缺片", S9)]

    MUT = [  # (代號, 說明, [(原字串, 突變字串)], 必須翻紅的情境)
        ("BASE", "未突變(同一條 exec 路徑)", [], None),
        ("NC", "陰性對照:改 dry-run 標籤字串", [('DRY_TAG = "DRY-RUN"', 'DRY_TAG = "DRY_RUN_NC"')], None),
        ("M1", "清單外 id 被送出(guard_id 失效)",
         [("    if vid not in allowed:\n", "    if False:\n")], "S2"),
        ("M2", "body 多改一個欄位(build_body 多翻 embeddable)",
         [('    st["privacyStatus"] = TARGET\n',
           '    st["privacyStatus"] = TARGET\n    st["embeddable"] = not st.get("embeddable")\n')], "S1"),
        ("M2b", "M2 + 拿掉 check() 的多欄位檢查(證明判準獨立於腳本自己的 check)",
         [('    st["privacyStatus"] = TARGET\n',
           '    st["privacyStatus"] = TARGET\n    st["embeddable"] = not st.get("embeddable")\n'),
          ("    if extra:\n", "    if False:\n")], "S1"),
        ("M3", "讀回已 private 仍送(拿掉 skip 判斷)",
         [('            if priv != "public":\n', "            if False:\n")], "S3"),
        ("M3b", "M3 + 拿掉 check() 的 public→private 檢查",
         [('            if priv != "public":\n', "            if False:\n"),
          ('    if d.get("privacyStatus") != ("public", TARGET):\n', "    if False:\n")], "S3"),
        ("M4", "冪等失效(帳上的 ok 不算數)",
         [('        if ev == "ok":\n', "        if False:\n")], "S4"),
        ("M5", "本地帳本擋了不中止",
         [("            raise LocalLedgerAbort(LOCAL_MSG % (vid, str(exc)[:200]))\n", "            return False\n")], "S5"),
        ("M6", "Google 錯了不停",
         [("        raise GoogleAbort(GOOGLE_MSG % (vid, repr(exc)[:300]))\n", "        return False\n")], "S6"),
    ]

    print("# set_private_13 --self-test  %s  離線;stub service;突變只作用在 SELF-TEST 標記以上" % now_iso())
    print("# 判準:上線 body 由本 harness 逐欄比對讀回值(不用受測模組的 check)\n")
    allpass = True
    tmp_root = tempfile.mkdtemp(prefix="sp13_")
    try:
        for code, desc, reps, must_red in MUT:
            s = prod
            for old, new in reps:
                c = s.count(old)
                if c != 1:
                    print("❌ %s 突變原字串出現 %d 次(應 1):%r" % (code, c, old)); allpass = False
                    break
                s = s.replace(old, new)
            m = types.ModuleType("sp13_" + code)
            m.__dict__["__file__"] = os.path.abspath(__file__)
            exec(compile(s, "<set_private_13:%s>" % code, "exec"), m.__dict__)
            reds = {}
            for name, fn in SCEN:
                tmp = tempfile.mkdtemp(dir=tmp_root)
                try:
                    fails = fn(m, tmp)
                except Exception as e:  # noqa: BLE001
                    fails = ["情境本身丟 %s:%s" % (type(e).__name__, str(e)[:90])]
                if fails:
                    reds[name] = fails
            red_keys = sorted(k.split()[0] for k in reds)
            if must_red is None:
                ok = not reds
                verdict = "✅ 全綠" if ok else "❌ 應全綠卻紅:%s" % red_keys
            else:
                ok = must_red in red_keys
                verdict = ("✅ 翻紅(%s)" % must_red) if ok else "❌ 沒翻紅 —— 這條承重行為沒被測到"
            allpass &= ok
            print("%-4s %-52s %s  紅燈情境=%s" % (code, desc, verdict, red_keys or "無"))
            for k, v in sorted(reds.items()):
                print("       %s:%s" % (k, " | ".join(v)[:220]))
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
    leaked = [k for k in ("daily_publish", "googleapiclient") if k in sys.modules]
    print("\n# 零網路:daily_publish / googleapiclient 載入了嗎 → %s" % (leaked or "都沒有"))
    allpass &= not leaked
    print("SELFTEST_RESULT:", "PASS" if allpass else "FAIL")
    return 0 if allpass else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    sys.exit(main())
