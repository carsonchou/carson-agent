# -*- coding: utf-8 -*-
"""單支影片的 description 還原工具 —— 還原成 fix_period_disclaimer --rewrite-note 寫入前另存的
STUDIO/desc_backup/<vid>.pre_rewrite.json(fix_period_disclaimer.py:867-887)。只動 description。

預設 dry-run(1 次 videos.list = 1 unit,零 update)。真寫要同時帶 --apply 和
--confirm-sha1=<dry-run 印出的「當下線上 description」sha1>(1 + 50 + 1 = 52 units)。

承重行為(每一條都是程式碼、都有 --self-test 的突變列,拿掉要有情境翻紅):
  M1 來源寫死   只讀 STUDIO/desc_backup/<vid>.pre_rewrite.json;不存在就拒絕。
                🔴 絕不退回 desc_backup/<vid>.json —— 那是第一次插入更正之前的舊版
                (沒有更正段、標題舊、語言欄舊),拿它還原會把三樣一起倒回去。
  M2 只准 description 差異  送出前拿「線上 snippet 的每個非唯讀鍵 ∪ body 的鍵」逐一比對,
                差異集合必須恰好是 {description};多一欄就拒寫。基準刻意不是 _WRITABLE_SNIPPET
                那張表 —— 線上有、表裡沒有的鍵(YouTube 新加的可寫欄位)會被整包覆蓋清掉,這裡是拒寫。
  M3 confirm-sha1  --apply 會重讀線上值;sha1(description) ≠ --confirm-sha1 就拒寫
                (dry-run 之後線上被第三方改過 ⇒ 不蓋掉別人的改動)。
  M4 其他欄位用線上值  body 裡 description 以外的可寫欄位一律取「當下讀回」的 snippet,不用備份裡的舊值。
  M5 前置條件   a) 線上 description 已逐字等於 pre_rewrite ⇒ 印「不需還原」、exit 0、不寫。
                b) 線上既找不到新句也找不到舊句 ⇒ 拒寫(被別人改過,現況不明)。
  —— 以下是 wF:p5 定案的兩條准寫判準(docs/ops/2026-09-12_84支寫入把關清單_wF-p3.md:65-77,commit 6b77c90f),兩條都要成立:
  M8 (a) 段外有差 ⇒ 拒寫  線上與 pre_rewrite 的逐字差異必須全部落在 pre_rewrite 舊句所在那一段
                (段 = 空白行分隔;與段相鄰的空白 / 換行多寡可以不同,但段前段後的空白行本身要在 ——
                否則分不出字是補在這段還是隔壁段)。段外有差 ⇒ 別的 job 動過 ⇒ exit 1、要人判;
                🔴 任何旗標都蓋不過(M8b:被 --accept-needs-human 蓋過要翻紅)。
                刻意**不是**「線上 == pre_rewrite 換上新句才寫」—— wF:p5 駁回:寫壞了才需要還原,
                那條只放寫對的、擋寫壞的,方向反了(M10:換成它,「段內寫壞」那個陽性情境要翻紅)。
  M6/M7 (b) 長度對 STAMP  線上 description 長度 == 寫入端 STAMP 該支的 new_len。new_len 的取法:
                最後一筆 ok 行 → sent_at 完全相同的 sent 行 → 它的 new_len
                (🔴 ok 行沒有 new_len,fix_period_disclaimer.py:922-924;sent 行才有,:893-894 —— M6)。
                長度不等 / 沒有 ok 行(只有 sent、error)/ 對不到 sent 行 / 最後一筆 ok 之後還有 sent 或 error /
                STAMP 不存在或有解析不了的行 ⇒ 需人判(exit 4);apply 要**同時**帶 --accept-needs-human 與
                --confirm-sha1 才寫(M7)。這條較弱(STAMP 沒記 body hash),所以是「需人判」不是拒寫。
  M9 還原時間戳  sent / ok / error 寫進 restore/restore_stamp.jsonl(格式同 STAMP,另加 tool 欄)。
                🔴 不寫進寫入端 STAMP:它的 _stamped()(fix_period_disclaimer.py:564-582)只看 vid 與
                phase ∈ (sent, ok),還原的行混進去會被當成它自己寫過,重跑判成已完成、把還原蓋回去。
其他:
  - 新句 / 舊句逐字抄自 fix_period_disclaimer.py(blob 35149f7e)的 _TAIL_OLD / _TAIL_NEW(去掉結尾 \\n),
    載入時核 md5;不 import 它。來源檔內容另核「舊句恰 1 次、新句 0 次」,不像改寫前原文就拒絕。
  - 配額照 fix_period_disclaimer 的走法:daily_publish.get_service()(內掛 quota_meter.install)。
    service 建好後核 HttpRequest._quota_metered,沒掛上就拒絕。門檻 / ENFORCE / RESERVE 只讀不改。
  - 所有 execute(num_retries=0);遇錯即停,不重試。dry-run 外包 _NoWrite,只放行 videos().list。
  - apply:送出前把「重讀的線上 snippet」和「body」落檔,送出後把回應和讀回一次(T0,不算證據)也落檔;
    位置 docs/ops/2026-09-11_84支描述欄改寫_事後回讀計畫/restore/,檔名開頭是 ISO 8601 基本格式時間
    (Windows 檔名不能有冒號);不覆蓋既有檔,tmp → fsync → 讀回比對 → os.replace。
  - 沒有 vid 白名單:有 pre_rewrite 檔的任何一支都能還原。一次一支。

用法(在 youtube_channel/ 下;--vid / --confirm-sha1 一定要用等號 —— id 可能以 - 開頭):
  .venv\\Scripts\\python.exe scripts\\restore_desc_pre_rewrite.py --self-test
  .venv\\Scripts\\python.exe scripts\\restore_desc_pre_rewrite.py --vid=-_aUs0oj1o0
  .venv\\Scripts\\python.exe scripts\\restore_desc_pre_rewrite.py --apply --vid=-_aUs0oj1o0 --confirm-sha1=<40 位小寫 hex>
  (dry-run 回 4 = 需人判時,人看過差異與理由、決定仍要還原,apply 才另加 --accept-needs-human;dry-run 會把整行印出來)

exit code:0 成功 / 不需還原 / dry-run 可還原 | 1 拒寫(含參數錯、來源缺、(a) 段外有差)
         | 2 API 錯誤(Google 回錯,或本機 quota_meter 在送出前擋下;訊息寫明是哪一個)
           ——另:update 已送出且回應相符、但事後落檔 / 時間戳或 T0 讀回失敗,也是 2(訊息寫明寫入已送出)。
         | 4 需人判((b) 不成立;dry-run 或沒帶 --accept-needs-human 的 apply,都不寫)
"""
import argparse, datetime, difflib, hashlib, io, json, os, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent            # youtube_channel/
REPO = ROOT.parent
BACKUP_DIR = ROOT / "STUDIO" / "desc_backup"
PRE_SUFFIX = ".pre_rewrite.json"
EVID_DIR = REPO / "docs" / "ops" / "2026-09-11_84支描述欄改寫_事後回讀計畫" / "restore"
# 寫入端的時間戳(fix_period_disclaimer.py:535-536)。🔴 只讀;還原的時間戳另開 RESTORE_STAMP
STAMP = REPO / "docs" / "ops" / "2026-09-11_84支更正句改寫_寫入時間戳.jsonl"
RESTORE_STAMP = EVID_DIR / "restore_stamp.jsonl"
TOOL = "restore_desc_pre_rewrite"
DRY_TAG = "DRY-RUN"
EXIT_OK, EXIT_REFUSE, EXIT_API, EXIT_HUMAN = 0, 1, 2, 4

# ---------------------------------------------------------------- 字面值(抄寫,不 import)
# 逐字抄自 fix_period_disclaimer.py 的 _TAIL_OLD / _TAIL_NEW,去掉結尾 \n。半形 , ; —— 句尾全形 。
_SENT_OLD = "之後的影片已改成在同一句標明期間。"
_SENT_NEW = "之後的影片已改進做法,但仍可能有漏的;看到請留言告訴我,我會補上更正。"
_OLD_MD5 = "e9f13a327f665ad742eceabc1340a900"
_NEW_MD5 = "1d873574fdb646dc27e9dc5c6a99cd29"
for _n, _s, _w in (("_SENT_OLD", _SENT_OLD, _OLD_MD5), ("_SENT_NEW", _SENT_NEW, _NEW_MD5)):
    if hashlib.md5(_s.encode("utf-8")).hexdigest() != _w:
        raise SystemExit("🔴 字面值 %s 被動過(md5 ≠ 寫死的 %s)—— 停" % (_n, _w))

# 抄自 fix_period_disclaimer.py:596-599(不 import)
_READONLY_SNIPPET = ("publishedAt", "channelId", "thumbnails", "channelTitle",
                     "liveBroadcastContent", "localized")
_WRITABLE_SNIPPET = ("title", "description", "tags", "categoryId",
                     "defaultLanguage", "defaultAudioLanguage")

VID_RE = re.compile(r"[A-Za-z0-9_-]{11}")
SHA1_RE = re.compile(r"[0-9a-f]{40}")

LOCAL_MSG = ("🔴 本機 quota_meter 擋下的,不是 Google(這一筆沒有離開本機)。停,不重試;"
             "門檻 / ENFORCE / RESERVE 不准改。[%s] 原訊息:%s")
GOOGLE_MSG = "🔴 Google 回錯誤 —— 停,不重試。[%s] %s"


class Refuse(Exception):
    """拒寫(exit 1)。"""


class ApiError(Exception):
    """API 錯誤(exit 2)。local=True 表示是本機 quota_meter 在送出前擋的。"""

    def __init__(self, msg, local=False):
        Exception.__init__(self, msg)
        self.local = local


class NeedsHuman(Exception):
    """(b) 不成立、沒帶 --accept-needs-human(exit 4)。不是 Refuse 的子類:不能被當成拒寫吞掉。"""


class DryRunWriteAttempt(Refuse):
    pass


def now_tw():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))


def now_pair():
    """同 fix_period_disclaimer._now 的形狀:{"utc": ISO 毫秒, "tpe": "YYYY-mm-dd HH:MM:SS.fff"}。"""
    u = datetime.datetime.now(datetime.timezone.utc)
    t = u.astimezone(datetime.timezone(datetime.timedelta(hours=8)))
    return {"utc": u.isoformat(timespec="milliseconds"), "tpe": t.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]}


def desc_sha1(s):
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()


def _nz(v):
    return None if v in (None, "", []) else v


# ---------------------------------------------------------------- API(不重試;分主詞)
def _client_side_quota(exc):
    """同 fix_period_disclaimer._client_side_quota:quota_meter 在送出**之前**丟 QuotaExhausted,
    訊息開頭固定是 `quota exhausted:` 或 `quota reserve:`;Google 的真 403 走 HttpError。"""
    if type(exc).__name__ == "QuotaExhausted":
        return True
    msg = str(exc)
    return msg.startswith("quota exhausted:") or msg.startswith("quota reserve:")


def _execute(req, label, counter):
    counter[label] = counter.get(label, 0) + 1
    try:
        return req.execute(num_retries=0)
    except Exception as exc:  # noqa: BLE001
        if _client_side_quota(exc):
            raise ApiError(LOCAL_MSG % (label, str(exc)[:200]), local=True)
        raise ApiError(GOOGLE_MSG % (label, repr(exc)[:300]))


def read_live(yt, vid, counter, label="videos.list"):
    resp = _execute(yt.videos().list(part="snippet", id=vid), label, counter)
    items = [it for it in ((resp or {}).get("items") or []) if it.get("id") == vid]
    if len(items) != 1 or not isinstance(items[0].get("snippet"), dict):
        raise Refuse("🔴 videos.list 沒回這支(或沒有 snippet):%s —— 未讀到,不是通過;不寫" % vid)
    return items[0]["snippet"]


# ---------------------------------------------------------------- M1 來源(寫死)
def source_path(vid):
    return BACKUP_DIR / (vid + PRE_SUFFIX)


def load_source(vid):
    """只讀 <vid>.pre_rewrite.json。🔴 不存在就拒絕;絕不退回 <vid>.json。回傳 (路徑, 檔案 sha1, snippet)。"""
    p = source_path(vid)
    if not p.is_file():
        raise Refuse("🔴 來源缺:%s 不存在 —— 拒絕。不會退回去讀 %s.json"
                     "(那是第一次插入更正之前的舊版:沒有更正段、標題舊、語言欄舊)" % (p, vid))
    raw = p.read_bytes()
    try:
        sn = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise Refuse("🔴 來源讀不動:%s(%s)—— 拒絕" % (p.name, str(exc)[:80]))
    if not isinstance(sn, dict) or not isinstance(sn.get("description"), str) or not sn["description"]:
        raise Refuse("🔴 來源不是 snippet dict 或沒有 description:%s —— 拒絕" % p.name)
    d = sn["description"]
    if d.count(_SENT_OLD) != 1 or _SENT_NEW in d:
        raise Refuse("🔴 來源內容不像改寫前的原文(舊句 %d 次、新句 %d 次;應 1 / 0):%s —— 拒絕"
                     % (d.count(_SENT_OLD), d.count(_SENT_NEW), p.name))
    return p, hashlib.sha1(raw).hexdigest(), sn


# ---------------------------------------------------------------- M4 body / M2 差異
def build_body(vid, live_sn, target_desc):
    """description 換成 pre_rewrite 原文;其餘可寫欄位一律取**當下線上讀回**的值。"""
    snip = {}
    for k in _WRITABLE_SNIPPET:
        if k == "description":
            snip[k] = target_desc
            continue
        v = live_sn.get(k)
        if v in (None, "", []):
            continue
        snip[k] = list(v) if isinstance(v, list) else v
    return {"id": vid, "snippet": snip}


def body_problems(vid, live_sn, body, target_desc):
    """🔴 送出前最後一道。基準是**線上 snippet 自己的每個鍵**(只跳過 API 唯讀鍵;不認得的鍵一律
    當成必須帶),不是 build_body 用的那張表。差異集合必須恰好是 {description}。回傳問題清單,空 = 通過。"""
    bad = []
    if sorted(body) != ["id", "snippet"] or body.get("id") != vid:
        bad.append("body 外層不是 {id=%s, snippet}:%r" % (vid, sorted(body)))
    snip = body.get("snippet") or {}
    alien = sorted(set(snip) - set(_WRITABLE_SNIPPET))
    if alien:
        bad.append("body 帶了非可寫欄位:%s" % alien)
    keys = {k for k in live_sn if k not in _READONLY_SNIPPET} | set(snip)
    diff = sorted(k for k in keys if _nz(live_sn.get(k)) != _nz(snip.get(k)))
    extra = [k for k in diff if k != "description"]
    if extra:
        bad.append("description 以外有差異:" + "; ".join(
            "%s 線上 %.40r → body %.40r" % (k, live_sn.get(k), snip.get(k)) for k in extra))
    if snip.get("description") != target_desc:
        bad.append("body.description 不是 pre_rewrite 原文")
    if "description" not in diff:
        bad.append("description 沒有差異(不需要寫)")
    return bad


# ---------------------------------------------------------------- M8 (a) 差異只准在舊句那一段
_BLANK_LINE = re.compile(r"\n[^\S\n]*\n")


def old_para_bounds(target):
    """pre_rewrite 裡舊句所在那一段的 [起, 迄)。段 = 空白行分隔。load_source 已保證舊句恰 1 次。"""
    i = target.index(_SENT_OLD)
    j = i + len(_SENT_OLD)
    ps = 0
    for mm in _BLANK_LINE.finditer(target):       # 舊句本身沒有換行 ⇒ 空白行不可能跨過它
        if mm.end() <= i:
            ps = mm.end()
        elif mm.start() >= j:
            return ps, mm.start()
    return ps, len(target)


def outside_para_diff(live, target):
    """回 None = 線上與 pre_rewrite 的差異全部落在舊句那一段;否則回一句「段外哪裡不同」。
    段外文字 = pre_rewrite 在那一段之前 / 之後的全部,逐字比;只有與段相鄰的空白 / 換行不算(rstrip / lstrip)。"""
    ps, pe = old_para_bounds(target)
    head, tail = target[:ps].rstrip(), target[pe:].lstrip()
    if not live.startswith(head):
        k = next((n for n, (x, y) in enumerate(zip(live, head)) if x != y), min(len(live), len(head)))
        return "段前第 %d 字起不同:線上 %.40r / pre_rewrite %.40r" % (k, live[k:k + 40], head[k:k + 40])
    if not live.endswith(tail):
        k = next((n for n, (x, y) in enumerate(zip(live[::-1], tail[::-1])) if x != y),
                 min(len(live), len(tail)))
        return ("段後(倒數第 %d 字往前)不同:線上 %.40r / pre_rewrite %.40r"
                % (k, live[max(0, len(live) - k - 40):len(live) - k], tail[max(0, len(tail) - k - 40):len(tail) - k]))
    if len(head) + len(tail) > len(live):
        return "線上比段外文字還短(段前 %d + 段後 %d > 線上 %d)⇒ 段外被刪過" % (len(head), len(tail), len(live))
    # 🔴 段的邊界(空白行)本身要還在:只比 startswith / endswith 的話,補在隔壁段結尾 / 開頭的字
    #    (「第一段正文(別的 job 補的)」)會被算進舊句那一段而放行。空白的量可以變,空白行不能不見。
    mid = live[len(head):len(live) - len(tail)]
    if head and not _BLANK_LINE.search(mid[:len(mid) - len(mid.lstrip())]):
        return "段前的空白行不見了(字補在上一段結尾,或兩段被併起來):線上 %.40r" % mid[:40]
    if tail and not _BLANK_LINE.search(mid[len(mid.rstrip()):]):
        return "段後的空白行不見了(字補在下一段開頭,或兩段被併起來):線上 %.40r" % mid[-40:]
    return None


# ---------------------------------------------------------------- M6/M7 (b) 長度對寫入端 STAMP(只讀)
def stamp_check(vid, live_len):
    """回 (需人判理由清單, new_len)。空清單 = (b) 成立。
    new_len 取法(wF:p5 定案):最後一筆 ok 行 → sent_at 完全相同的 sent 行 → 它的 new_len。
    🔴 ok 行沒有 new_len(fix_period_disclaimer.py:922-924),只有 sent 行有(:893-894)。"""
    if not STAMP.is_file():
        return ["寫入端 STAMP 不存在(%s)⇒ 沒有寫入紀錄可對" % STAMP], None
    rows, bad = [], 0
    for ln in STAMP.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            row = json.loads(ln)
        except ValueError:
            bad += 1
            continue
        if isinstance(row, dict) and row.get("vid") == vid:
            rows.append(row)
    reasons = []
    if bad:
        reasons.append("STAMP 有 %d 行解析不了(可能正是這支的紀錄;未讀到不是通過)" % bad)
    oks = [n for n, r in enumerate(rows) if r.get("phase") == "ok"]
    if not oks:
        reasons.append("STAMP 裡這支沒有 ok 行(這支的 phase 依序:%s)⇒ 寫入狀態未知"
                       % [r.get("phase") for r in rows])
        return reasons, None
    ok = rows[oks[-1]]
    later = [r.get("phase") for r in rows[oks[-1] + 1:] if r.get("phase") in ("sent", "error")]
    if later:
        reasons.append("最後一筆 ok 之後還有 %s ⇒ 線上可能是之後那次寫的" % later)
    sents = [r for r in rows if r.get("phase") == "sent" and ok.get("sent_at")
             and r.get("sent_at") == ok.get("sent_at")]
    if len(sents) != 1:
        reasons.append("sent_at 與最後一筆 ok 完全相同的 sent 行有 %d 行(應 1)" % len(sents))
        return reasons, None
    new_len = sents[0].get("new_len")
    if type(new_len) is not int:
        reasons.append("取到的 new_len 不是整數:%r" % (new_len,))
    elif live_len != new_len:
        reasons.append("線上 description 長度 %d ≠ STAMP new_len %d(ok 行 sent_at=%s)"
                       % (live_len, new_len, (ok.get("sent_at") or {}).get("tpe")))
    return reasons, new_len


# ---------------------------------------------------------------- M9 還原時間戳(另開檔)
def rstamp(row):
    """一行一筆,逐行 flush + fsync。🔴 只寫 RESTORE_STAMP,絕不寫寫入端 STAMP(見 docstring M9)。"""
    if RESTORE_STAMP.resolve() == STAMP.resolve():
        raise Refuse("🔴 RESTORE_STAMP 指到寫入端 STAMP —— 拒寫")
    RESTORE_STAMP.parent.mkdir(parents=True, exist_ok=True)
    with RESTORE_STAMP.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


# ---------------------------------------------------------------- 落檔(不覆蓋;tmp → fsync → 讀回 → replace)
def write_new_json(path, obj):
    path = Path(path)
    if path.exists():
        raise Refuse("🔴 不覆蓋既有檔:%s" % path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    tmp = path.with_name(path.name + ".tmp")
    with io.open(str(tmp), "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    if tmp.read_bytes() != data:
        raise Refuse("🔴 暫存檔讀回不符:%s" % tmp)
    os.replace(str(tmp), str(path))
    return path


def _post_write(out, path, obj):
    """送出**之後**的落檔:失敗不能假裝沒送,印出來、回 False。"""
    try:
        write_new_json(path, obj)
        return True
    except Exception as exc:  # noqa: BLE001
        out("🔴 落檔失敗(videos.update 已送出):%s —— %s" % (Path(path).name, str(exc)[:160]))
        return False


def print_diff(out, live_desc, target):
    lines = list(difflib.unified_diff(live_desc.split("\n"), target.split("\n"),
                                      fromfile="線上", tofile="還原目標", n=0, lineterm=""))
    for x in lines[:40]:
        out("    " + x)
    if len(lines) > 40:
        out("    …(另 %d 行)" % (len(lines) - 40))


# ---------------------------------------------------------------- 主流程
def run(yt, vid, apply, confirm_sha1, out, counter, accept_human=False):
    live_sn = read_live(yt, vid, counter)                      # apply 時這就是「重讀」
    live_desc = live_sn.get("description") or ""
    live_sha1 = desc_sha1(live_desc)
    out("線上  %s  title=%r" % (vid, live_sn.get("title", "")))
    out("      description sha1=%s  長度 %d  新句 %d 次、舊句 %d 次"
        % (live_sha1, len(live_desc), live_desc.count(_SENT_NEW), live_desc.count(_SENT_OLD)))

    src_path, src_file_sha1, src_sn = load_source(vid)
    target = src_sn["description"]
    out("來源  %s(檔案 sha1=%s)" % (src_path, src_file_sha1))
    out("      pre_rewrite description sha1=%s  長度 %d" % (desc_sha1(target), len(target)))

    # M5a
    if live_desc == target:
        out("✅ 不需還原:線上 description 已逐字等於 pre_rewrite。不寫。")
        return EXIT_OK
    # M5b
    if _SENT_NEW not in live_desc and _SENT_OLD not in live_desc:
        raise Refuse("🔴 線上 description 既沒有新句也沒有舊句 —— 被別人改過、現況不明,拒寫")
    # M8 (a):差異只准落在舊句那一段;段外有差 ⇒ 直接拒寫,任何旗標都蓋不過
    ps, pe = old_para_bounds(target)
    outside = outside_para_diff(live_desc, target)
    if outside:
        out("      description 差異(線上 → pre_rewrite),給人判用:")
        print_diff(out, live_desc, target)
        raise Refuse("🔴 (a) 段外有差 —— 別的 job 動過,拒寫、要人判(--accept-needs-human 也蓋不過):" + outside)
    out("(a) 差異全在 pre_rewrite 舊句那一段(第 %d–%d 字)✅" % (ps, pe))
    # M3
    if apply:
        if live_sha1 != confirm_sha1:
            raise Refuse("🔴 線上 description sha1=%s ≠ --confirm-sha1=%s —— dry-run 之後線上被改過(或貼錯),"
                         "拒寫;重跑 dry-run 看過再說" % (live_sha1, confirm_sha1))
    # M6 / M7 (b)
    needs, new_len = stamp_check(vid, len(live_desc))
    out("(b) 寫入端 STAMP(只讀)=%s" % STAMP)
    if needs:
        out("(b) 🟠 需人判:")
        for r in needs:
            out("      - " + r)
    else:
        out("(b) 線上長度 %d == STAMP new_len %d ✅" % (len(live_desc), new_len))
    # M4 / M2
    body = build_body(vid, live_sn, target)
    bad = body_problems(vid, live_sn, body, target)
    if bad:
        raise Refuse("🔴 body 檢查不過,拒寫:" + " | ".join(bad))
    out("body  part=snippet  帶的欄位:%s(description 以外皆取當下線上值)" % ",".join(body["snippet"]))
    out("      與線上的差異:只有 description ✅")
    out("      description 差異(線上 → 還原目標):")
    print_diff(out, live_desc, target)
    if not apply:
        cmd = ("  .venv\\Scripts\\python.exe scripts\\restore_desc_pre_rewrite.py --apply --vid=%s --confirm-sha1=%s"
               % (vid, live_sha1))
        if needs:
            out("%s:不送。🟠 需人判(exit 4)—— 人看過上面的差異與 (b) 理由、決定仍要還原,才逐字跑"
                "(sha1 是**這一刻**線上 description 的):" % DRY_TAG)
            out(cmd + " --accept-needs-human")
            return EXIT_HUMAN
        out("%s:不送。確認上面的差異後,要還原請逐字跑(sha1 是**這一刻**線上 description 的):" % DRY_TAG)
        out(cmd)
        return EXIT_OK
    if needs and not accept_human:
        raise NeedsHuman("🟠 需人判((b) 不成立),沒帶 --accept-needs-human —— 不寫(exit 4):" + " | ".join(needs))
    if accept_human and not needs:
        out("# 註:給了 --accept-needs-human,但本次 (b) 成立、不需人判")
    checks = {"a_para": [ps, pe], "b_new_len": new_len, "b_needs_human": needs,
              "accept_needs_human": bool(accept_human)}
    return _apply(yt, vid, live_sn, body, target, src_path, src_file_sha1, out, counter, checks)


def _apply(yt, vid, live_sn, body, target, src_path, src_file_sha1, out, counter, checks):
    stamp = now_tw().strftime("%Y%m%dT%H%M%S%z")          # ISO 8601 基本格式
    base = "%s_%s_" % (stamp, vid)
    meta = {"tool": TOOL, "vid": vid, "taken_at": now_tw().isoformat(timespec="seconds"),
            "source": str(src_path), "source_file_sha1": src_file_sha1, "checks": checks}
    # 送出**之前**就落盤:「送出了但回應丟了」那一種也要有紀錄
    write_new_json(EVID_DIR / (base + "before.json"),
                   dict(meta, phase="before", note="送出前重讀的線上 snippet", snippet=live_sn,
                        description_sha1=desc_sha1(live_sn.get("description"))))
    write_new_json(EVID_DIR / (base + "body.json"),
                   dict(meta, phase="body", note="videos.update 送出的內容", part="snippet", body=body,
                        description_sha1=desc_sha1(target)))
    out("落檔(送出前):%s  %sbefore.json / %sbody.json" % (EVID_DIR, base, base))
    # M9 送出時間在呼叫**之前**落盤(同 fix_period_disclaimer:889-894 的理由),寫到 RESTORE_STAMP
    sent_at = now_pair()
    try:
        rstamp({"tool": TOOL, "vid": vid, "idx": None, "phase": "sent", "sent_at": sent_at,
                "old_len": len(live_sn.get("description") or ""), "new_len": len(target),
                "accept_needs_human": bool(checks.get("accept_needs_human"))})
    except Exception as exc:  # noqa: BLE001
        raise Refuse("🔴 落不了 %s(還沒送)—— 不寫:%s" % (RESTORE_STAMP.name, str(exc)[:160]))
    try:
        resp = _execute(yt.videos().update(part="snippet", body=body), "videos.update", counter)
    except ApiError as exc:
        try:
            rstamp({"tool": TOOL, "vid": vid, "idx": None, "phase": "blocked" if exc.local else "error",
                    "by": "本機 quota_meter" if exc.local else "未知", "sent_at": sent_at,
                    "recv_at": now_pair(), "error": str(exc)[:400]})
        except Exception as e2:  # noqa: BLE001
            out("🔴 %s 落不了 error 行:%s" % (RESTORE_STAMP.name, str(e2)[:160]))
        _post_write(out, EVID_DIR / (base + "update_result.json"),
                    dict(meta, phase="update_result", ok=False, error=str(exc)))
        raise
    try:
        rstamp({"tool": TOOL, "vid": vid, "idx": None, "phase": "ok", "sent_at": sent_at,
                "recv_at": now_pair(), "etag": (resp or {}).get("etag"), "resp_id": (resp or {}).get("id")})
        stamped = True
    except Exception as exc:  # noqa: BLE001
        out("🔴 %s 落不了 ok 行(videos.update 已送出):%s" % (RESTORE_STAMP.name, str(exc)[:160]))
        stamped = False
    wrote = _post_write(out, EVID_DIR / (base + "update_result.json"),
                        dict(meta, phase="update_result", ok=True, response=resp)) and stamped
    got = ((resp or {}).get("snippet") or {}).get("description")
    if got != target:
        raise ApiError(GOOGLE_MSG % ("videos.update", "寫入已送出,但回應的 description ≠ 還原目標(回應 sha1=%s)"
                                     % desc_sha1(got)))
    out("✅ videos.update 已送出;回應的 description == pre_rewrite 原文")
    try:
        after = read_live(yt, vid, counter, "videos.list(T0)")
    except (ApiError, Refuse) as exc:
        raise ApiError("🔴 寫入已送出且回應相符,但 T0 讀回失敗 —— 停,不重試:%s" % exc)
    a_desc = after.get("description") or ""
    wrote &= _post_write(out, EVID_DIR / (base + "after_T0.json"),
                         dict(meta, phase="after_T0", note="T0,不算證據(可能是快取;證據要之後用獨立儀器回讀)",
                              snippet=after, description_sha1=desc_sha1(a_desc)))
    out("T0 讀回(T0,不算證據):description %s pre_rewrite 原文  sha1=%s"
        % ("==" if a_desc == target else "🔴 ≠", desc_sha1(a_desc)))
    for k in _WRITABLE_SNIPPET:
        if k != "description" and _nz(after.get(k)) != _nz(live_sn.get(k)):
            out("  🔴 T0 %s 與送出前不同:%.40r → %.40r" % (k, live_sn.get(k), after.get(k)))
    if not wrote:
        out("🔴 寫入已送出,但事後落檔不完整(見上)")
        return EXIT_API
    return EXIT_OK


# ---------------------------------------------------------------- dry-run 的寫入封鎖
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


# ---------------------------------------------------------------- 參數
class _AP(argparse.ArgumentParser):
    def error(self, message):                                  # argparse 預設 exit 2 會跟「API 錯誤」撞號
        raise Refuse("🔴 參數錯誤:%s" % message)


def build_parser():
    ap = _AP(prog=TOOL, allow_abbrev=False, description="把單支 description 還原成 pre_rewrite(預設 dry-run)")
    ap.add_argument("--vid", help="影片 id;一定要寫成 --vid=<id>")
    ap.add_argument("--apply", action="store_true", help="🔴 真的送 videos.update(要配 --confirm-sha1)")
    ap.add_argument("--confirm-sha1", dest="confirm_sha1",
                    help="dry-run 印出的線上 description sha1;一定要寫成 --confirm-sha1=<hex>")
    ap.add_argument("--accept-needs-human", dest="accept_needs_human", action="store_true",
                    help="dry-run 回 4(需人判)且人已判過要還原時才帶;只蓋 (b),蓋不過 (a) 段外有差")
    ap.add_argument("--self-test", action="store_true", help="離線自我檢查 + 突變列(零網路)")
    return ap


def parse_args(argv):
    for tok in argv:
        if tok in ("--vid", "--confirm-sha1"):
            raise Refuse("🔴 %s 一定要用等號:%s=<值>(id 可能以 - 開頭,空格分開會被當成另一個參數)" % (tok, tok))
    a = build_parser().parse_args(argv)
    if a.self_test:
        if a.apply or a.vid or a.confirm_sha1 or a.accept_needs_human:
            raise Refuse("🔴 --self-test 不能配其他參數")
        return a
    if a.accept_needs_human and not a.apply:
        raise Refuse("🔴 --accept-needs-human 只能配 --apply(dry-run 不需要它)—— 拒絕")
    if not a.vid or not VID_RE.fullmatch(a.vid):
        raise Refuse("🔴 --vid 缺或格式不對(應 11 字元 [A-Za-z0-9_-]):%r" % a.vid)
    if a.apply:
        if not a.confirm_sha1 or not SHA1_RE.fullmatch(a.confirm_sha1):
            raise Refuse("🔴 --apply 必須同時帶 --confirm-sha1=<dry-run 印出的 40 位小寫 hex>:%r" % a.confirm_sha1)
    elif a.confirm_sha1:
        raise Refuse("🔴 沒有 --apply 卻給了 --confirm-sha1 —— 不確定要做哪一個,拒絕")
    return a


def _real_service(out):
    """照 fix_period_disclaimer 的走法:daily_publish.get_service()(內掛 quota_meter)。quota_meter 只讀不改。"""
    os.chdir(str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    import quota_meter as qm
    import daily_publish as dp
    out("# quota_meter(唯讀):ENFORCE=%s RESERVE=%s remaining=%s" % (qm.ENFORCE, qm.RESERVE, qm.remaining()))
    yt = dp.get_service()
    from googleapiclient.http import HttpRequest
    if not getattr(HttpRequest, "_quota_metered", False):
        raise Refuse("🔴 quota_meter 沒掛上(HttpRequest._quota_metered 不是 True)—— 呼叫不會進帳本,拒絕")
    out("# quota_meter 已掛上(HttpRequest._quota_metered=True)")
    return yt, qm.remaining


def main(argv=None, _service_factory=None, out=print):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        a = parse_args(argv)
    except Refuse as e:
        out(str(e))
        return EXIT_REFUSE
    if a.self_test:
        return self_test()
    counter, remaining = {}, None
    out("# %s  %s  模式=%s  vid=%s" % (TOOL, now_tw().isoformat(timespec="seconds"),
                                       "APPLY" if a.apply else DRY_TAG, a.vid))
    out("# 來源(寫死)=%s" % source_path(a.vid))
    try:
        try:
            yt, remaining = (_service_factory or _real_service)(out)
        except (Refuse, ApiError):
            raise
        except Exception as exc:  # noqa: BLE001
            raise ApiError("🔴 建 service 失敗(沒有任何 YouTube API 呼叫送出)—— 停:%r" % (exc,))
        if not a.apply:
            yt = _NoWrite(yt)
        code = run(yt, a.vid, a.apply, a.confirm_sha1, out, counter, a.accept_needs_human)
    except Refuse as e:
        out(str(e))
        code = EXIT_REFUSE
    except NeedsHuman as e:
        out(str(e))
        code = EXIT_HUMAN
    except ApiError as e:
        out(str(e))
        code = EXIT_API
    out("# 本次 API 嘗試:%s(list 1 unit、update 50 unit)"
        % (json.dumps(counter, ensure_ascii=False, sort_keys=True) if counter else "0 次"))
    if remaining is not None:
        try:
            out("# quota_meter remaining(事後,唯讀)=%s" % remaining())
        except Exception as exc:  # noqa: BLE001
            out("# quota_meter remaining 讀不到:%r" % (exc,))
    out("# exit=%d" % code)
    return code


# ======== SELF-TEST(不屬於正式路徑;突變只作用在本行以上的原始碼) ========
def self_test():
    """離線自我檢查。讀本檔原始碼 → 對「標記以上」做字串突變 → exec 成獨立模組 → 對假 client 跑情境。
    判準獨立於受測模組:上線 body 由這裡另外拿「送出前的線上 snippet」逐欄比對;字面值 harness 自己抄一份。"""
    import copy, shutil, tempfile, types

    src = io.open(os.path.abspath(__file__), encoding="utf-8").read()
    mark = "# ======" + "== SELF-TEST"
    prod = src[:src.index(mark)]

    H_OLD = "之後的影片已改成在同一句標明期間。"
    H_NEW = "之後的影片已改進做法,但仍可能有漏的;看到請留言告訴我,我會補上更正。"
    if (hashlib.md5(H_OLD.encode("utf-8")).hexdigest() != "e9f13a327f665ad742eceabc1340a900"
            or hashlib.md5(H_NEW.encode("utf-8")).hexdigest() != "1d873574fdb646dc27e9dc5c6a99cd29"):
        print("❌ harness 字面值 md5 不符")
        return 1
    H_RO = ("publishedAt", "channelId", "thumbnails", "channelTitle", "liveBroadcastContent", "localized")

    def H_SHA(s):
        return hashlib.sha1(s.encode("utf-8")).hexdigest()

    def nz(v):
        return None if v in (None, "", []) else v

    VID = "-_aUs0oj1o0"
    D_PRE = ("第一段正文\n\n📌 關於片中與 0050 的比較\n片中比較的期間與 0050 不同。\n" + H_OLD
             + "\n\n📃 播放清單:https://example.invalid/pl\n#台股")
    D_NOW = D_PRE.replace(H_OLD, H_NEW)
    RO = {"publishedAt": "2026-08-01T00:00:00Z", "channelId": "UCxxxx", "channelTitle": "CH",
          "thumbnails": {"default": {"url": "x"}}, "liveBroadcastContent": "none",
          "localized": {"title": "t", "description": "d"}}
    # pre_rewrite 的其他欄位刻意與線上不同:M4(其他欄位用線上值)要有東西可以咬
    PRE_SN = dict(RO, title="寫入前的標題", description=D_PRE, tags=["台股", "0050"], categoryId="27",
                  defaultLanguage="zh-Hant", defaultAudioLanguage="zh-Hant")
    LIVE = dict(RO, title="寫入後改過的標題", description=D_NOW, tags=["台股", "0050", "新標籤"], categoryId="27",
                defaultLanguage="zh-Hant", defaultAudioLanguage="zh-TW")
    # 舊 .json 刻意做成「看起來可用」(含舊句 1 次、無新句)⇒ 擋住它的只剩路徑寫死那一行
    OLD_JSON = dict(RO, title="第一次插入前的舊標題", description="舊版正文\n" + H_OLD + "\n", tags=["舊"],
                    categoryId="27", defaultLanguage="zh-Hant", defaultAudioLanguage="en-US")
    DRY = ["--vid=" + VID]

    def APPLY(sha):
        return ["--apply", "--vid=" + VID, "--confirm-sha1=" + sha]

    class HttpErrorStub(Exception):
        pass

    class QuotaExhausted(Exception):        # 同名類別;受測模組靠類別名 / 訊息前綴分主詞,不 import quota_meter
        pass

    class Req:
        def __init__(self, fn):
            self.fn = fn

        def execute(self, num_retries=None):
            if num_retries != 0:
                raise AssertionError("execute 沒帶 num_retries=0:%r" % (num_retries,))
            return self.fn()

    class StubYT:
        def __init__(self, live, fail_list=None, fail_update=None):
            self.st = {VID: copy.deepcopy(live)}
            self.lists, self.attempts, self.wire = [], [], []
            self.fail_list, self.fail_update = fail_list, fail_update

        def videos(self):
            return StubVideos(self)

    class StubVideos:
        def __init__(self, p):
            self.p = p

        def list(self, part, id):
            def f():
                self.p.lists.append((part, id))
                if self.p.fail_list is not None:
                    raise self.p.fail_list
                return {"items": [{"id": v, "snippet": copy.deepcopy(self.p.st[v])}
                                  for v in id.split(",") if v in self.p.st]}
            return Req(f)

        def update(self, part, body):
            def f():
                self.p.attempts.append((part, copy.deepcopy(body)))
                if isinstance(self.p.fail_update, QuotaExhausted):   # 本機擋:送出前丟,沒上線
                    raise self.p.fail_update
                self.p.wire.append((part, copy.deepcopy(body)))
                if self.p.fail_update is not None:
                    raise self.p.fail_update
                old = self.p.st[body["id"]]
                new = {k: v for k, v in old.items() if k in H_RO}       # 整包覆蓋:可寫欄位只剩 body 帶的
                new.update(copy.deepcopy(body["snippet"]))
                self.p.st[body["id"]] = new
                return {"id": body["id"], "snippet": copy.deepcopy(new)}
            return Req(f)

    def call(m, yt, argv):
        lines = []
        code = m.main(argv, _service_factory=lambda out: (yt, None), out=lambda s="": lines.append(str(s)))
        return code, "\n".join(lines)

    def tail(o, n):
        return o[-n:].replace("\n", " ⏎ ")

    T_A = {"utc": "2026-09-12T11:30:01.000+00:00", "tpe": "2026-09-12 19:30:01.000"}
    T_B = {"utc": "2026-09-12T11:30:09.000+00:00", "tpe": "2026-09-12 19:30:09.000"}
    T_C = {"utc": "2026-09-12T12:10:00.000+00:00", "tpe": "2026-09-12 20:10:00.000"}
    OTHER = "zzzzzzzzzzz"

    def stamp_rows(new_len, ok=True):
        """寫入端 STAMP。行的形狀照 fix_period_disclaimer.py:893-894(sent)/:902-906(error)/:922-924(ok)。
        刻意的陷阱:同一支先有一輪 sent+error(new_len 不同)、另一支用同一個 sent_at(new_len 也不同)、
        ok 行沒有 new_len ⇒ 取錯行的實作都對不上。"""
        r = [{"vid": VID, "idx": 1, "phase": "sent", "sent_at": T_A, "privacy": "public",
              "old_len": len(D_PRE), "new_len": new_len + 7},
             {"vid": VID, "idx": 1, "phase": "error", "by": "未知", "sent_at": T_A, "recv_at": T_A, "error": "x"},
             {"vid": OTHER, "idx": 2, "phase": "sent", "sent_at": T_B, "privacy": "public",
              "old_len": 5, "new_len": new_len + 11},
             {"vid": VID, "idx": 1, "phase": "sent", "sent_at": T_B, "privacy": "public",
              "old_len": len(D_PRE), "new_len": new_len}]
        if ok:
            r.append({"vid": VID, "idx": 1, "phase": "ok", "sent_at": T_B, "recv_at": T_B,
                      "etag": "e1", "resp_id": VID})
        r.append({"vid": OTHER, "idx": 2, "phase": "ok", "sent_at": T_B, "recv_at": T_B,
                  "etag": "e2", "resp_id": OTHER})
        return "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in r)

    def rrows(m):
        p = m.RESTORE_STAMP
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []

    def setup(m, tmp, name, pre=None, old_json=None, stamp="default"):
        d = Path(tmp) / name
        bk = d / "desc_backup"
        bk.mkdir(parents=True)
        m.BACKUP_DIR, m.EVID_DIR = bk, d / "restore"
        m.STAMP, m.RESTORE_STAMP = d / "writer_stamp.jsonl", m.EVID_DIR / "restore_stamp.jsonl"
        if stamp == "default":
            stamp = stamp_rows(len(D_NOW))
        if stamp is not None:
            m.STAMP.write_text(stamp, encoding="utf-8")
        if pre is not None:
            (bk / (VID + ".pre_rewrite.json")).write_text(json.dumps(pre, ensure_ascii=False), encoding="utf-8")
        if old_json is not None:
            (bk / (VID + ".json")).write_text(json.dumps(old_json, ensure_ascii=False), encoding="utf-8")
        return m.EVID_DIR

    def evid(ed):
        return sorted(p.name for p in ed.iterdir()) if ed.exists() else []

    def wire_ok(yt, before, target):
        """獨立判準:上線 body 只能差 description,且 description 就是 pre_rewrite 原文。"""
        if len(yt.wire) != 1:
            return ["上線 %d 次 ≠ 1" % len(yt.wire)]
        bad = []
        part, b = yt.wire[0]
        if part != "snippet":
            bad.append("part=%r" % part)
        if sorted(b) != ["id", "snippet"] or b.get("id") != VID:
            bad.append("body 外層 %r" % sorted(b))
        sn = b.get("snippet") or {}
        if sn.get("description") != target:
            bad.append("上線 description ≠ pre_rewrite 原文")
        ks = {k for k in before if k not in H_RO} | set(sn)
        d = sorted(k for k in ks - {"description"} if nz(before.get(k)) != nz(sn.get(k)))
        if d:
            bad.append("上線 body 與送出前線上值差 %s" % d)
        ro = sorted(set(sn) & set(H_RO))
        if ro:
            bad.append("上線 body 帶了唯讀欄位 %s" % ro)
        return bad

    def S1(m, tmp):  # 正常還原:dry-run → 照印出的 sha1 apply
        f = []
        ed = setup(m, tmp, "s1", pre=PRE_SN)
        writer_before = m.STAMP.read_bytes()
        yt = StubYT(LIVE)
        code, o = call(m, yt, DRY)
        if code != 0:
            f.append("dry-run exit %d ≠ 0:%s" % (code, tail(o, 160)))
        if H_SHA(D_NOW) not in o:
            f.append("dry-run 沒印線上 description sha1")
        if yt.attempts or len(yt.lists) != 1:
            f.append("dry-run:list %d、update %d" % (len(yt.lists), len(yt.attempts)))
        if evid(ed):
            f.append("dry-run 落了檔 %s" % evid(ed))
        try:
            m._NoWrite(yt).videos().update(part="snippet", body={})
            f.append("_NoWrite 沒擋 update")
        except m.DryRunWriteAttempt:
            pass
        code, o = call(m, yt, APPLY(H_SHA(D_NOW)))
        if code != 0:
            f.append("apply exit %d ≠ 0:%s" % (code, tail(o, 200)))
        if len(yt.lists) != 3:
            f.append("videos.list 累計 %d ≠ 3(dry 1 + 重讀 1 + T0 1)" % len(yt.lists))
        f += wire_ok(yt, LIVE, D_PRE)
        if yt.st[VID].get("description") != D_PRE:
            f.append("stub 最後 description ≠ pre_rewrite")
        if m.STAMP.read_bytes() != writer_before:
            f.append("寫入端 STAMP 被動過(還原的時間戳混進去了)")
        rr = rrows(m)
        if ([r.get("phase") for r in rr] != ["sent", "ok"] or any(r.get("vid") != VID for r in rr)
                or rr[0].get("sent_at") != rr[1].get("sent_at") or rr[0].get("new_len") != len(D_PRE)):
            f.append("restore_stamp 行不對:%s" % [(r.get("phase"), r.get("new_len")) for r in rr])
        docs = {}
        for n in evid(ed):
            if n == "restore_stamp.jsonl":
                continue
            k = re.sub(r"^\d{8}T\d{6}[+-]\d{4}_" + re.escape(VID) + "_", "", n)
            docs[k] = json.loads((ed / n).read_text(encoding="utf-8"))
        if sorted(docs) != ["after_T0.json", "before.json", "body.json", "update_result.json"]:
            f.append("落檔 %s" % evid(ed))
        else:
            if docs["before.json"].get("snippet") != LIVE:
                f.append("before 檔 ≠ 送出前線上 snippet")
            if not yt.wire or docs["body.json"].get("body") != yt.wire[0][1]:
                f.append("body 檔 ≠ 上線 body")
            if "不算證據" not in json.dumps(docs["after_T0.json"], ensure_ascii=False):
                f.append("after_T0 檔沒標不算證據")
        if "T0" not in o or "不算證據" not in o:
            f.append("輸出沒標 T0 不算證據")
        return f

    def S2(m, tmp):  # 不需還原:線上已等於 pre_rewrite
        f = []
        setup(m, tmp, "s2", pre=PRE_SN)
        yt = StubYT(dict(LIVE, description=D_PRE))
        for argv in (DRY, APPLY(H_SHA(D_PRE))):
            code, o = call(m, yt, argv)
            if code != 0 or "不需還原" not in o:
                f.append("%s:exit %d、印不需還原=%s" % (argv[0], code, "不需還原" in o))
        if yt.attempts:
            f.append("不需還原卻送了 update %d 次" % len(yt.attempts))
        return f

    def S3(m, tmp):  # 來源缺(兩個檔都沒有)
        f = []
        setup(m, tmp, "s3")
        yt = StubYT(LIVE)
        for argv in (DRY, APPLY(H_SHA(D_NOW))):
            code, o = call(m, yt, argv)
            if code != 1 or "來源缺" not in o:
                f.append("%s:exit %d ≠ 1 或沒寫來源缺" % (argv[0], code))
        if yt.attempts:
            f.append("來源缺卻送了 update")
        return f

    def S4(m, tmp):  # 只有舊 <vid>.json
        f = []
        setup(m, tmp, "s4", old_json=OLD_JSON)
        yt = StubYT(LIVE)
        for argv in (DRY, APPLY(H_SHA(D_NOW))):
            code, o = call(m, yt, argv)
            if code != 1 or "來源缺" not in o:
                f.append("%s:exit %d ≠ 1 或沒寫來源缺" % (argv[0], code))
        if yt.attempts:
            f.append("拿舊 .json 送了 update(description %.20r)"
                     % yt.attempts[0][1].get("snippet", {}).get("description"))
        return f

    def S5(m, tmp):  # 線上被第三方改過
        f = []
        setup(m, tmp, "s5", pre=PRE_SN)
        live = dict(LIVE, description=D_NOW.replace(H_NEW, "(第三方整句改寫)"))
        yt = StubYT(live)
        for argv in (DRY, APPLY(H_SHA(live["description"]))):
            code, o = call(m, yt, argv)
            if code != 1:
                f.append("a) 新舊句都不在:%s exit %d ≠ 1" % (argv[0], code))
        if yt.attempts:
            f.append("a) 新舊句都不在卻送了 update")
        yt2 = StubYT(LIVE)
        call(m, yt2, DRY)
        # 改在舊句那一段裡:(a) 過得去,擋它的只剩 confirm-sha1
        yt2.st[VID]["description"] = D_NOW.replace(H_NEW, H_NEW + "(dry-run 之後第三方補)")
        code, o = call(m, yt2, APPLY(H_SHA(D_NOW)))
        if code != 1 or yt2.attempts:
            f.append("b) dry-run 後被改:exit %d、update %d" % (code, len(yt2.attempts)))
        return f

    def S6(m, tmp):  # confirm-sha1 不符 / 參數
        f = []
        setup(m, tmp, "s6", pre=PRE_SN)
        yt = StubYT(LIVE)
        code, o = call(m, yt, APPLY("0" * 40))
        if code != 1 or yt.attempts:
            f.append("sha1 不符:exit %d、update %d" % (code, len(yt.attempts)))
        n, na = len(yt.lists), len(yt.attempts)
        for argv in (["--apply", "--vid=" + VID], ["--apply", "--vid", VID, "--confirm-sha1=" + H_SHA(D_NOW)],
                     ["--apply", "--vid=" + VID, "--confirm-sha1=XYZ"],
                     ["--vid=" + VID, "--confirm-sha1=" + H_SHA(D_NOW)], ["--vid=../../x/abcd"],
                     ["--vid=" + VID, "--accept-needs-human"]):
            code, o = call(m, yt, argv)
            if code != 1:
                f.append("參數 %r exit %d ≠ 1" % (argv, code))
        if len(yt.lists) != n or len(yt.attempts) != na:
            f.append("參數錯仍打了 API:list +%d、update +%d" % (len(yt.lists) - n, len(yt.attempts) - na))
        return f

    def S7(m, tmp):  # body 多一欄差異
        f = []
        setup(m, tmp, "s7", pre=PRE_SN)
        yt = StubYT(dict(LIVE, someNewWritableField="線上有值"))   # 不認得的可寫欄位:整包覆蓋會被清掉
        code, o = call(m, yt, APPLY(H_SHA(D_NOW)))
        if code != 1 or yt.attempts:
            f.append("a) 線上多一個不認得的欄位:exit %d、update %d" % (code, len(yt.attempts)))
        orig = m.build_body

        def bad_build(vid, live_sn, target):
            b = orig(vid, live_sn, target)
            b["snippet"]["title"] = "被多改的標題"
            return b
        m.build_body = bad_build
        try:
            yt2 = StubYT(LIVE)
            code, o = call(m, yt2, APPLY(H_SHA(D_NOW)))
        finally:
            m.build_body = orig
        if code != 1 or yt2.attempts:
            f.append("b) body 多改 title:exit %d、update %d" % (code, len(yt2.attempts)))
        return f

    def S8(m, tmp):  # API 錯:停、不重試、分主詞
        f = []
        ed = setup(m, tmp, "s8a", pre=PRE_SN)
        yt = StubYT(LIVE, fail_update=HttpErrorStub('<HttpError 500 "backendError">'))
        code, o = call(m, yt, APPLY(H_SHA(D_NOW)))
        if code != 2 or len(yt.attempts) != 1 or "Google 回錯誤" not in o or "本機 quota_meter" in o:
            f.append("a) Google 錯:exit %d、嘗試 %d" % (code, len(yt.attempts)))
        if len(yt.lists) != 1:
            f.append("a) Google 錯之後還讀了 %d 次" % (len(yt.lists) - 1))
        if len([n for n in evid(ed) if n.endswith("update_result.json")]) != 1:
            f.append("a) 沒落 update_result:%s" % evid(ed))
        if [r.get("phase") for r in rrows(m)] != ["sent", "error"]:
            f.append("a) restore_stamp 應 sent,error:%s" % [r.get("phase") for r in rrows(m)])
        setup(m, tmp, "s8b", pre=PRE_SN)
        yt = StubYT(LIVE, fail_update=QuotaExhausted("quota exhausted:videos.update 需 50,今日剩 12"))
        code, o = call(m, yt, APPLY(H_SHA(D_NOW)))
        if code != 2 or "本機 quota_meter 擋下" not in o or yt.wire or len(yt.attempts) != 1:
            f.append("b) 本機擋:exit %d、上線 %d、嘗試 %d" % (code, len(yt.wire), len(yt.attempts)))
        if [r.get("phase") for r in rrows(m)] != ["sent", "blocked"]:
            f.append("b) restore_stamp 應 sent,blocked:%s" % [r.get("phase") for r in rrows(m)])
        setup(m, tmp, "s8c", pre=PRE_SN)
        yt = StubYT(LIVE, fail_list=HttpErrorStub("<HttpError 503>"))
        code, o = call(m, yt, APPLY(H_SHA(D_NOW)))
        if code != 2 or yt.attempts or len(yt.lists) != 1:
            f.append("c) list 錯:exit %d、list %d、update %d" % (code, len(yt.lists), len(yt.attempts)))
        if rrows(m):
            f.append("c) 沒送卻落了 restore_stamp")
        return f

    def S9(m, tmp):  # (a) 段外有差 ⇒ 拒寫、旗標蓋不過;段內寫壞 ⇒ 照寫(那正是需要還原的形狀)
        f = []
        cases = [("a) 段後(播放清單行)被改", D_NOW.replace("example.invalid/pl", "example.invalid/pl2")),
                 ("b) 字補在上一段結尾", D_NOW.replace("第一段正文", "第一段正文(別的 job 補的)")),
                 ("c) 結尾多一行", D_NOW + "\n#別的job"),
                 ("e) 字插在下一段開頭", D_NOW.replace("\n\n📃", "\n\n(別的 job 插的)📃"))]
        for i, (lab, live_d) in enumerate(cases):
            setup(m, tmp, "s9%d" % i, pre=PRE_SN, stamp=stamp_rows(len(live_d)))   # (b) 刻意成立
            yt = StubYT(dict(LIVE, description=live_d))
            for argv in (DRY, APPLY(H_SHA(live_d)), APPLY(H_SHA(live_d)) + ["--accept-needs-human"]):
                code, o = call(m, yt, argv)
                if code != 1 or "段外" not in o:
                    f.append("%s:%s exit %d(要 1 且訊息有「段外」)"
                             % (lab, " ".join(a for a in argv if not a.startswith("--c")), code))
            if yt.attempts:
                f.append("%s:送了 update" % lab)
        # 陽性:段內寫壞(新句重複兩次 + 段前多一個空行)⇒ 差異都在那一段 ⇒ 照寫
        bad_d = D_NOW.replace(H_NEW, H_NEW + H_NEW).replace("\n\n📌", "\n\n\n📌")
        setup(m, tmp, "s9p", pre=PRE_SN, stamp=stamp_rows(len(bad_d)))
        yt = StubYT(dict(LIVE, description=bad_d))
        code, o = call(m, yt, APPLY(H_SHA(bad_d)))
        if code != 0:
            f.append("d) 段內寫壞:apply exit %d ≠ 0:%s" % (code, tail(o, 160)))
        f += ["d) " + x for x in wire_ok(yt, dict(LIVE, description=bad_d), D_PRE)]
        return f

    def S10(m, tmp):  # (b) 不成立 ⇒ 需人判 exit 4;apply 要同時帶 --accept-needs-human
        f = []
        later = "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in (
            {"vid": VID, "idx": 1, "phase": "sent", "sent_at": T_C, "privacy": "public",
             "old_len": len(D_NOW), "new_len": len(D_NOW)},
            {"vid": VID, "idx": 1, "phase": "error", "by": "未知", "sent_at": T_C, "recv_at": T_C, "error": "x"}))
        cases = [("a) 長度 ≠ new_len", stamp_rows(len(D_NOW) + 3)),
                 ("b) 只有 sent/error 沒有 ok", stamp_rows(len(D_NOW), ok=False)),
                 ("c) STAMP 不存在", None),
                 ("d) STAMP 有解析不了的行", stamp_rows(len(D_NOW)) + "{壞掉的一行\n"),
                 ("e) 最後一筆 ok 之後又有 sent+error", stamp_rows(len(D_NOW)) + later)]
        for i, (lab, st) in enumerate(cases):
            setup(m, tmp, "s10%d" % i, pre=PRE_SN, stamp=st)
            yt = StubYT(LIVE)
            code, o = call(m, yt, DRY)
            if code != 4 or "--accept-needs-human" not in o:
                f.append("%s:dry-run exit %d ≠ 4 或印的指令沒帶 --accept-needs-human" % (lab, code))
            code, o = call(m, yt, APPLY(H_SHA(D_NOW)))
            if code != 4 or yt.attempts:
                f.append("%s:apply 沒帶旗標 exit %d、update %d" % (lab, code, len(yt.attempts)))
            if i == 0:
                code, o = call(m, yt, APPLY(H_SHA(D_NOW)) + ["--accept-needs-human"])
                if code != 0:
                    f.append("%s:兩個旗標都帶 apply exit %d ≠ 0:%s" % (lab, code, tail(o, 160)))
                f += [lab + ":" + x for x in wire_ok(yt, LIVE, D_PRE)]
        return f

    SCEN = [("S1 正常還原", S1), ("S2 不需還原", S2), ("S3 來源缺", S3), ("S4 只有舊.json", S4),
            ("S5 線上被第三方改過", S5), ("S6 confirm-sha1不符", S6), ("S7 body多一欄差異", S7), ("S8 API錯", S8),
            ("S9 (a)段外有差", S9), ("S10 (b)需人判", S10)]

    P_M2 = ("    if extra:\n", "    if False:\n")
    P_M4 = ("    body = build_body(vid, live_sn, target)\n", "    body = build_body(vid, src_sn, target)\n")
    MUT = [  # (代號, 說明, [(原字串, 突變字串)], 必須翻紅的情境)
        ("BASE", "未突變(同一條 exec 路徑)", [], None),
        ("NC", "陰性對照:改 dry-run 標籤字串", [('DRY_TAG = "DRY-RUN"', 'DRY_TAG = "DRY_RUN_NC"')], None),
        ("M1", "來源找不到就退回讀 <vid>.json",
         [("    p = source_path(vid)\n",
           "    p = source_path(vid)\n    if not p.is_file():\n        p = BACKUP_DIR / (vid + \".json\")\n")], "S4"),
        ("M2", "拿掉「description 以外有差異 ⇒ 拒寫」", [P_M2], "S7"),
        ("M3", "拿掉 confirm-sha1 比對", [("        if live_sha1 != confirm_sha1:\n", "        if False:\n")], "S6"),
        ("M4", "其他欄位改用備份裡的舊值", [P_M4], "S1"),
        ("M4b", "M4 + M2(證明判準獨立於受測模組的 body_problems)", [P_M4, P_M2], "S1"),
        ("M5a", "拿掉「已等於 pre_rewrite ⇒ 不需還原」", [("    if live_desc == target:\n", "    if False:\n")], "S2"),
        ("M5b", "拿掉「新舊句都不在 ⇒ 拒寫」",
         [("    if _SENT_NEW not in live_desc and _SENT_OLD not in live_desc:\n", "    if False:\n")], "S5"),
        ("M6", "new_len 改讀最後一筆 ok 行(ok 行沒有這欄)",
         [('    new_len = sents[0].get("new_len")\n', '    new_len = ok.get("new_len")\n')], "S1"),
        ("M7", "不檢查 --accept-needs-human", [("    if needs and not accept_human:\n", "    if False:\n")], "S10"),
        ("M8", "拿掉 (a) 段外有差 ⇒ 拒寫", [("    if outside:\n", "    if False:\n")], "S9"),
        ("M8b", "(a) 段外有差被 --accept-needs-human 蓋過",
         [("    if outside:\n", "    if outside and not accept_human:\n")], "S9"),
        ("M9", "還原時間戳寫進寫入端 STAMP",
         [('    with RESTORE_STAMP.open("a", encoding="utf-8") as fh:\n',
           '    with STAMP.open("a", encoding="utf-8") as fh:\n')], "S1"),
        ("M10", "(a) 換成被駁回的較嚴判準(線上 == pre_rewrite 換新句才寫)",
         [("    outside = outside_para_diff(live_desc, target)\n",
           "    outside = None if live_desc == target.replace(_SENT_OLD, _SENT_NEW) else \"較嚴判準不符\"\n")], "S9"),
    ]

    print("# %s --self-test  %s  離線;假 client;突變只作用在 SELF-TEST 標記以上" % (TOOL, now_tw().isoformat(timespec="seconds")))
    print("# 判準:上線 body 由本 harness 拿送出前的線上 snippet 逐欄比對(不用受測模組的 body_problems)\n")
    allpass = True
    if re.search(r"^\s*(import|from)\s+fix_period_disclaimer", prod, re.M):
        print("❌ 正式路徑 import 了 fix_period_disclaimer")
        allpass = False
    evid_before = sorted(p.name for p in EVID_DIR.iterdir()) if EVID_DIR.exists() else None

    def stamp_stat():
        return (STAMP.stat().st_size, STAMP.stat().st_mtime_ns) if STAMP.exists() else None
    stamp_before = stamp_stat()
    tmp_root = tempfile.mkdtemp(prefix="restore_st_")
    try:
        for code, desc, reps, must_red in MUT:
            s = prod
            for old, new in reps:
                c = s.count(old)
                if c != 1:
                    print("❌ %s 突變原字串出現 %d 次(應 1):%r" % (code, c, old))
                    allpass = False
                    break
                s = s.replace(old, new)
            m = types.ModuleType("restore_st_" + code)
            m.__dict__["__file__"] = os.path.abspath(__file__)
            exec(compile(s, "<%s:%s>" % (TOOL, code), "exec"), m.__dict__)
            m.BACKUP_DIR = m.EVID_DIR = Path(tmp_root) / "__未設定__"     # 情境忘了 setup 也碰不到真目錄
            m.STAMP = m.RESTORE_STAMP = Path(tmp_root) / "__未設定__" / "x.jsonl"
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
            print("%-4s %-46s %s  紅燈情境=%s" % (code, desc, verdict, red_keys or "無"))
            for k, v in sorted(reds.items()):
                print("       %s:%s" % (k, " | ".join(v)[:220]))
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
    leaked = [k for k in ("daily_publish", "quota_meter", "googleapiclient", "fix_period_disclaimer")
              if k in sys.modules]
    print("\n# 零網路:daily_publish / quota_meter / googleapiclient / fix_period_disclaimer 載入了嗎 → %s"
          % (leaked or "都沒有"))
    evid_after = sorted(p.name for p in EVID_DIR.iterdir()) if EVID_DIR.exists() else None
    print("# 真的落檔目錄 %s:前 %s / 後 %s" % (EVID_DIR.name, evid_before, evid_after))
    stamp_after = stamp_stat()
    print("# 真的寫入端 STAMP(size, mtime_ns):前 %s / 後 %s" % (stamp_before, stamp_after))
    allpass &= not leaked and evid_before == evid_after and stamp_before == stamp_after
    print("SELFTEST_RESULT:", "PASS" if allpass else "FAIL")
    return 0 if allpass else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    sys.exit(main())
