# -*- coding: utf-8 -*-
"""84 支描述欄改寫 —— 獨立回讀儀器(只讀;全檔唯一的 API 呼叫是 videos.list)。

依據:docs/ops/2026-09-11_84支描述欄改寫_事後回讀計畫.md(a3994a6f)§2–§6、
      docs/ops/2026-09-12_84支寫入把關清單_wF-p3.md(195ed7ff)§D。
寫這支的人不是改寫工具的作者,也不是把關者。

獨立性(承重,每一條都是程式碼):
  1. 不 import fix_period_disclaimer / daily_publish / yt_analytics / quota_meter;結束時核 sys.modules。
  2. 舊句 / 新句自己抄字面值,載入時核 md5(寫死在下面);不相符就丟例外,不回報任何結果。
  3. 自建 service;token 只在記憶體 refresh、只要求 youtube.readonly,不寫回 token 檔。
  4. service 外包 _ListOnly:videos().list 以外的任何呼叫都丟例外。
  5. 不 yt-dlp、不抓 HTML。

兩支儀器(結論分開寫,不准合併成一句):
  ch2   yt_ch2/token.json            專案 881902283633  與寫入端完全獨立;預期看不到 private
  main  youtube_channel/token.json   專案 524513894332  與寫入端同專案同帳號(部分獨立);看得到 private

用法(在 youtube_channel/ 下):
  .venv\\Scripts\\python.exe scripts\\verify_desc_rewrite.py --self-test [--evidence-dir DIR]   離線、零 API
  .venv\\Scripts\\python.exe scripts\\verify_desc_rewrite.py --baseline [--out FILE]          (正式一律兩支儀器)
  .venv\\Scripts\\python.exe scripts\\verify_desc_rewrite.py --check BASELINE.json [--label T1]
        [--expect-written=vid1,vid2 | --expect-written=@file | --expect-none] [--out FILE]
  --cred main|ch2 只供診斷:少量的那支儀器算 code 3,baseline 會標成「不可作為比較基準」。
每支儀器一輪 = 88 個 id(84 + 3 陰性對照 + 1 假 id)= 2 次 videos.list = 2 units(記在該儀器的專案帳上)。
本工具的呼叫不進 STUDIO/quota_meter.json(刻意不 import daily_publish)⇒ 本地帳本會少記這幾 units。

--check 判準(逐支):新句恰 1 次、舊句 0 次;描述把新句換回舊句後逐位元組 == baseline;
  title/tags/categoryId/defaultLanguage/defaultAudioLanguage/privacyStatus 與 baseline 不同 ⇒ 列「需人判」,不自動判錯。
  --expect-written 外的目標反過來判:舊句恰 1、新句 0、描述逐位元組 == baseline(沒被碰)。
  沒回來的 id 一律「未讀到」,不是通過。ch2 讀不到的 private 只在「main 同一輪讀到它是 private」時豁免;
  main 本輪沒量到 ⇒ 一支都不豁免。
baseline 只有在兩支儀器都 ok、code 0 時落檔標 usable_as_baseline=true;--check 讀到其他 baseline 一律拒比(code 2)。

exit code:0 成功 | 4 描述全過、有需人判 | 1 不成立 | 2 儀器作廢(陰性對照翻面 / 回了沒送的 id / 重複 id /
          nextPageToken / baseline 不可用 / 參數錯)| 3 儀器不可用或沒量(含工具本身丟例外)
"""
import argparse, datetime, hashlib, io, json, os, sys, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
YC = os.path.normpath(os.path.join(HERE, ".."))
REPO = os.path.normpath(os.path.join(YC, ".."))
OUT_DIR = os.path.join(REPO, "docs", "ops", "2026-09-11_84支描述欄改寫_事後回讀計畫")
SNAP_DIR = os.path.join(YC, "STUDIO", "desc_snapshot_20260911")
TOOL_TAG = "verify_desc_rewrite"
READONLY = "https://www.googleapis.com/auth/youtube.readonly"

# ---------------------------------------------------------------- 判準的錨點:獨立抄寫
# 來源:回讀計畫 §1 + team-lead 派工單逐字。半形 , ; —— 句尾全形 。。不 import 寫入端取常數。
OLD = "之後的影片已改成在同一句標明期間。"
NEW = "之後的影片已改進做法,但仍可能有漏的;看到請留言告訴我,我會補上更正。"
OLD_MD5 = "e9f13a327f665ad742eceabc1340a900"
NEW_MD5 = "1d873574fdb646dc27e9dc5c6a99cd29"


class LiteralMismatch(Exception):
    pass


def literal_problems():
    p = []
    for name, s, want in (("OLD", OLD, OLD_MD5), ("NEW", NEW, NEW_MD5)):
        got = hashlib.md5(s.encode("utf-8")).hexdigest()
        if got != want:
            p.append("%s md5=%s ≠ 寫死的 %s" % (name, got, want))
    return p


_lp = literal_problems()
if _lp:
    raise LiteralMismatch("🔴 字面值被動過,停,不回報任何結果:" + ";".join(_lp))

# ---------------------------------------------------------------- 母體(凍結在 09-11 盤點;不讀 DONE)
# 來源 STUDIO/_mixed_period_published.json 的順序;與 desc_snapshot_20260911 的 84 檔逐支相同。
TARGETS = (
    "0Gy7jec6Agc", "B1VfToi_HdY", "l36tPQliBSc", "-_aUs0oj1o0", "Oy7dux0cBHs", "mvNh7IjgRLY",
    "OtwYzI6XE8Y", "EFQGvPDDTRQ", "Vd3pOcDFhFQ", "J5pDfPc9w7A", "m1pqccjG5s8", "Hgf5C6P0fN4",
    "yKc1SMchkSw", "UY0DdkuZrHo", "gyVqxplDyu8", "7DIYyvjQdKY", "wcqE7dVwkP4", "7ixOvHW5aM8",
    "N_quHN5BBRE", "u0gWQe1RbNA", "0tc8VKpjfrA", "BymPJQbC9cU", "TBMTuaUTd8A", "ZzYz7JrDBK0",
    "eXCi6EQ3scI", "D-IZXExuPmw", "DQqWOKBFDs8", "0EPASuhQti0", "8NCqx8Zzwu0", "p_KCREwmyds",
    "J_VtZrDPZB8", "u-2PyNoTOQk", "9Ly1duaPucw", "gv_LsCVxSOw", "Qzi-6x9iGj4", "_GgxPgLzsKQ",
    "H3Sk1AfUVT0", "gFbecJC41-I", "Qk-o2-ZaV-c", "otTPyfbKfJ0", "hmFTD4Tb4Sg", "Cc6-UL16-CQ",
    "WNrS46cXiQ8", "-dyes0qFE9U", "EaFK-E6_xss", "BiGdBpEvI6Q", "IjgIEJo5w7E", "jsIt1qA1aj8",
    "FYpVo6KawFE", "OhrPgVP_CR8", "I-dZzhEhAAA", "RUZLI4k8OU8", "5xlZ-GgkLoE", "PJu4zbcZ4Eo",
    "Nhc7XjmcTLY", "jDjuUXeSx98", "OqjzGFuuuHc", "rwdhTBAfXQI", "6TRk1183KbA", "l7bwt2ExKvg",
    "UAHNpnF3uqk", "Az3gBJzc6q8", "5qLlIj65Rt4", "28VsAqNKCZA", "B9mXAplHxYk", "9Sirsi0ZP9o",
    "WFJoOC-4izg", "Slty-G_Gdj4", "MTPczTWeZ74", "U0Rj9r0jzHg", "h5eH6di_SNA", "aoLWkUDQ0zI",
    "p6Qvg2mC-9w", "dURMDAu8HYY", "bJN3uXU9mgo", "tDanOnIWAfo", "Xdwvq7NEE84", "6HsGEj_jt0Y",
    "gXc3LvibBLs", "24Kz-SOtX2o", "DOZcYNsXfjc", "SFk0W_2WqLc", "GNSXluoU1-E", "9_35qFeSCIw",
)
TARGETS_SHA1 = "1df05cc83ccc4d0e34bab3b064d01ace7c754200"   # sha1(",".join(sorted(TARGETS)))
if len(set(TARGETS)) != 84 or hashlib.sha1(",".join(sorted(TARGETS)).encode()).hexdigest() != TARGETS_SHA1:
    raise LiteralMismatch("🔴 TARGETS 被動過(應 84 支、sha1 %s),停" % TARGETS_SHA1)

# 盤點 §3a 的 15 支 private(09-11 11:45 量的)。只在「這次沒有 main 儀器」時當分組參考,並標明出處。
INVENTORY_PRIVATE15 = frozenset((
    "0EPASuhQti0", "7ixOvHW5aM8", "8NCqx8Zzwu0", "D-IZXExuPmw", "H3Sk1AfUVT0", "Nhc7XjmcTLY",
    "OtwYzI6XE8Y", "RUZLI4k8OU8", "SFk0W_2WqLc", "UY0DdkuZrHo", "l36tPQliBSc", "m1pqccjG5s8",
    "u-2PyNoTOQk", "u0gWQe1RbNA", "wcqE7dVwkP4",
))
# 陰性對照:不在 84 裡、從來沒有 MARK / 舊句(盤點 §4 用過的三支;y_pggXEwZJo public,另兩支 private)
CONTROLS = ("y_pggXEwZJo", "mxV56GTL-oI", "YPQpGOlsJMs")
FAKE = "ZZZZfake000"
POP = {"targets": TARGETS, "controls": CONTROLS, "fake": FAKE}

INSTRUMENTS = {
    "ch2": {"token": os.path.join(REPO, "yt_ch2", "token.json"), "project": "881902283633",
            "sees_private": False, "independence": "完全獨立(不同專案 / client / token 檔)"},
    "main": {"token": os.path.join(YC, "token.json"), "project": "524513894332",
             "sees_private": True, "independence": "部分獨立:與寫入端同專案同帳號(不同 token 檔)"},
}
FIELDS = ("title", "tags", "categoryId", "defaultLanguage", "defaultAudioLanguage")
FORBIDDEN_MODULES = ("fix_period_disclaimer", "daily_publish", "yt_analytics", "quota_meter")

PASS, FAIL, UNREAD = "PASS", "FAIL", "未讀到"
CODE_TEXT = {0: "成功", 4: "描述全過、有需人判", 1: "不成立", 2: "儀器作廢", 3: "儀器不可用"}
SEVERITY = {0: 0, 4: 1, 1: 2, 2: 3, 3: 4}


class Stop(Exception):
    pass


class InstrumentUnavailable(Exception):
    pass


class ListOnlyViolation(Exception):
    pass


def now_iso():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec="seconds")


def sha1(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def git_blob(path):
    data = io.open(path, "rb").read()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def rel(path):
    try:
        return os.path.relpath(os.path.abspath(path), REPO).replace("\\", "/")
    except ValueError:  # 不同磁碟
        return os.path.abspath(path).replace("\\", "/")


def count_old_new(desc):
    return desc.count(OLD), desc.count(NEW)


def pl_lines(desc):
    return sum(1 for ln in desc.split("\n") if ln.startswith("📚"))


def privacy(item):
    return (item.get("status") or {}).get("privacyStatus")


def first_diff(a, b):
    """a = 現在(已換回), b = baseline。回第一個不同處前後文。"""
    n, i = min(len(a), len(b)), 0
    while i < n and a[i] == b[i]:
        i += 1
    return "第 %d 字起 baseline=%r / 現在=%r(長度 %d / %d)" % (i, b[max(0, i - 12):i + 24], a[max(0, i - 12):i + 24],
                                                          len(b), len(a))


# ---------------------------------------------------------------- 讀取(唯一的 API 呼叫點)
def read_ids(yt, ids):
    """每 50 支一次 videos.list。只存送出的 id 和原始回應;判讀一律交給 reads_from_calls(和讀落檔同一條路)。"""
    ids = list(ids)
    calls = []
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        rec = {"at": now_iso(), "sent_ids": chunk}
        calls.append(rec)
        try:
            resp = yt.videos().list(part="snippet,status", id=",".join(chunk)).execute(num_retries=0)  # 1 unit
        except Exception as exc:  # noqa: BLE001
            rec["error"] = "第 %d 次 videos.list 丟例外:%s" % (len(calls), repr(exc)[:1200])
            break
        rec["response"] = resp
        rec["returned_ids"] = [it.get("id") for it in (resp or {}).get("items") or []]   # 給人看;判讀不用
    return reads_from_calls(calls)


def reads_from_calls(calls):
    """從原始回應重建讀值(不信任任何衍生欄位)。
    重複 id / nextPageToken / 回了沒送的 id / 沒回應也沒錯誤 ⇒ problems(→ code 2)。"""
    items, problems = {}, []
    for n, c in enumerate(calls, 1):
        resp = c.get("response")
        if not isinstance(resp, dict):
            if not c.get("error"):
                problems.append("第 %d 次沒有回應也沒有錯誤" % n)
            continue
        if resp.get("nextPageToken"):
            problems.append("第 %d 次回了 nextPageToken(分頁沒處理)" % n)
        for it in resp.get("items") or []:
            vid = it.get("id")
            if vid in items:
                problems.append("id 重複回來(後一份蓋掉前一份,讀值不可信):%s" % vid)
            if vid not in c["sent_ids"]:
                problems.append("回了沒送的 id:%s" % vid)
            items[vid] = it
    err = next((c["error"] for c in calls if c.get("error")), None)
    return {"calls": calls, "items": items, "problems": problems, "error": err,
            "sent": [v for c in calls for v in c["sent_ids"]]}


# ---------------------------------------------------------------- 判定
def group_of(vid, priv_ref):
    return priv_ref.get(vid) or "unknown"


def summarize(rows, priv_ref):
    g = {}
    for vid, r in rows.items():
        s = g.setdefault(group_of(vid, priv_ref), {"total": 0, "pass": 0, "fail": 0, "unread": 0, "review": 0})
        s["total"] += 1
        s[{PASS: "pass", FAIL: "fail", UNREAD: "unread"}[r["verdict"]]] += 1
        if r.get("review"):
            s["review"] += 1
    return g


def expected_unread(pop, main_privacy, sees_private):
    """看不到 private 的儀器,只豁免「main 同一輪讀到是 private」的那幾支。
    main_privacy 必須是同一輪 main 的讀值;main 沒量到 ⇒ 呼叫端傳 {} ⇒ 一支都不豁免(沒量 ≠ 通過)。"""
    return set() if sees_private else {v for v in pop["targets"] if main_privacy.get(v) == "private"}


def judge_controls(pop, items, sent, base_items=None):
    rows, bad = {}, []
    for vid in pop["controls"]:
        it = items.get(vid)
        if it is None:
            rows[vid] = UNREAD
            continue
        d = (it.get("snippet") or {}).get("description") or ""
        o, n = count_old_new(d)
        if o or n:
            rows[vid] = "🔴 舊句 %d / 新句 %d(應 0 / 0)" % (o, n)
            bad.append("陰性對照 %s 被判成有那句話 ⇒ 儀器對什麼都說有" % vid)
            continue
        b = (base_items or {}).get(vid)
        if b is not None and ((b.get("snippet") or {}).get("description") or "") != d:
            rows[vid] = "🔴 描述與 baseline 不同"
            bad.append("陰性對照 %s 的描述和 baseline 不同 ⇒ 範圍外有東西被動過或儀器讀錯;停手、開原檔人判" % vid)
            continue
        rows[vid] = "不適用/未改"
    if not any(r.startswith("不適用/未改") for r in rows.values()):
        bad.append("沒有任何一支陰性對照被讀到並判成未改")
    if pop["fake"] not in sent:
        bad.append("假 id 沒有送出")
    if pop["fake"] in items:
        bad.append("假 id %s 回來了" % pop["fake"])
    rows[pop["fake"]] = "🔴 回來了" if pop["fake"] in items else "沒回來(正確)"
    return {"ok": not bad, "rows": rows, "bad": bad}


def decide(rows, ctrl, problems, expect, pop):
    if problems or not ctrl["ok"]:
        return 2
    unread = {v for v, r in rows.items() if r["verdict"] == UNREAD}
    if len(rows) != len(pop["targets"]) or (unread - expect) or any(r["verdict"] == FAIL for r in rows.values()):
        return 1
    if (expect - unread) or any(r.get("review") for r in rows.values()):
        return 4
    return 0


def judge_target(b, c, written=True):
    """b = baseline item、c = 現在 item。written=False ⇒ 這支不該被碰。回 (verdict, reasons, review, info)。"""
    bsn, csn = b.get("snippet") or {}, c.get("snippet") or {}
    bdesc, cdesc = bsn.get("description") or "", csn.get("description") or ""
    reasons, review = [], []
    b_old, b_new = count_old_new(bdesc)
    if (b_old, b_new) != (1, 0):
        reasons.append("baseline 不合格:舊句 %d、新句 %d(應 1 / 0)" % (b_old, b_new))
    n_old, n_new = count_old_new(cdesc)
    if written:
        ok_count = (n_new == 1 and n_old == 0)
        restored = cdesc.replace(NEW, OLD)
    else:
        ok_count = (n_new == 0 and n_old == 1)
        restored = cdesc
    if not ok_count:
        reasons.append("新句 %d 次、舊句 %d 次(應 %s)" % (n_new, n_old, "新 1 / 舊 0" if written else "新 0 / 舊 1,未被寫"))
    ok_bytes = restored.encode("utf-8") == bdesc.encode("utf-8")
    if not ok_bytes:
        reasons.append("換回後 ≠ baseline(逐位元組):" + first_diff(restored, bdesc))
    for k in FIELDS:
        if bsn.get(k) != csn.get(k):
            review.append("欄位 %s 不同(需人判):%r → %r" % (k, bsn.get(k), csn.get(k)))
    if privacy(b) != privacy(c):
        review.append("privacyStatus 不同(需人判):%r → %r" % (privacy(b), privacy(c)))
    info = {"new": n_new, "old": n_old, "pl_base": pl_lines(bdesc), "pl_now": pl_lines(cdesc),
            "sha1_now": sha1(cdesc), "audio_now": csn.get("defaultAudioLanguage"), "privacy_now": privacy(c)}
    return (PASS if not reasons else FAIL), reasons, review, info


def judge_check(pop, base, cur, main_privacy, sees_private, written=None, group_ref=None):
    """base / cur = reads_from_calls() 的回傳;main_privacy = 同一輪 main 讀到的 privacyStatus(沒量到 = {});
    written = 應已改寫的 id 集合(None = 全部);group_ref 只給分組顯示用(預設 = main_privacy)。"""
    written = set(pop["targets"]) if written is None else set(written)
    rows = {}
    for vid in pop["targets"]:
        c = cur["items"].get(vid)
        b = base["items"].get(vid)
        if c is None:
            rows[vid] = {"verdict": UNREAD, "reasons": ["送出了、沒回來"], "review": []}
            continue
        if b is None:
            rows[vid] = {"verdict": FAIL, "reasons": ["baseline 當時沒讀到這支,無從比對"], "review": []}
            continue
        v, reasons, review, info = judge_target(b, c, vid in written)
        rows[vid] = dict(info, verdict=v, reasons=reasons, review=review, expect="written" if vid in written else "untouched")
    expect = expected_unread(pop, main_privacy, sees_private)
    ctrl = judge_controls(pop, cur["items"], cur["sent"], base["items"])
    problems = (["[baseline] " + p for p in base.get("problems") or []] + list(cur.get("problems") or [])
                + ([cur["error"]] if cur.get("error") else []))
    unread = {v for v, r in rows.items() if r["verdict"] == UNREAD}
    code = 3 if cur.get("error") else decide(rows, ctrl, problems, expect, pop)
    return {"rows": rows, "groups": summarize(rows, main_privacy if group_ref is None else group_ref),
            "controls": ctrl, "problems": problems,
            "split": {"expected_unread": sorted(expect), "unread": sorted(unread), "ok": unread == expect},
            "code": code}


def judge_baseline(pop, rd, main_privacy, sees_private, group_ref=None):
    """§3-A 改寫前鏡像:讀到的每一支必須舊句 1 / 新句 0。main_privacy / group_ref 同 judge_check。"""
    rows = {}
    for vid in pop["targets"]:
        it = rd["items"].get(vid)
        if it is None:
            rows[vid] = {"verdict": UNREAD, "reasons": ["baseline 讀取:送出了、沒回來"], "review": []}
            continue
        sn = it.get("snippet") or {}
        d = sn.get("description") or ""
        o, n = count_old_new(d)
        mirror_ok = (o == 1 and n == 0)
        rows[vid] = {"verdict": PASS if mirror_ok else FAIL, "review": [],
                     "reasons": [] if mirror_ok else ["改寫前應舊句 1 / 新句 0,實際 %d / %d" % (o, n)],
                     "old": o, "new": n, "sha1": sha1(d), "len": len(d), "pl": pl_lines(d),
                     "privacy": privacy(it), "audio": sn.get("defaultAudioLanguage")}
    expect = expected_unread(pop, main_privacy, sees_private)
    ctrl = judge_controls(pop, rd["items"], rd["sent"])
    problems = list(rd.get("problems") or []) + ([rd["error"]] if rd.get("error") else [])
    unread = {v for v, r in rows.items() if r["verdict"] == UNREAD}
    code = 3 if rd.get("error") else decide(rows, ctrl, problems, expect, pop)
    return {"rows": rows, "groups": summarize(rows, main_privacy if group_ref is None else group_ref),
            "controls": ctrl, "problems": problems,
            "split": {"expected_unread": sorted(expect), "unread": sorted(unread), "ok": unread == expect},
            "code": code}


def overall(codes):
    return max(codes, key=lambda c: SEVERITY[c]) if codes else 3


# ---------------------------------------------------------------- 儀器(只讀)
class _ListOnly:
    """包住真 service:只放行 videos().list。"""

    def __init__(self, yt):
        self._yt = yt

    def videos(self):
        return _ListOnlyVideos(self._yt.videos())

    def __getattr__(self, name):
        raise ListOnlyViolation("🔴 本儀器不准呼叫 service.%s" % name)


class _ListOnlyVideos:
    def __init__(self, v):
        self._v = v

    def list(self, **kw):
        return self._v.list(**kw)

    def __getattr__(self, name):
        raise ListOnlyViolation("🔴 本儀器不准呼叫 videos().%s" % name)


def build_instrument(name):
    spec = INSTRUMENTS[name]
    meta = {"name": name, "token_file": os.path.relpath(spec["token"], REPO).replace("\\", "/"),
            "project": spec["project"], "independence": spec["independence"], "sees_private": spec["sees_private"]}
    raw = json.load(io.open(spec["token"], encoding="utf-8"))
    if not str(raw.get("client_id", "")).startswith(spec["project"] + "-"):
        raise InstrumentUnavailable("token 的 client_id 不屬於專案 %s" % spec["project"])
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_info(raw, [READONLY])   # 只要求 readonly;記憶體內,不寫回
    try:
        creds.refresh(Request())
    except Exception as exc:  # noqa: BLE001
        raise InstrumentUnavailable("refresh 失敗(= 儀器不可用,不是影片有問題):%r" % exc)
    meta["granted_scopes"] = sorted(getattr(creds, "granted_scopes", None) or [])
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    return _ListOnly(yt), meta


def run_instrument(name, ids):
    try:
        yt, meta = build_instrument(name)
    except Exception as exc:  # noqa: BLE001  token 檔不在 / 壞掉 / refresh 失敗 都是「儀器不可用」,不是影片有問題
        return {"meta": {"name": name, "project": INSTRUMENTS[name]["project"]}, "status": "unavailable",
                "error": "%s: %s" % (type(exc).__name__, exc), "problems": [], "calls": [], "api_attempts": 0}
    rd = read_ids(yt, ids)
    return {"meta": meta, "status": "error" if rd["error"] else "ok", "error": rd["error"],
            "problems": rd["problems"], "calls": rd["calls"], "api_attempts": len(rd["calls"])}


def reads_of(inst):
    """落檔原始回應重建的讀值,再併入 run_instrument 當場記的 problems(兩邊應相同;不同也都留著)。"""
    rd = reads_from_calls(inst.get("calls") or [])
    rd["problems"] += [p for p in inst.get("problems") or [] if p not in rd["problems"]]
    return rd


def round_privacy(instruments):
    """這一輪 main 讀到的 privacyStatus。main 沒量 / 不可用 / 讀到一半出錯 ⇒ {}(⇒ ch2 的 private 一支都不豁免)。"""
    m = instruments.get("main")
    if not m or m.get("status") != "ok":
        return {}
    items = reads_from_calls(m["calls"])["items"]
    return {v: privacy(items[v]) for v in TARGETS if v in items}


def report_unmeasured(names, codes):
    """--cred 排除的儀器:印出來、算 code 3。沒量的那支儀器負責的結論,本輪就是沒有。"""
    for n in INSTRUMENTS:
        if n not in names:
            print("\n== 儀器 %s | 🔴 本輪沒量(--cred 排除)⇒ code 3;它負責的那一半結論本輪不存在" % n)
            codes.append(3)


def baseline_unusable(bl):
    """回「不可作為比較基準」的理由;空 list = 可用。旗標之外逐項重核(旗標可能被手改)。"""
    why_unusable = []
    if bl.get("usable_as_baseline") is not True:
        why_unusable.append("usable_as_baseline=%r" % bl.get("usable_as_baseline"))
    for n in INSTRUMENTS:
        st = ((bl.get("instruments") or {}).get(n) or {}).get("status")
        if st != "ok":
            why_unusable.append("儀器 %s status=%r" % (n, st))
    if bl.get("code") != 0:
        why_unusable.append("baseline code=%r" % bl.get("code"))
    return why_unusable


def write_new_json(path, obj):
    if os.path.exists(path):
        raise Stop("🔴 不覆蓋既有檔:%s" % path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    data = json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    tmp = path + ".tmp"
    with io.open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    if io.open(tmp, "rb").read() != data:
        raise Stop("🔴 暫存檔讀回不符:%s" % tmp)
    os.replace(tmp, path)
    return hashlib.sha1(data).hexdigest()


def cred_names(cred):
    return ["ch2", "main"] if cred == "both" else [cred]


# ---------------------------------------------------------------- 輸出
def print_groups(rep, sees_private):
    for g in sorted(rep["groups"]):
        s = rep["groups"][g]
        note = ""
        if g == "private" and not sees_private:
            note = "  (此儀器預期看不到 private ⇒ 未讀到是預期,不是通過)"
        print("   %-8s PASS %d/%d  FAIL %d  未讀到 %d  需人判 %d%s"
              % (g, s["pass"], s["total"], s["fail"], s["unread"], s["review"], note))


def print_controls_split(rep):
    print("   陰性對照:" + ";".join("%s %s" % (k, v) for k, v in rep["controls"]["rows"].items()))
    for b in rep["controls"]["bad"]:
        print("   🔴 " + b)
    for p in rep["problems"]:
        print("   🔴 " + p)
    sp = rep["split"]
    print("   分裂對照:預期讀不到 %d 支、實際讀不到 %d 支 ⇒ %s"
          % (len(sp["expected_unread"]), len(sp["unread"]), "✅ 逐支相同" if sp["ok"] else "🔴 不同(需人判)"))
    if not sp["ok"]:
        print("     只在預期:%s | 只在實際:%s" % (sorted(set(sp["expected_unread"]) - set(sp["unread"])),
                                            sorted(set(sp["unread"]) - set(sp["expected_unread"]))))


def print_head(inst):
    m = inst["meta"]
    print("\n== 儀器 %s | %s | 專案 %s | %s" % (m["name"], m.get("token_file", "?"), m["project"],
                                             m.get("independence", "")))
    if inst["status"] == "unavailable":
        print("   🔴 儀器不可用:%s" % inst["error"])
        return False
    print("   granted_scopes=%s" % m.get("granted_scopes"))
    print("   videos.list 呼叫 %d 次(= %d units,記在專案 %s 的帳上)" % (inst["api_attempts"], inst["api_attempts"],
                                                            m["project"]))
    if inst["error"]:
        print("   🔴 %s" % inst["error"])
    return True


def snapshot_drift(items):
    """資訊用(不影響 code):與 w9 09-11 11:45 快照比。寫入端要求線上 == 快照,不同的那幾支它會拒動。"""
    if not os.path.isdir(SNAP_DIR):
        print("   (快照目錄不存在,略過)")
        return None
    same, diff, missing, fields = 0, [], [], {}
    for v in TARGETS:
        p = os.path.join(SNAP_DIR, v + ".json")
        if v not in items:
            continue
        if not os.path.exists(p):
            missing.append(v)
            continue
        sn = json.load(io.open(p, encoding="utf-8")).get("snippet") or {}
        cn = items[v].get("snippet") or {}
        if (sn.get("description") or "").encode("utf-8") == (cn.get("description") or "").encode("utf-8"):
            same += 1
        else:
            diff.append(v)
        for k in FIELDS:
            if sn.get(k) != cn.get(k):
                fields.setdefault(k, []).append("%s:%r→%r" % (v, sn.get(k), cn.get(k)) if k != "tags" else v)
    print("   [資訊] 對 09-11 快照:描述逐位元組相同 %d、不同 %d %s、缺檔 %d" % (same, len(diff), diff, len(missing)))
    for k, vs in sorted(fields.items()):
        print("   [資訊] 對 09-11 快照 %s 不同 %d 支:%s" % (k, len(vs), vs))
    return {"same": same, "diff": diff, "missing": missing, "fields": fields}


def cmd_baseline(a):
    ids = list(TARGETS) + list(CONTROLS) + [FAKE]
    out = {"tool": TOOL_TAG, "tool_blob": git_blob(os.path.abspath(__file__)), "mode": "baseline",
           "taken_at": now_iso(), "old": OLD, "new": NEW, "old_md5": OLD_MD5, "new_md5": NEW_MD5,
           "targets": list(TARGETS), "targets_sha1": TARGETS_SHA1, "controls": list(CONTROLS), "fake": FAKE,
           "instruments": {}}
    print("# %s --baseline  %s  tool_blob=%s" % (TOOL_TAG, out["taken_at"], out["tool_blob"]))
    print("# 送出 %d 個 id = 84 目標 + 3 陰性對照 + 假 id %s" % (len(ids), FAKE))
    names = cred_names(a.cred)
    for name in names:
        out["instruments"][name] = run_instrument(name, ids)
    main_priv = round_privacy(out["instruments"])   # 同一輪 main 讀到的;ch2 的豁免只認這個
    if main_priv:
        group_ref, src = main_priv, "main 儀器同一輪讀到的 privacyStatus"
    else:
        group_ref = {v: ("private" if v in INVENTORY_PRIVATE15 else "public") for v in TARGETS}
        src = "🔴 09-11 盤點的 15 支清單,只用來分組顯示(本輪沒有 main 讀值 ⇒ ch2 讀不到的 private 一支都不豁免)"
    out["privacy_reference"] = src
    print("# 分組依據:%s" % src)
    codes = []
    report_unmeasured(names, codes)
    for name, inst in out["instruments"].items():
        if not print_head(inst):
            codes.append(3)
            continue
        if not INSTRUMENTS[name]["sees_private"] and not main_priv:
            print("   🔴 本輪沒有 main 讀值 ⇒ 讀不到的 private 不豁免,都算未讀到")
        rd = reads_of(inst)
        rep = judge_baseline(POP, rd, main_priv, INSTRUMENTS[name]["sees_private"], group_ref)
        inst["judge"] = {k: rep[k] for k in ("groups", "controls", "problems", "split", "code")}
        print("   送出 %d / 回來 %d" % (len(rd["sent"]), len(rd["items"])))
        print("   %-3s %-12s %-8s %-8s %-12s %2s %2s %2s %5s" % ("#", "videoId", "privacy", "audio", "desc_sha1",
                                                             "舊", "新", "📚", "len"))
        for i, v in enumerate(TARGETS, 1):
            r = rep["rows"][v]
            if r["verdict"] == UNREAD:
                print("   %-3d %-12s 未讀到(送出了、沒回來)" % (i, v))
            else:
                print("   %-3d %-12s %-8s %-8s %-12s %2d %2d %2d %5d%s" % (
                    i, v, r["privacy"], r["audio"], r["sha1"][:12], r["old"], r["new"], r["pl"], r["len"],
                    "" if r["verdict"] == PASS else "  🔴 " + ";".join(r["reasons"])))
        read = [r for r in rep["rows"].values() if r["verdict"] != UNREAD]
        print("   小計:讀到 %d/84;舊句=1 的 %d 支;新句=0 的 %d 支;public %d / private %d;未讀到 %d"
              % (len(read), sum(r["old"] == 1 for r in read), sum(r["new"] == 0 for r in read),
                 sum(r["privacy"] == "public" for r in read), sum(r["privacy"] == "private" for r in read),
                 84 - len(read)))
        print("   📚 行合計 %d(有 📚 行的 %d 支)" % (sum(r["pl"] for r in read), sum(r["pl"] > 0 for r in read)))
        print_groups(rep, INSTRUMENTS[name]["sees_private"])
        print_controls_split(rep)
        if name == "main":
            inst["snapshot_drift"] = snapshot_drift(rd["items"])
        print("   §3-A 改寫前鏡像 [%s]:%s" % (name, CODE_TEXT[rep["code"]]))
        codes.append(rep["code"])
    return finish(a, out, codes, "baseline_%s.json" % out["taken_at"][:19].replace(":", "").replace("-", ""))


def load_written(spec, none=False):
    """應已改寫的 id 集合;None = 全部 84。空字串 / 讀不了的 @檔 / 不在 84 裡的 id ⇒ Stop(code 2)。"""
    if none:
        return set()
    if spec is None:
        return None
    src = "--expect-written"
    if spec.startswith("@"):
        src = "--expect-written=" + spec
        try:
            spec = io.open(spec[1:], encoding="utf-8-sig").read()
        except (UnicodeDecodeError, OSError) as exc:
            raise Stop("🔴 %s 讀不了(要存成 ASCII 或 UTF-8;PS5.1 用 Set-Content -Encoding ascii,"
                       "不要用 Out-File 預設的 UTF-16):%s: %s" % (src, type(exc).__name__, exc))
    ids = [x.strip() for x in spec.replace("\n", ",").split(",") if x.strip()]
    if not ids:
        raise Stop("🔴 %s 是空的 —— 空集合等於「84 支都該沒被碰」;真的要這樣判,改用 --expect-none" % src)
    stray = [v for v in ids if v not in TARGETS]
    if stray:
        raise Stop("🔴 %s 有不在 84 支裡的 id:%s" % (src, stray))
    return set(ids)


def cmd_check(a):
    bl = json.load(io.open(a.check, encoding="utf-8"))
    if bl.get("mode") != "baseline" or bl.get("old_md5") != OLD_MD5 or bl.get("new_md5") != NEW_MD5 \
            or bl.get("targets_sha1") != TARGETS_SHA1:
        raise Stop("🔴 baseline 檔的 mode / 字面值 md5 / 母體 sha1 與本工具不符,不比")
    why = baseline_unusable(bl)
    if why:
        raise Stop("🔴 baseline 不可作為比較基準(%s)⇒ 不比;重跑 --baseline(兩支儀器都 ok、code 0 才可用)"
                   % ";".join(why))
    written = load_written(a.expect_written, a.expect_none)
    names = cred_names(a.cred or "both")
    ids = list(TARGETS) + list(CONTROLS) + [FAKE]
    out = {"tool": TOOL_TAG, "tool_blob": git_blob(os.path.abspath(__file__)), "mode": "check", "label": a.label,
           "checked_at": now_iso(), "baseline_file": rel(a.check),
           "baseline_sha1": hashlib.sha1(io.open(a.check, "rb").read()).hexdigest(),
           "baseline_taken_at": bl.get("taken_at"), "expect_written": sorted(written) if written is not None else "全部 84",
           "instruments": {}}
    print("# %s --check  label=%s  %s  tool_blob=%s" % (TOOL_TAG, a.label, out["checked_at"], out["tool_blob"]))
    print("# baseline=%s(%s,sha1 %s)" % (out["baseline_file"], out["baseline_taken_at"], out["baseline_sha1"][:12]))
    print("# 應已改寫:%s" % (out["expect_written"] if written is None else "%d 支 %s" % (len(written), sorted(written))))
    for name in names:
        out["instruments"][name] = run_instrument(name, ids)   # 先全部量完再判:ch2 的豁免要用同一輪 main 的讀值
    base_priv = round_privacy(bl["instruments"])
    main_priv = round_privacy(out["instruments"])  # 本輪 main 讀到的(ch2 豁免只認這個)
    group_ref = main_priv or base_priv
    out["privacy_reference"] = ("本輪 main 讀到的 privacyStatus" if main_priv else
                                "🔴 baseline 時 main 讀到的,只用來分組顯示(本輪沒有 main 讀值 ⇒ ch2 讀不到的 private 一支都不豁免)")
    print("# 分組依據:%s" % out["privacy_reference"])
    codes = []
    report_unmeasured(names, codes)
    for name in names:
        inst = out["instruments"][name]
        if not print_head(inst):
            codes.append(3)
            continue
        if not INSTRUMENTS[name]["sees_private"] and not main_priv:
            print("   🔴 本輪沒有 main 讀值 ⇒ 讀不到的 private 不豁免,都算未讀到")
        base = reads_of(bl["instruments"][name])
        cur = reads_of(inst)
        rep = judge_check(POP, base, cur, main_priv, INSTRUMENTS[name]["sees_private"], written, group_ref)
        inst["judge"] = rep
        print("   送出 %d / 回來 %d" % (len(cur["sent"]), len(cur["items"])))
        print_groups(rep, INSTRUMENTS[name]["sees_private"])
        for v in TARGETS:
            r = rep["rows"][v]
            if r["verdict"] == UNREAD and v in rep["split"]["expected_unread"]:
                continue
            if r["verdict"] != PASS or r["review"]:
                print("   %-12s [%s] %s %s" % (v, group_of(v, group_ref), r["verdict"], ";".join(r["reasons"] + r["review"])))
        rows_read = [r for r in rep["rows"].values() if "pl_base" in r]
        print("   📚 行:baseline %d / 現在 %d(已含在逐位元組比對內,這行只是看得見)"
              % (sum(r["pl_base"] for r in rows_read), sum(r["pl_now"] for r in rows_read)))
        print_controls_split(rep)
        print("   結論 [%s]:%s" % (name, CODE_TEXT[rep["code"]]))
        codes.append(rep["code"])
    print("\n# 這一輪期間 §5 表的 job 有沒有跑過:本工具不知道 —— 落檔時要人補一句,答不出來 ⇒ 本輪降級成參考")
    return finish(a, out, codes, "check_%s_%s.json" % (a.label, out["checked_at"][:19].replace(":", "").replace("-", "")))


def finish(a, out, codes, default_name):
    leaked = [m for m in FORBIDDEN_MODULES if m in sys.modules]
    out["forbidden_modules_loaded"] = leaked
    code = 2 if leaked else overall(codes)
    out["code"] = code
    if out["mode"] == "baseline":
        why = baseline_unusable(dict(out, usable_as_baseline=True))
        out["usable_as_baseline"] = not why
        out["unusable_reasons"] = why
    path = a.out or os.path.join(OUT_DIR, default_name)
    digest = write_new_json(path, out)
    api = sum(i.get("api_attempts", 0) for i in out["instruments"].values())
    print("\n# 獨立性:%s 載入了嗎 → %s" % ("/".join(FORBIDDEN_MODULES), leaked or "都沒有"))
    print("# 本輪 videos.list 共 %d 次;其他 API 0 次" % api)
    print("# 落檔 %s(sha1 %s)" % (path, digest))
    if out["mode"] == "baseline":
        print("# " + ("✅ 可作為比較基準(usable_as_baseline=true)" if out["usable_as_baseline"] else
                      "🔴 不可作為比較基準:%s —— --check 會拒絕這個檔" % ";".join(out["unusable_reasons"])))
    print("RESULT: code=%d %s" % (code, CODE_TEXT[code]))
    return code


def build_parser():
    ap = argparse.ArgumentParser(description="84 支描述欄改寫 —— 獨立回讀儀器(只讀)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--self-test", action="store_true", help="離線自我檢查 + 突變列(零 API)")
    g.add_argument("--baseline", action="store_true", help="改寫前量測(§3-A)")
    g.add_argument("--check", metavar="BASELINE_JSON", help="改寫後回讀(T1 / T2)")
    ap.add_argument("--cred", choices=("both", "main", "ch2"), default=None,
                    help="預設 both;main / ch2 只供診斷(沒量的那支算 code 3,baseline 不可作為比較基準)")
    ap.add_argument("--label", default="T1", help="check 的標籤(T1_canary / T1 / T2 ...)")
    ew = ap.add_mutually_exclusive_group()
    ew.add_argument("--expect-written", default=None,
                    help="應已改寫的 id:--expect-written=vid1,vid2 或 --expect-written=@檔案(要帶等號,id 可能以 - 開頭);"
                         "預設全部 84;空字串會被拒")
    ew.add_argument("--expect-none", action="store_true", help="一支都不該被寫(取代空字串 --expect-written=)")
    ap.add_argument("--out", default=None, help="落檔路徑(預設 %s 下自動命名,不覆蓋)" % OUT_DIR)
    ap.add_argument("--evidence-dir", default=None, help="self-test 證據檔目錄")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    if a.self_test:
        return self_test(a.evidence_dir)
    try:
        if a.baseline:
            a.cred = a.cred or "both"
            return cmd_baseline(a)
        return cmd_check(a)
    except Stop as exc:
        print(exc)
        print("RESULT: code=2 %s" % CODE_TEXT[2])
        return 2
    except Exception:  # noqa: BLE001  工具本身壞掉:traceback 的 exit 1 不能被讀成「不成立」
        traceback.print_exc(file=sys.stdout)
        print("RESULT: code=3 %s(工具本身丟例外,這一輪輸出作廢)" % CODE_TEXT[3])
        return 3


# ======== SELF-TEST(不屬於正式路徑;突變只作用在本行以上的原始碼) ========
def self_test(evidence_dir=None):
    """讀本檔原始碼 → 對「標記以上」做字串突變 → exec 成獨立模組 → 對造出來的樣本跑情境。
    判準(每個情境的預期)寫死在這裡,不來自受測模組。"""
    import contextlib, copy, shutil, tempfile, types

    src = io.open(os.path.abspath(__file__), encoding="utf-8").read()
    mark = "# ======" + "== SELF-TEST"
    prod = src[:src.index(mark)]

    # harness 自己的字面值(M6 只改受測模組那份)
    H_OLD = "之後的影片已改成在同一句標明期間。"
    H_NEW = "之後的影片已改進做法,但仍可能有漏的;看到請留言告訴我,我會補上更正。"
    T = ["P1", "P2", "P3", "P4", "Q1", "Q2"]
    PRIV = {"P1": "public", "P2": "public", "P3": "public", "P4": "public", "Q1": "private", "Q2": "private"}
    CTRL = ["C1", "C2"]
    FK = "ZZZZfake000"
    HPOP = {"targets": T, "controls": CTRL, "fake": FK}
    IDS = T + CTRL + [FK]

    def desc_of(v, with_pl):
        lines = ["📌 關於片中與 0050 的比較", ""]
        if with_pl:
            lines += ["📚 全系列連播｜個股體檢｜https://www.youtube.com/playlist?list=PLa" + v, ""]
        lines += ["片中提到「同期 0050」的報酬數字,取自「近十年」(%s)。" % v, H_OLD, "",
                  "📚 產業連播｜https://www.youtube.com/playlist?list=PLb" + v, "#台股 #存股"]
        return "\n".join(lines)

    def mk(v, desc, priv, audio="zh-Hant"):
        return {"kind": "youtube#video", "id": v,
                "snippet": {"title": "t-" + v, "description": desc, "tags": ["台股", v], "categoryId": "27",
                            "defaultLanguage": "zh-Hant", "defaultAudioLanguage": audio},
                "status": {"privacyStatus": priv}}

    BASE = {v: mk(v, desc_of(v, i % 2 == 0), PRIV[v], "en-US" if v == "P1" else "zh-Hant") for i, v in enumerate(T)}
    BASE["C1"] = mk("C1", "穩定幣買美股能跑網格?\n📚 https://www.youtube.com/playlist?list=PLc", "public")
    BASE["C2"] = mk("C2", "AI 寫的量化系統 90% 虧錢", "private")

    def rw(d):
        i = d.index(H_OLD)
        return d[:i] + H_NEW + d[i + len(H_OLD):]

    def rewritten(only=None):
        w = copy.deepcopy(BASE)
        for v in (T if only is None else only):
            w[v]["snippet"]["description"] = rw(w[v]["snippet"]["description"])
        return w

    class Req:
        def __init__(self, fn):
            self.fn = fn

        def execute(self, num_retries=0):
            return self.fn()

    class StubYT:
        def __init__(self, world, sees_private=True, fake_returns=False, dup=None, page_token=False,
                     fail_on_call=None):
            self.world, self.sees, self.fake = world, sees_private, fake_returns
            self.dup, self.pt, self.fail_on_call, self.n = dup or {}, page_token, fail_on_call, 0

        def videos(self):
            return StubVideos(self)

    class StubVideos:
        def __init__(self, p):
            self.p = p

        def list(self, part, id):
            def f():
                self.p.n += 1
                if self.p.fail_on_call == self.p.n:
                    raise RuntimeError("stub: 第 %d 次呼叫丟例外" % self.p.n)
                out = []
                for v in id.split(","):
                    if v in self.p.dup:
                        out.append(copy.deepcopy(self.p.dup[v]))     # 先回一份(快取吐的舊副本)
                    it = self.p.world.get(v)
                    if it is not None and (self.p.sees or it["status"]["privacyStatus"] == "public"):
                        out.append(copy.deepcopy(it))
                    if v == FK and self.p.fake:
                        out.append(mk(FK, "假", "public"))
                r = {"kind": "youtube#videoListResponse", "items": out}
                if self.p.pt:
                    r["nextPageToken"] = "CDIQAA"
                return r
            return Req(f)

    def chk(m, cur, sees=True, fake=False, written=None, base=None):
        b = m.read_ids(StubYT(base or BASE, sees), IDS)
        c = m.read_ids(StubYT(cur, sees, fake), IDS)
        return m.judge_check(HPOP, b, c, PRIV, sees, written)

    def expect(rep, code=None, verdicts=None, groups=None):
        f = []
        if code is not None and rep["code"] != code:
            f.append("code %s ≠ 預期 %s" % (rep["code"], code))
        for v, want in (verdicts or {}).items():
            got = rep["rows"].get(v, {}).get("verdict", "<沒有這一列>")
            if got != want:
                f.append("%s 判 %s ≠ 預期 %s" % (v, got, want))
        if groups is not None:
            got = {k: (s["total"], s["pass"], s["fail"], s["unread"], s["review"]) for k, s in rep["groups"].items()}
            if got != groups:
                f.append("分組 %s ≠ 預期 %s" % (sorted(got.items()), sorted(groups.items())))
        return f

    ALLP = {v: "PASS" for v in T}
    G_ALL = {"public": (4, 4, 0, 0, 0), "private": (2, 2, 0, 0, 0)}

    def S0(m):  # 字面值:受測模組那份 == harness 那份;非漢字碼點 = 半形 , ; , + 全形 。
        f = []
        if m.NEW != H_NEW or m.OLD != H_OLD:
            f.append("受測模組字面值 ≠ harness 字面值")
        if m.literal_problems():
            f.append("literal_problems 非空:%s" % m.literal_problems())
        cps = [hex(ord(ch)) for ch in m.NEW if ord(ch) < 0x3000 or ord(ch) in (0x3002, 0xff0c, 0xff1b)]
        if cps != ["0x2c", "0x3b", "0x2c", "0x3002"]:
            f.append("NEW 非漢字碼點 %s" % cps)
        return f

    def S1(m):  # 正常:看得到 private 的儀器,6 支全改好
        return expect(chk(m, rewritten()), 0, ALLP, G_ALL)

    def S2(m):  # 一支沒改到(快取吐舊副本 / 沒寫進去):描述 == baseline
        cur = rewritten()
        cur["P2"] = copy.deepcopy(BASE["P2"])
        return expect(chk(m, cur), 1, dict(ALLP, P2="FAIL"), {"public": (4, 3, 1, 0, 0), "private": (2, 2, 0, 0, 0)})

    def S3(m):  # 那句話換對了,但別處被動:吃掉 📚 行 / 改一個字
        f = []
        cur = rewritten()
        d = cur["P3"]["snippet"]["description"].split("\n")
        cur["P3"]["snippet"]["description"] = "\n".join(x for i, x in enumerate(d) if i != 2)   # 第一條 📚 行
        f += expect(chk(m, cur), 1, dict(ALLP, P3="FAIL"))
        cur = rewritten()
        cur["Q1"]["snippet"]["description"] = cur["Q1"]["snippet"]["description"].replace("0050", "0056", 1)
        f += expect(chk(m, cur), 1, dict(ALLP, Q1="FAIL"))
        return f

    def S4(m):  # 看不到 private 的儀器(ch2 型):private 必須落在未讀到,不是通過;分組各自 N/N
        rep = chk(m, rewritten(), sees=False)
        f = expect(rep, 0, dict(ALLP, Q1="未讀到", Q2="未讀到"), {"public": (4, 4, 0, 0, 0), "private": (2, 0, 0, 2, 0)})
        if not rep["split"]["ok"]:
            f.append("分裂對照沒過:%s" % rep["split"])
        return f

    def S5(m):  # 一支送出了沒回來 ⇒ 未讀到,不是通過
        cur = rewritten()
        del cur["P4"]
        rep = chk(m, cur)
        f = expect(rep, 1, dict(ALLP, P4="未讀到"), {"public": (4, 3, 0, 1, 0), "private": (2, 2, 0, 0, 0)})
        if rep["controls"]["rows"].get(FK) != "沒回來(正確)":
            f.append("假 id 列 = %r" % rep["controls"]["rows"].get(FK))
        return f

    def S6(m):  # 陰性對照翻面:對照片也出現新句 / 假 id 回來 / 對照片全沒讀到 ⇒ 儀器作廢
        f = []
        cur = rewritten()
        cur["C1"]["snippet"]["description"] += "\n" + H_NEW
        f += ["[對照有新句] " + x for x in expect(chk(m, cur), 2)]
        f += ["[假 id 回來] " + x for x in expect(chk(m, rewritten(), fake=True), 2)]
        cur = rewritten()
        del cur["C1"], cur["C2"]
        f += ["[對照全沒讀到] " + x for x in expect(chk(m, cur), 2)]
        return f

    def S7(m):  # 欄位差異(fix_audio_language 那種):描述過、列需人判、不自動判錯
        cur = rewritten()
        cur["P1"]["snippet"]["defaultAudioLanguage"] = "zh-Hant"
        rep = chk(m, cur)
        f = expect(rep, 4, ALLP, {"public": (4, 4, 0, 0, 1), "private": (2, 2, 0, 0, 0)})
        rv = rep["rows"].get("P1", {}).get("review", [])
        if not any("defaultAudioLanguage" in x for x in rv):
            f.append("P1 需人判沒列出 defaultAudioLanguage:%s" % rv)
        return f

    def S8(m):  # §3-A 改寫前鏡像:正常 baseline 過;有一支已經是新句 ⇒ 不成立
        f = []
        rep = m.judge_baseline(HPOP, m.read_ids(StubYT(BASE), IDS), PRIV, True)
        f += ["[正常] " + x for x in expect(rep, 0, ALLP, G_ALL)]
        rep = m.judge_baseline(HPOP, m.read_ids(StubYT(rewritten(["P1"])), IDS), PRIV, True)
        f += ["[P1 已是新句] " + x for x in expect(rep, 1, dict(ALLP, P1="FAIL"))]
        return f

    def S9(m):  # 新句重複插入兩次
        cur = rewritten()
        cur["P2"]["snippet"]["description"] += "\n" + H_NEW
        return expect(chk(m, cur), 1, dict(ALLP, P2="FAIL"))

    def S10(m):  # canary:只寫了 P1、Q1;其餘必須原封不動;寫到範圍外 ⇒ 不成立
        f = expect(chk(m, rewritten(["P1", "Q1"]), written={"P1", "Q1"}), 0, ALLP)
        f += ["[範圍外被寫] " + x for x in expect(chk(m, rewritten(["P1", "Q1", "P2"]), written={"P1", "Q1"}),
                                             1, dict(ALLP, P2="FAIL"))]
        return f

    # ---- 黏合層:走 m.main([...]) 正式路徑(cmd_baseline / cmd_check / run_instrument / reads_from_calls /
    #      round_privacy / load_written / finish),只把 build_instrument 換成 stub;輸出只寫進暫存目錄。
    GTMP = tempfile.mkdtemp(prefix="vdr_selftest_")
    GN = [0]
    INV = set(INVENTORY_PRIVATE15)
    CAN = [TARGETS[3], TARGETS[43]]   # -_aUs0oj1o0、-dyes0qFE9U:以 - 開頭,只能用 = 形式
    DRIFT = (INV - {"0EPASuhQti0"}) | {"0Gy7jec6Agc"}   # w9 那種:一支 private→public、一支 public→private

    def gdesc(v):
        return "\n".join(["📌 關於片中與 0050 的比較", "片中數字取自「近十年」(%s)。" % v, H_OLD, "",
                          "📚 產業連播｜https://www.youtube.com/playlist?list=PLb" + v, "#台股"])

    def gworld(private):
        w = {v: mk(v, gdesc(v), "private" if v in private else "public") for v in TARGETS}
        for c in CONTROLS:
            w[c] = mk(c, "陰性對照 %s\n📚 https://www.youtube.com/playlist?list=PLc" % c,
                      "public" if c == CONTROLS[0] else "private")
        return w

    GBASE = gworld(INV)

    def grw(base, only=None):
        w = copy.deepcopy(base)
        for v in (TARGETS if only is None else only):
            w[v]["snippet"]["description"] = rw(w[v]["snippet"]["description"])
        return w

    def both(w, **kw):
        return {"ch2": dict(kw, world=w), "main": dict(kw, world=w)}

    def gmain(m, worlds, argv):
        def fake_build(name):
            cfg = worlds.get(name, "unavailable")
            if cfg == "unavailable":
                raise m.InstrumentUnavailable("stub: refresh 失敗")
            spec = m.INSTRUMENTS[name]
            meta = {"name": name, "token_file": "stub/" + name, "project": spec["project"],
                    "independence": spec["independence"], "sees_private": spec["sees_private"],
                    "granted_scopes": [m.READONLY]}
            kw = dict(cfg)
            return m._ListOnly(StubYT(kw.pop("world"), spec["sees_private"], **kw)), meta
        m.build_instrument = fake_build
        m.OUT_DIR = os.path.join(GTMP, "never_default")   # 保險:沒帶 --out 也寫不進正式目錄
        m.SNAP_DIR = os.path.join(GTMP, "no_snapshot")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                code = m.main(argv)
            except SystemExit as e:
                code = "SystemExit(%s)" % e.code
            except Exception as e:  # noqa: BLE001
                code = "uncaught %s" % type(e).__name__
        return code, buf.getvalue()

    def gfile(tag):
        GN[0] += 1
        return os.path.join(GTMP, "%04d_%s.json" % (GN[0], tag))

    def gload(p):
        return json.load(io.open(p, encoding="utf-8")) if os.path.exists(p) else {}

    def gbaseline(m, worlds, cred=None):
        p = gfile("bl")
        code, _txt = gmain(m, worlds, ["--baseline", "--out", p] + (["--cred", cred] if cred else []))
        return p, code, gload(p)

    def gcheck(m, bl, worlds, extra=()):
        p = gfile("ck")
        code, txt = gmain(m, worlds, ["--check", bl, "--out", p] + list(extra))
        return code, gload(p), txt

    def jget(doc, name, key):
        return (((doc.get("instruments") or {}).get(name) or {}).get("judge") or {}).get(key)

    OKBL = {}

    def okbl(m):  # 每個受測模組一份「兩支都好」的 baseline
        if m.__name__ not in OKBL:
            OKBL[m.__name__] = gbaseline(m, both(GBASE))
        return OKBL[m.__name__]

    def G1(m):  # 陽性對照:兩支都好 ⇒ 0 + 可用;全寫對 / canary ⇒ 0;privacy 漂移時豁免跟著本輪 main 走
        p, c, bl = okbl(m)
        f = [] if (c, bl.get("usable_as_baseline")) == (0, True) else \
            ["baseline code %s、usable %r" % (c, bl.get("usable_as_baseline"))]
        c, ck, _ = gcheck(m, p, both(grw(GBASE)))
        if c != 0 or sorted(jget(ck, "ch2", "split")["expected_unread"] if ck else []) != sorted(INV):
            f.append("全寫對 code %s;ch2 豁免的應是本輪 main 讀到的 15 支" % c)
        c, _, _ = gcheck(m, p, both(grw(GBASE, CAN)), ["--expect-written=" + ",".join(CAN)])
        if c != 0:
            f.append("canary code %s ≠ 0" % c)
        pd, c, _ = gbaseline(m, both(gworld(DRIFT)))
        if c != 0:
            f.append("[privacy 漂移] baseline code %s ≠ 0" % c)
        c, ck, _ = gcheck(m, pd, both(grw(gworld(DRIFT))))
        exp = (jget(ck, "ch2", "split") or {}).get("expected_unread") or []
        if c != 0 or sorted(exp) != sorted(DRIFT):
            f.append("[privacy 漂移] check code %s;ch2 豁免 %d 支,應是本輪 main 讀到的 %d 支" % (c, len(exp), len(DRIFT)))
        return f

    def G2(m):  # F1:baseline 少一支儀器 ⇒ 不准 0、落檔標不可用、ch2 的 private 不豁免;check 拒比(2)
        f = []
        for tag, worlds, cred in (("main 不可用", {"ch2": {"world": GBASE}, "main": "unavailable"}, None),
                                  ("main 第 2 次出錯", {"ch2": {"world": GBASE},
                                                      "main": {"world": GBASE, "fail_on_call": 2}}, None),
                                  ("--cred ch2", both(GBASE), "ch2")):
            p, c, bl = gbaseline(m, worlds, cred)
            if c != 3:
                f.append("[%s] baseline code %s ≠ 3" % (tag, c))
            if bl.get("usable_as_baseline") is not False:
                f.append("[%s] 落檔沒標不可用:%r" % (tag, bl.get("usable_as_baseline")))
            if jget(bl, "ch2", "code") != 1:
                f.append("[%s] ch2 code %s ≠ 1(同一輪沒有 main ⇒ private 不該豁免)" % (tag, jget(bl, "ch2", "code")))
            c, _, txt = gcheck(m, p, both(grw(GBASE)))
            if c != 2 or "不可作為比較基準" not in txt:
                f.append("[%s] check 沒拒比:code %s" % (tag, c))
        return f

    def G3(m):  # F1:check 這一輪 main 不在 ⇒ ch2 的 private 不豁免(ch2 判 1),overall 3
        p, _c, _bl = okbl(m)
        f = []
        for tag, mw in (("main 不可用", "unavailable"), ("main 第 2 次出錯", {"world": grw(GBASE), "fail_on_call": 2})):
            c, ck, _ = gcheck(m, p, {"ch2": {"world": grw(GBASE)}, "main": mw})
            sp = jget(ck, "ch2", "split") or {}
            if c != 3 or jget(ck, "ch2", "code") != 1 or sp.get("expected_unread") or not INV <= set(sp.get("unread") or []):
                f.append("[%s] overall %s、ch2 code %s、豁免 %d 支(應 3、1、0 支)"
                         % (tag, c, jget(ck, "ch2", "code"), len(sp.get("expected_unread") or [])))
        return f

    def G4(m):  # F1:--cred 排除的儀器 ⇒ 印出來、算 3(check --cred ch2 不准 0)
        p, _c, _bl = okbl(m)
        f = []
        for cred, other, want_j in (("main", "ch2", 0), ("ch2", "main", 1)):
            c, ck, txt = gcheck(m, p, both(grw(GBASE)), ["--cred", cred])
            if c != 3 or jget(ck, cred, "code") != want_j or ("== 儀器 %s | 🔴 本輪沒量" % other) not in txt:
                f.append("[--cred %s] overall %s(應 3)、%s 判 %s(應 %s)" % (cred, c, cred, jget(ck, cred, "code"), want_j))
        return f

    def G5(m):  # F2:陰性對照的描述被動過(不含舊句 / 新句)⇒ 2
        p, _c, _bl = okbl(m)
        f = []
        for tag, vid, d in (("private 對照被清空", CONTROLS[1], "被整段清空之後剩這行"),
                            ("public 對照 📚 行被吃掉", CONTROLS[0], "陰性對照 %s" % CONTROLS[0])):
            w = grw(GBASE)
            w[vid]["snippet"]["description"] = d
            c, _, _ = gcheck(m, p, both(w))
            if c != 2:
                f.append("[%s] code %s ≠ 2" % (tag, c))
        return f

    def G6(m):  # F3:重複 id / nextPageToken 在正式路徑 ⇒ 2(check 和 baseline 都是)
        p, _c, _bl = okbl(m)
        f = []
        old_copy = {TARGETS[0]: copy.deepcopy(GBASE[TARGETS[0]])}
        for tag, kw in (("重複 id(先舊後新)", {"dup": old_copy}), ("nextPageToken", {"page_token": True})):
            c, _, _ = gcheck(m, p, both(grw(GBASE), **kw))
            if c != 2:
                f.append("[check %s] code %s ≠ 2" % (tag, c))
            _p, c, bl = gbaseline(m, both(GBASE, **kw))
            if c != 2 or bl.get("usable_as_baseline") is not False:
                f.append("[baseline %s] code %s、usable %r" % (tag, c, bl.get("usable_as_baseline")))
        return f

    def G7(m):  # F4:--expect-written 解析
        p, _c, _bl = okbl(m)
        u16, bom, empty = (os.path.join(GTMP, n) for n in ("ids_utf16.txt", "ids_bom.txt", "ids_empty.txt"))
        io.open(u16, "w", encoding="utf-16").write("\n".join(CAN) + "\n")
        io.open(bom, "w", encoding="utf-8-sig", newline="").write("\r\n".join(CAN) + "\r\n")
        io.open(empty, "w", encoding="utf-8").write("\n")
        f = []
        for tag, world, extra, want in (
                ("空字串", GBASE, ["--expect-written="], 2),
                ("--expect-none、沒寫", GBASE, ["--expect-none"], 0),
                ("--expect-none、其實寫了", grw(GBASE, CAN), ["--expect-none"], 1),
                ("@UTF-16", grw(GBASE, CAN), ["--expect-written=@" + u16], 2),
                ("@UTF-8 BOM + CRLF", grw(GBASE, CAN), ["--expect-written=@" + bom], 0),
                ("@空檔", GBASE, ["--expect-written=@" + empty], 2),
                ("@不存在", GBASE, ["--expect-written=@" + os.path.join(GTMP, "nope.txt")], 2),
                ("打錯一個字", grw(GBASE, CAN), ["--expect-written=%s,%s" % (CAN[0], CAN[1][:-1] + "u")], 2)):
            c, _, _ = gcheck(m, p, both(world), extra)
            if c != want:
                f.append("[%s] code %s ≠ %s" % (tag, c, want))
        return f

    SCEN = [("S0", "字面值", S0), ("S1", "正常", S1), ("S2", "一支沒改到", S2), ("S3", "別處被動", S3),
            ("S4", "看不到private的儀器", S4), ("S5", "沒回來", S5), ("S6", "陰性對照翻面", S6),
            ("S7", "欄位差異需人判", S7), ("S8", "改寫前鏡像", S8), ("S9", "新句重複", S9), ("S10", "canary範圍", S10),
            ("G1", "正式路徑陽性對照", G1), ("G2", "baseline少儀器", G2), ("G3", "check本輪main不在", G3),
            ("G4", "--cred排除", G4), ("G5", "對照描述被動", G5), ("G6", "重複id/分頁", G6),
            ("G7", "expect-written解析", G7)]

    lit_new = 'NEW = "之後的影片已改進做法,但'
    MUT = [  # (代號, 說明, [(原字串, 突變字串)], 必須翻紅的情境)
        ("BASE", "未突變(同一條 exec 路徑)", [], None),
        ("NC", "陰性對照:改顯示用標籤字串", [('TOOL_TAG = "verify_desc_rewrite"', 'TOOL_TAG = "verify_desc_rewrite_nc"')], None),
        ("M1", "拿掉「新句恰好 1 次、舊句 0 次」",
         [("        ok_count = (n_new == 1 and n_old == 0)\n", "        ok_count = True\n")], "S2"),
        ("M2", "拿掉逐位元組比對",
         [('    ok_bytes = restored.encode("utf-8") == bdesc.encode("utf-8")\n', "    ok_bytes = True\n")], "S3"),
        ("M3", "拿掉 privacy 分組(全部併成一組)",
         [('    return priv_ref.get(vid) or "unknown"\n', '    return "all"\n')], "S4"),
        ("M4", "拿掉「沒回來 = 未讀到」(沒回來的直接跳過)",
         [('            rows[vid] = {"verdict": UNREAD, "reasons": ["送出了、沒回來"], "review": []}\n', "")], "S5"),
        ("M5", "拿掉陰性對照",
         [('    ctrl = judge_controls(pop, cur["items"], cur["sent"], base["items"])\n',
           '    ctrl = {"ok": True, "rows": {}, "bad": []}\n')], "S6"),
        ("M6", "新句字面值抄錯一個標點(半形 , → 全形 ,)", [(lit_new, lit_new.replace(",但", "，但"))], "S0"),
        ("M6b", "M6 + 拿掉 md5 斷言(證明 harness 字面值獨立於受測模組)",
         [(lit_new, lit_new.replace(",但", "，但")), ("if _lp:\n", "if False:\n")], "S1"),
        ("M7a", "欄位差異自動判錯(不是需人判)",
         [('            review.append("欄位 %s 不同(需人判):%r → %r" % (k, bsn.get(k), csn.get(k)))\n',
           '            reasons.append("欄位 %s 不同(需人判):%r → %r" % (k, bsn.get(k), csn.get(k)))\n')], "S7"),
        ("M7b", "欄位差異不列出", [("        if bsn.get(k) != csn.get(k):\n", "        if False:\n")], "S7"),
        ("M8", "拿掉改寫前鏡像(baseline 已有新句也算過)",
         [("        mirror_ok = (o == 1 and n == 0)\n", "        mirror_ok = True\n")], "S8"),
        ("F1a", "--cred 排除的儀器不算 code 3",
         [("            codes.append(3)\n\n\ndef baseline_unusable", "            pass\n\n\ndef baseline_unusable")], "G4"),
        ("F1b", "check 的 ch2 豁免改回用 baseline 的 privacy",
         [('    main_priv = round_privacy(out["instruments"])  # 本輪 main 讀到的(ch2 豁免只認這個)\n',
           '    main_priv = round_privacy(bl["instruments"])\n')], "G3"),
        ("F1c", "baseline 一律標可用",
         [('        out["usable_as_baseline"] = not why\n', '        out["usable_as_baseline"] = True\n')], "G2"),
        ("F1d", "check 不擋不可用的 baseline",
         [("    return why_unusable\n", "    return []\n")], "G2"),
        ("F1e", "baseline 沒 main 時退回 09-11 盤點清單豁免",
         [('    main_priv = round_privacy(out["instruments"])   # 同一輪 main 讀到的;ch2 的豁免只認這個\n',
           '    main_priv = round_privacy(out["instruments"]) or '
           '{v: ("private" if v in INVENTORY_PRIVATE15 else "public") for v in TARGETS}\n')], "G2"),
        ("F2", "陰性對照描述不同只改顯示字串、不進 bad",
         [('            bad.append("陰性對照 %s 的描述和 baseline 不同 ⇒ 範圍外有東西被動過或儀器讀錯;停手、開原檔人判" % vid)\n',
           "")], "G5"),
        ("F3a", "reads_from_calls 不查重複 id",
         [('            if vid in items:\n                problems.append("id 重複回來(後一份蓋掉前一份,讀值不可信):%s" % vid)\n',
           "")], "G6"),
        ("F3b", "reads_from_calls 不查 nextPageToken",
         [('        if resp.get("nextPageToken"):\n            problems.append("第 %d 次回了 nextPageToken(分頁沒處理)" % n)\n',
           "")], "G6"),
        ("F4a", "--expect-written= 空字串不擋",
         [("    if not ids:\n        raise Stop(", "    if False:\n        raise Stop(")], "G7"),
        ("F4b", "@檔案改回 utf-8(不吃 BOM)",
         [('io.open(spec[1:], encoding="utf-8-sig").read()', 'io.open(spec[1:], encoding="utf-8").read()')], "G7"),
        ("F4c", "@檔案解碼錯誤不攔",
         [("        except (UnicodeDecodeError, OSError) as exc:\n", "        except KeyError as exc:\n")], "G7"),
    ]

    print("# %s --self-test  離線;造出來的樣本 + stub service;突變只作用在 SELF-TEST 標記以上" % TOOL_TAG)
    print("# 判準:每個情境的預期寫死在 harness,不來自受測模組\n")
    allpass, evidence = True, {}
    for code, desc, reps, must_red in MUT:
        s, setup_err = prod, None
        for old, new in reps:
            c = s.count(old)
            if c != 1:
                setup_err = "突變原字串出現 %d 次(應 1):%r" % (c, old)
                break
            s = s.replace(old, new)
        reds, load_err = {}, None
        if setup_err is None:
            m = types.ModuleType("vdr_" + code)
            m.__dict__["__file__"] = os.path.abspath(__file__)
            try:
                exec(compile(s, "<verify_desc_rewrite:%s>" % code, "exec"), m.__dict__)
            except Exception as e:  # noqa: BLE001
                load_err = "模組載入即丟 %s:%s" % (type(e).__name__, str(e)[:160])
            for name, _d, fn in SCEN:
                if load_err:
                    reds[name] = [load_err]
                    continue
                try:
                    fails = fn(m)
                except Exception as e:  # noqa: BLE001
                    fails = ["情境本身丟 %s:%s" % (type(e).__name__, str(e)[:120])]
                if fails:
                    reds[name] = fails
        red_keys = sorted(reds, key=lambda k: (k[0] != "S", int(k[1:])))
        if setup_err:
            ok, verdict = False, "❌ " + setup_err
        elif must_red is None:
            ok = not reds
            verdict = "✅ 全綠" if ok else "❌ 應全綠卻紅:%s" % red_keys
        else:
            ok = must_red in reds
            verdict = ("✅ 翻紅(%s)" % must_red) if ok else "❌ 沒翻紅 —— 這條承重行為沒被測到"
        allpass &= ok
        print("%-4s %-46s %s  紅燈情境=%s" % (code, desc, verdict, red_keys or "無"))
        for k in red_keys:
            print("       %s:%s" % (k, " | ".join(reds[k])[:230]))
        evidence[code] = {"desc": desc, "replacements": reps, "must_red": must_red, "ok": ok, "verdict": verdict,
                          "red_scenarios": reds, "setup_error": setup_err}
    shutil.rmtree(GTMP, ignore_errors=True)
    leaked = [k for k in ("googleapiclient", "google.auth", "google.oauth2", "httplib2") + FORBIDDEN_MODULES
              if k in sys.modules]
    print("\n# 零網路 / 獨立性:%s 載入了嗎 → %s" % ("/".join(("googleapiclient", "google.auth", "google.oauth2",
                                                          "httplib2") + FORBIDDEN_MODULES), leaked or "都沒有"))
    allpass &= not leaked
    print("# 情境 %d 個、突變 %d 條(含 BASE / NC 兩條應全綠)" % (len(SCEN), len(MUT)))
    print("SELFTEST_RESULT:", "PASS" if allpass else "FAIL")
    if evidence_dir:
        os.makedirs(evidence_dir, exist_ok=True)
        for code, ev in evidence.items():
            io.open(os.path.join(evidence_dir, "selftest_%s.json" % code), "w", encoding="utf-8", newline="\n").write(
                json.dumps(ev, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        summary = {"result": "PASS" if allpass else "FAIL", "leaked_modules": leaked,
                   "tool_blob": git_blob(os.path.abspath(__file__)),
                   "mutations": {k: {"ok": v["ok"], "must_red": v["must_red"], "red": sorted(v["red_scenarios"])}
                                 for k, v in evidence.items()}}
        io.open(os.path.join(evidence_dir, "selftest_summary.json"), "w", encoding="utf-8", newline="\n").write(
            json.dumps(summary, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        print("# 證據檔 → %s" % evidence_dir)
    return 0 if allpass else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    sys.exit(main())
