# -*- coding: utf-8 -*-
"""apply_first_batch_guard.py —— 補九條(D)缺口的「呼叫層」硬上限。

🔴 不改 set_private_13.py 一個字(標準紅線,見 CLAUDE.md/紅線)。做法:把它當模組
import,呼叫它既有的 run(yt, targets, allowed, apply, log_path, qe_types, out)。
targets 和 allowed 本來就是兩個獨立參數(見 set_private_13.py:217),targets 本來就
可以是 allowed 的子集合 —— main() 目前唯一的洞是「永遠傳 targets=allowed(13 支)」,
不是 run() 本身沒有分批能力。本檔是唯一對外入口,把「能不能一次送 >1 支」鎖死在
呼叫端,零 API 呼叫就能擋下。

規則(會擋人,不是提醒):
  1. batch="first" 永遠只送 HARD13[0](MuXiM5IqVQQ),呼叫端無法指定別的 id。
  2. batch="rest"(剩下 12 支)在 first_batch_verified.json 不存在或不合法之前,
     在呼叫 sp13.run() 之前就丟 FirstBatchCapExceeded,零 API 呼叫。
  3. first_batch_verified.json 合法要件(全部檢查,任一項不過 = 視為未驗證仍擋):
       videoId == HARD13[0]
       instrument 存在且 != "set_private_13.py"(不能拿受測腳本自己驗自己,九條(E)要求獨立儀器)
       verified_by、method 都非空
       readback_ts 至少 2 個 ISO8601 時間戳,首尾相差 >= 3600 秒(九條(E)要求 ≥60 分鐘)
  4. 本檔不讀、不改 quota_meter 的 ENFORCE/RESERVE,也不碰 crontab.txt。

用法:
  python apply_first_batch_guard.py --self-test              離線、零 API、零 service,含突變列
  python apply_first_batch_guard.py --batch first --apply    只送第一支(MuXiM5IqVQQ)
  python apply_first_batch_guard.py --batch rest  --apply    送剩下 12 支(需要合法的 first_batch_verified.json)
"""
import argparse, datetime, io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import set_private_13 as sp13  # noqa: E402  只 import,不改動該檔

VERIFY_PATH = os.path.join(HERE, "first_batch_verified.json")
FIRST = sp13.HARD13[0]
REST = sp13.HARD13[1:]


class FirstBatchCapExceeded(sp13.Stop):
    """呼叫層擋下:第一批 >1 支,或 rest 批次沒有合法的獨立驗證紀錄。"""


def load_verification(path=VERIFY_PATH):
    """回傳合法的驗證紀錄 dict;不存在、格式錯、或任一要件不過 —— 一律回傳 None(=視為未驗證)。"""
    if not os.path.exists(path):
        return None
    try:
        v = json.loads(io.open(path, encoding="utf-8").read())
    except ValueError:
        return None
    if not isinstance(v, dict):
        return None
    if v.get("videoId") != FIRST:
        return None
    instrument = v.get("instrument")
    if not instrument or instrument == "set_private_13.py":
        return None
    if not v.get("verified_by") or not v.get("method"):
        return None
    ts = v.get("readback_ts") or []
    if len(ts) < 2:
        return None
    try:
        parsed = [datetime.datetime.fromisoformat(t) for t in ts]
    except (ValueError, TypeError):
        return None
    span = max(parsed) - min(parsed)
    if abs(span.total_seconds()) < 3600:
        return None
    return v


def guarded_run(yt, batch, allowed, apply, log_path, qe_types=(), out=print, verify_path=VERIFY_PATH):
    """本檔唯一對外入口。batch 只接受 "first"/"rest" 這兩個字面值 —— 呼叫端沒有辦法
    自己組一份 targets 列表繞過(guarded_run 根本不接受 targets 參數)。"""
    if batch == "first":
        targets = [FIRST]
    elif batch == "rest":
        v = load_verification(verify_path)
        if v is None:
            raise FirstBatchCapExceeded(
                "🔴 %s 不存在或不合法 —— 第一支(%s)尚未經獨立驗證,不准送剩下 %d 支。"
                % (os.path.basename(verify_path), FIRST, len(REST)))
        targets = list(REST)
    else:
        raise FirstBatchCapExceeded("🔴 batch 必須是 'first' 或 'rest',收到 %r —— 不送" % (batch,))
    return sp13.run(yt, targets, allowed, apply, log_path, qe_types, out)


def build_parser():
    ap = argparse.ArgumentParser(description="set_private_13.py 呼叫層第一批上限=1(九條(D))")
    ap.add_argument("--batch", choices=["first", "rest"], help="first=只送第1支;rest=送剩下12支(需驗證檔)")
    ap.add_argument("--apply", action="store_true", help="🔴 真的送 videos.update")
    ap.add_argument("--include-9ybt", action="store_true", help="沿用 set_private_13.py 的旗標(預設關)")
    ap.add_argument("--self-test", action="store_true", help="離線自我檢查 + 突變列")
    return ap


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)
    if a.self_test:
        if a.apply or a.batch:
            ap.error("--self-test 不能配 --apply/--batch")
        return self_test()
    if not a.batch:
        ap.error("必須指定 --batch first 或 --batch rest")
    allowed = sp13.load_allowed(sp13.CAND_PATH, a.include_9ybt)
    os.chdir(sp13.YC)
    sys.path.insert(0, os.path.join(sp13.YC, "scripts"))
    import daily_publish as dp
    import quota_meter as qm
    print("# apply_first_batch_guard  %s  batch=%s  模式=%s"
          % (sp13.now_iso(), a.batch, "APPLY" if a.apply else sp13.DRY_TAG))
    print("# quota_meter(唯讀):ENFORCE=%s RESERVE=%s remaining=%s" % (qm.ENFORCE, qm.RESERVE, qm.remaining()))
    yt = dp.get_service()
    if not a.apply:
        yt = sp13._NoWrite(yt)
    code = 0
    try:
        res = guarded_run(yt, a.batch, allowed, a.apply, sp13.LOG_PATH, (qm.QuotaExhausted,))
        print("RESULT:", json.dumps(res, ensure_ascii=False, sort_keys=True))
    except FirstBatchCapExceeded as e:
        print(e); code = 7
    except sp13.LocalLedgerAbort as e:
        print(e); code = 3
    except sp13.GoogleAbort as e:
        print(e); code = 4
    except sp13.Blocked as e:
        print(e); code = 5
    except sp13.CheckAbort as e:
        print(e); code = 6
    except sp13.Stop as e:
        print(e); code = 2
    print("# quota_meter remaining(事後,唯讀)=%s" % qm.remaining())
    return code


# ======== SELF-TEST(不屬於正式路徑;突變只作用在本行以上的原始碼) ========
def self_test():
    """離線自我檢查,做法照抄 set_private_13.py 的 mutation-testing 慣例:
    讀本檔原始碼 → 對「標記以上」做字串突變 → exec 成獨立模組 → 對每個情境跑斷言,
    判準獨立於受測模組自己的邏輯。"""
    import copy, shutil, tempfile, types

    sys.path.insert(0, os.path.join(sp13.YC, "scripts"))
    import quota_meter
    QE = (quota_meter.QuotaExhausted,)

    src = io.open(os.path.abspath(__file__), encoding="utf-8").read()
    mark = "# ======" + "== SELF-TEST"
    prod = src[:src.index(mark)]

    cand = json.load(io.open(sp13.CAND_PATH, encoding="utf-8"))
    E13 = tuple(v["videoId"] for v in cand["videos"])
    snap = json.load(io.open(os.path.join(HERE, "snapshot.json"), encoding="utf-8"))["items"]
    ST = {v: snap[v]["status"] for v in E13}
    ALLOWED = E13

    class StubYT:
        def __init__(self, statuses):
            self.st = copy.deepcopy(statuses)
            self.orig = copy.deepcopy(statuses)
            self.lists, self.wire, self.attempts = [], [], []

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
                return {"items": [{"id": v, "status": dict(self.p.st[v]), "snippet": {"title": "t-" + v}}
                                  for v in id.split(",") if v in self.p.st]}
            return Req(f)

        def update(self, part, body):
            def f():
                self.p.attempts.append(copy.deepcopy(body))
                self.p.wire.append(copy.deepcopy(body))
                self.p.st[body["id"]] = dict(body["status"])
                return {"id": body["id"], "status": dict(body["status"])}
            return Req(f)

    silent = lambda *_a, **_k: None

    def expect_raise(fn, cls):
        try:
            fn()
        except cls as e:
            return None, e
        except Exception as e:  # noqa: BLE001
            return "丟的是 %s 不是 %s:%s" % (type(e).__name__, cls.__name__, str(e)[:80]), e
        return "沒丟 %s" % cls.__name__, None

    def write_verify(tmp, **overrides):
        base = {
            "videoId": FIRST, "verified_by": "w9:p1", "method": "獨立儀器回讀(見 instrument2)",
            "instrument": "preflight_inst2.py(playlistItems.list)",
            "readback_ts": ["2026-09-15T21:15:00+08:00", "2026-09-15T22:16:00+08:00"],
        }
        base.update(overrides)
        p = os.path.join(tmp, "first_batch_verified.json")
        io.open(p, "w", encoding="utf-8").write(json.dumps(base, ensure_ascii=False))
        return p

    def S1(m, tmp):  # batch=first 永遠只送 1 支(FIRST),零讀取 verify 檔
        f, yt, lg = [], StubYT(ST), os.path.join(tmp, "s1.jsonl")
        try:
            m.guarded_run(yt, "first", ALLOWED, True, lg, QE, silent, os.path.join(tmp, "nope.json"))
        except Exception as e:  # noqa: BLE001
            f.append("run 丟 %s:%s" % (type(e).__name__, str(e)[:90]))
        if [b["id"] for b in yt.wire] != [FIRST]:
            f.append("first 批次上線 id ≠ [%s]:%s" % (FIRST, [b["id"] for b in yt.wire]))
        return f

    def S2_no_verify_file(m, tmp):  # 🔴 核心情境:沒有驗證檔,batch=rest 必須在 API 之前就被擋
        f = []
        yt = StubYT(ST)
        err, e = expect_raise(
            lambda: m.guarded_run(yt, "rest", ALLOWED, True, os.path.join(tmp, "s2.jsonl"),
                                   QE, silent, os.path.join(tmp, "missing.json")),
            m.FirstBatchCapExceeded)
        if err:
            f.append(err)
        if yt.lists or yt.attempts:
            f.append("擋下前不該有任何 API 呼叫:list %d、update %d" % (len(yt.lists), len(yt.attempts)))
        return f

    def S3_tampered_verify(m, tmp):  # 驗證檔存在但不合法(videoId 錯/instrument 是自己/時間差<60分)→ 一樣擋
        f = []
        cases = [
            ("videoId 錯", {"videoId": "WRONG_ID"}),
            ("instrument 是受測腳本自己", {"instrument": "set_private_13.py"}),
            ("instrument 空字串", {"instrument": ""}),
            ("時間差 <60 分", {"readback_ts": ["2026-09-15T21:15:00+08:00", "2026-09-15T21:59:00+08:00"]}),
            ("只有 1 個時間戳", {"readback_ts": ["2026-09-15T21:15:00+08:00"]}),
        ]
        for label, override in cases:
            vp = write_verify(tmp, **override)
            yt = StubYT(ST)
            err, _ = expect_raise(
                lambda vp=vp: m.guarded_run(yt, "rest", ALLOWED, True, os.path.join(tmp, "s3.jsonl"),
                                             QE, silent, vp),
                m.FirstBatchCapExceeded)
            if err:
                f.append("%s:%s" % (label, err))
            if yt.attempts:
                f.append("%s:不合法的驗證檔卻放行了 update" % label)
        return f

    def S4_valid_verify_unblocks_rest(m, tmp):  # 合法驗證檔存在 → rest 批次放行,送出剩下 12 支
        f = []
        vp = write_verify(tmp)
        yt, lg = StubYT(ST), os.path.join(tmp, "s4.jsonl")
        try:
            m.guarded_run(yt, "rest", ALLOWED, True, lg, QE, silent, vp)
        except Exception as e:  # noqa: BLE001
            f.append("run 丟 %s:%s" % (type(e).__name__, str(e)[:90]))
        sent = [b["id"] for b in yt.wire]
        if sent != list(REST):
            f.append("rest 批次應送剩下 12 支(依序),實送 %s" % sent)
        if FIRST in sent:
            f.append("rest 批次不該再碰 first(%s)" % FIRST)
        return f

    def S5_bad_batch_literal(m, tmp):  # batch 不是 first/rest → 擋,零 API
        f = []
        yt = StubYT(ST)
        err, _ = expect_raise(
            lambda: m.guarded_run(yt, "ALL13", ALLOWED, True, os.path.join(tmp, "s5.jsonl"), QE, silent,
                                   os.path.join(tmp, "nope.json")),
            m.FirstBatchCapExceeded)
        if err:
            f.append(err)
        if yt.lists or yt.attempts:
            f.append("非法 batch 字面值卻有 API 呼叫")
        return f

    SCEN = [
        ("S1 first批次=1支", S1),
        ("S2 沒驗證檔擋rest", S2_no_verify_file),
        ("S3 驗證檔不合法擋rest", S3_tampered_verify),
        ("S4 合法驗證檔放行rest=12支", S4_valid_verify_unblocks_rest),
        ("S5 非法batch字面值擋", S5_bad_batch_literal),
    ]

    MUT = [
        ("BASE", "未突變(同一條 exec 路徑)", [], None),
        ("NC", "陰性對照:改一個不相干字串",
         [('description="set_private_13.py 呼叫層第一批上限=1(九條(D))"',
           'description="set_private_13.py 呼叫層第一批上限=1(九條(D))(nc)"')], None),
        ("M1", "batch=rest 時不檢查驗證檔(直接放行,guard 失效)",
         [("        v = load_verification(verify_path)\n        if v is None:\n",
           "        v = load_verification(verify_path)\n        if False:\n")], "S2"),
        ("M2", "驗證檔合法性檢查失效(videoId 不比對)",
         [('    if v.get("videoId") != FIRST:\n        return None\n', "    pass\n")], "S3"),
        ("M3", "時間差門檻被拿掉(<60分也算合法)",
         [("    if abs(span.total_seconds()) < 3600:\n        return None\n", "    pass\n")], "S3"),
    ]

    print("# apply_first_batch_guard --self-test  %s  離線;stub service;突變只作用在 SELF-TEST 標記以上"
          % sp13.now_iso())
    print("# 判準:S2(沒驗證檔)必須在零 API 呼叫下擋下 rest 批次;這是九條(D)要求的「會擋人」核心情境\n")
    allpass = True
    tmp_root = tempfile.mkdtemp(prefix="afbg_")
    try:
        for code, desc, reps, must_red in MUT:
            s = prod
            for old, new in reps:
                c = s.count(old)
                if c != 1:
                    print("❌ %s 突變原字串出現 %d 次(應 1):%r" % (code, c, old)); allpass = False
                    break
                s = s.replace(old, new)
            m = types.ModuleType("afbg_" + code)
            m.__dict__["__file__"] = os.path.abspath(__file__)
            exec(compile(s, "<apply_first_batch_guard:%s>" % code, "exec"), m.__dict__)
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
