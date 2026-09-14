# -*- coding: utf-8 -*-
"""單支影片的 description 還原工具 —— 還原成 fix_period_disclaimer --rewrite-note 寫入前另存的
STUDIO/desc_backup/<vid>.pre_rewrite.json(fix_period_disclaimer.py:867-887)。只動 description。

預設 dry-run(1 次 videos.list = 1 unit,零 update)。真寫要同時帶 --apply 和
--confirm-sha1=<dry-run 印出的「當下線上 description」sha1>(1 + 50 + 1 = 52 units)。
輸出第一行印本檔 blob(git hash-object 同算法,算的是磁碟上本檔的位元組)。真 apply 前核三值一致:
這個值 == 最新 commit 的 blob == 驗證員報告裡的 blob(docs/ops/2026-09-12_84支寫入把關清單_wF-p3.md §0-3)。

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
  M5 不需還原   線上 description 已逐字等於 pre_rewrite ⇒ 印「不需還原」、exit 0、不寫。
                (原規格的「線上新句、舊句都找不到 ⇒ 拒寫」已由 wF:p5 刪除、由 (a) 取代:寫入端把那句寫壞時
                 新舊句正好都找不到,那條會擋掉最需要還原的情形。M11:把它加回來,S5 要翻紅。)
  —— 以下是 wF:p5 定案的兩條准寫判準(docs/ops/2026-09-12_84支寫入把關清單_wF-p3.md:65-77,commit 6b77c90f;
     突變編號照 wF:p5 09-12 規格修正),兩條都要成立:
  M6 (a) N0:只准舊句那一行有差  先在 pre_rewrite 裡定位舊句所在的那一行(84/84 支的舊句都自成一行),
                取 head = target[:行首]、tail = target[行尾:];線上必須 head 開頭逐位元組相等、
                tail 結尾逐位元組相等(🔴 不 strip、不正規化換行 —— N0d),而且中段不准出現 "\\n",
                也就是線上行數必須等於 pre_rewrite 的行數(N0b)。任一條不符 ⇒ 印出段外第一個差異位置
                前後各 40 字的 repr、exit 1;差異只是 \\r\\n 或結尾空白時另印一行
                `note: whitespace-only outside segment`,仍然 exit 1。
                🔴 任何旗標都蓋不過(M6b:被 --accept-needs-human 蓋過要翻紅)。
                寫入端的壞法(截半、重複、刪光)都發生在那一行裡 ⇒ 放行;吃掉句尾換行會讓行數不同
                ⇒ 拒寫(fail-closed,wF:p5 接受)。放寬回「以空白行分段」(N0c)或「舊句行 ±1 行」
                (N0e)都要翻紅。
                刻意**不是**「線上 == pre_rewrite 換上新句才寫」—— wF:p5 駁回:寫壞了才需要還原,
                那條只放寫對的、擋寫壞的,方向反了(M10:換成它,「段內寫壞」那個陽性情境要翻紅)。
                🔴 已知殘留(第六則,總督導接受):N0 分不出第三方在舊句那一行裡的等長改動
                (A13b/A13e)⇒ 所以 dry-run 和 apply 一律用 repr 印出那一行的兩個版本,靠人判前逐字看。
  M8/M9 (b) 長度對 STAMP  線上 description 長度 == 寫入端 STAMP 該支的 new_len。new_len 的取法:
                最後一筆 ok 行 → sent_at(整個 {utc,tpe} dict)完全相同的 sent 行 → 它的 new_len
                (🔴 ok 行沒有 new_len,fix_period_disclaimer.py:922-924;sent 行才有,:893-894 —— M8)。
                長度不等 / 沒有 ok 行(只有 sent、error)/ 對不到 sent 行 / 最後一筆 ok 之後還有 sent 或 error /
                STAMP 不存在或有解析不了的行 / new_len 不是整數 ⇒ 需人判(exit 4),讀不到欄位不當成「沒有條件」;
                dry-run 印完整 diff、線上長度、sent 行 new_len 與理由。apply 要**同時**帶 --accept-needs-human 與
                --confirm-sha1 才寫,只帶 --confirm-sha1 ⇒ 不寫、exit 4(M9)。
                這條較弱(STAMP 沒記 body hash;YouTube 可能正規化空白),所以是「需人判」不是拒寫。
  M7 還原時間戳  sent / ok / error / blocked / readback_mismatch 寫進 restore/restore_stamp.jsonl
                (格式同 STAMP 的 _stamp(),另加 tool 欄;本機 quota_meter 擋下時 phase=blocked,
                同 fix_period_disclaimer.py:903)。sent 在呼叫**之前**落盤,而且排在 before/body 證據檔
                **之前**(第三則 D:sent 行寫失敗就不留任何孤兒證據檔)。
                🔴 還原之後,擋住寫入端再寫一次的,是寫入端 STAMP 裡該支的 ok 行
                (fix_period_disclaimer.py:776-804)⇒ 那一行不准刪,也不准改。
                🔴 所以還原的行絕不寫進寫入端 STAMP:它的 _stamped()(fix_period_disclaimer.py:564-582)
                只看 vid 與 phase ∈ (sent, ok),還原的行混進去會被當成它自己寫過。
                🔴 建置員實讀 :735-815 的補記(照規格寫,但據實說):還原之後 desc == snap,
                `if desc != snap:` 那一支根本不會進去,而 _stamped() 只在那一支裡被問到 ⇒ 現行碼實際上
                會再跑一次 rewrite_desc()。上面那句照 wF:p5 規格原文寫,這一句是實讀結果,已回報。
                🔴 本工具**完全不讀** restore_stamp 來做任何決定(第七則補二)—— 只寫、不讀。
  R5 sent 之後一律 5  restore_stamp 的 sent 行落檔之後,任何例外都轉成 StateUnknown ⇒ exit 5、印 traceback
                加一行 STATE UNKNOWN(第五則)。sent 落檔之前的例外維持原行為(1 / 2 / 4)。
  R6 舊句那行印兩版  dry-run 與 apply 都用 repr 印出舊句那一行的 pre_rewrite 版與線上版,
                不論 (a)(b) 結果如何都印(第六則;只加輸出,不改判定)。
  R7 T0 回讀不符    不准 exit 0:改走 R5 的 5,印出兩邊 sha1,restore_stamp 只寫
                phase="readback_mismatch"、**不准寫 ok 行**(第七則 + 補一)。
  B  ok 之後的 phase 用白名單  只認得的 phase 才放行;blocked / 不認得的 phase ⇒ 需人判(第三則 B)。
                🔴 白名單不含 readback_mismatch:那是 restore_stamp 才有的 phase,出現在寫入端 STAMP
                代表還原工具寫錯檔(第七則補二)⇒ 直接拒寫。
  C  不是 dict 的列 ⇒ 壞行  能解析但不是 dict 的列也算壞行 ⇒ 需人判(第三則 C)。
  D  sent 行排最前  restore_stamp 的 sent 行寫在 before/body 證據檔之前(第三則 D)。
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

exit code:0 成功 / 不需還原 / dry-run 可還原 | 1 拒寫(含參數錯、來源缺、(a) N0 段外有差)
         | 2 API 錯誤(Google 回錯,或本機 quota_meter 在送出前擋下;訊息寫明是哪一個)
           ——🔴 第五則之後,2 只涵蓋 restore_stamp 的 sent 行**落檔之前**的失敗(建 service、
             第一次 videos.list)。sent 行落檔之後的一切失敗都是 5,不是 2。
         | 4 需人判((b) 不成立;dry-run 或沒帶 --accept-needs-human 的 apply,都不寫)
         | 5 寫入狀態未知,必須回讀(第五則;2 已被 API 錯誤用掉,所以另挑 5)。restore_stamp 的
             sent 行一旦落檔,之後任何例外 —— 本機 quota_meter 擋下 update、Google 回錯、回應形狀
             不對、寫 ok 行失敗、事後落檔失敗、T0 讀回失敗、T0 回讀與預期不符(第七則)—— 一律 5,
             印出 traceback 再加一行 STATE UNKNOWN。🔴 不准當成成功,也不准當成沒寫。
"""
import argparse, datetime, difflib, hashlib, io, json, os, re, sys, traceback
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
EXIT_UNKNOWN = 5                                          # 第五則:2 已被用掉 ⇒ 另挑沒用過的 5
UNKNOWN_LINE = "STATE UNKNOWN: update may have been applied to %s; read back before any retry"
WS_ONLY_NOTE = "note: whitespace-only outside segment"
# 第三則 B:寫入端 STAMP 最後一筆 ok 之後,只有這些 phase 算「認得且無害」。
# 🔴 白名單刻意不含 readback_mismatch(第七則補二):那是 restore_stamp 專屬,出現在寫入端 STAMP
#    代表還原工具寫錯了檔,本身就是 FAIL ⇒ 由 STAMP_ALIEN_PHASES 直接擋成拒寫,不是需人判。
#    白名單本身是空的:寫入端只會寫 sent / ok / blocked / error(fix_period_disclaimer.py:893/903/922),
#    最後一筆 ok 之後不管出現哪一種,都代表「線上可能是之後那次寫的」⇒ 一律需人判。
STAMP_PHASE_OK_AFTER = ()
STAMP_ALIEN_PHASES = ("readback_mismatch",)

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


class StateUnknown(Exception):
    """第五則:restore_stamp 的 sent 行已落檔,之後出錯 ⇒ 寫入狀態未知,必須回讀(exit 5)。
    刻意不是 Refuse / ApiError 的子類:絕不能被「拒寫」或「API 錯誤」吞掉當成沒寫。"""

    def __init__(self, vid, tb=None):
        Exception.__init__(self, UNKNOWN_LINE % vid)
        self.vid = vid
        self.tb = tb or (traceback.format_exc() if sys.exc_info()[0] is not None
                         else "".join(traceback.format_stack()))


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


# ---------------------------------------------------------------- 第四則 3.:自算本檔 blob(不寫死)
def self_blob():
    """本檔的 git blob。sha1(b"blob <len>\\0" + 位元組) —— 和 git hash-object 同一條算法,
    現算現印,🔴 不准寫死。回 (磁碟位元組的 blob, LF 正規化後的 blob 或 None)。
    這個 repo 是 core.autocrlf=true 且沒有 .gitattributes:磁碟上若是 CRLF,git 收進去的是 LF 版,
    兩者會不一樣 ⇒ 另算一份,只在不同時附註,免得「三值一致」對不起來卻沒人看見。"""
    def _h(b):
        return hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()
    raw = Path(os.path.abspath(__file__)).read_bytes()
    norm = raw.replace(b"\r\n", b"\n")
    return _h(raw), (_h(norm) if norm != raw else None)


def blob_line():
    raw, lf = self_blob()
    s = "# blob %s  (本檔自算,git hash-object 同算法;不是寫死的)" % raw
    if lf:
        s += "  🔴 磁碟上是 CRLF,git 存的是 LF 版 %s" % lf
    return s


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


# ---------------------------------------------------------------- M6 (a) N0:只准舊句那一行有差
def old_line_bounds(target):
    """pre_rewrite 裡舊句所在那一行的 [行首, 行尾)(行尾不含換行本身)。
    84/84 支的舊句都自成一行(09-11 快照實測 84/84 支含舊句恰 1 次的都是，見 self-test N5);load_source 已保證舊句恰 1 次。"""
    i = target.index(_SENT_OLD)
    ls = target.rfind("\n", 0, i) + 1
    le = target.find("\n", i + len(_SENT_OLD))
    return ls, (len(target) if le < 0 else le)


def _first_diff(a, b):
    n = min(len(a), len(b))
    for k in range(n):
        if a[k] != b[k]:
            return k
    return n


def n0_diff(live, target, _norm=lambda s: s):
    """N0(第三則):線上與 pre_rewrite 只准「舊句所在那一行」不同。回 None = 通過,否則回一句話。
    🔴 _norm 刻意是 identity —— 不 strip、不正規化換行(N0d 突變把它換成 s.strip())。
    🔴 這是 fail-closed:吃掉句尾換行會讓行數不同 ⇒ 拒寫,wF:p5 已接受。"""
    live, target = _norm(live), _norm(target)
    ls, le = old_line_bounds(target)
    head, tail = target[:ls], target[le:]
    if not live.startswith(head):                      # 段前逐位元組相等
        k = _first_diff(live, head)
        return ("段前第 %d 字起不同(前後各 40 字)\n      線上       %r\n      pre_rewrite %r"
                % (k, live[max(0, k - 40):k + 40], head[max(0, k - 40):k + 40]))
    if not live.endswith(tail):                        # 段後逐位元組相等
        rk = _first_diff(live[::-1], tail[::-1])
        a, b = len(live) - rk, len(tail) - rk
        return ("段後倒數第 %d 字起不同(前後各 40 字)\n      線上       %r\n      pre_rewrite %r"
                % (rk, live[max(0, a - 40):a + 40], tail[max(0, b - 40):b + 40]))
    if len(head) + len(tail) > len(live):
        return "線上比段外文字還短(段前 %d + 段後 %d > 線上 %d)⇒ 段外被刪過" % (len(head), len(tail), len(live))
    mid = live[len(head):len(live) - len(tail)]
    if "\n" in mid:                                    # 行數必須相同
        return ("線上行數與 pre_rewrite 不同:舊句那一行的位置多了 %d 個換行(前後各 40 字)\n"
                "      線上 %r" % (mid.count("\n"), mid[:80]))
    return None


def _wsz(s):
    """把 \\r\\n 收成 \\n、每一行的結尾空白去掉 —— 只給「差異是不是只有空白」這個附註用,不參與判定。"""
    return "\n".join(x.rstrip() for x in s.replace("\r\n", "\n").split("\n"))


def n0_ws_only(live, target):
    """段外的差異是不是只有 \\r\\n 或行尾空白。True ⇒ 另印 WS_ONLY_NOTE,仍然 exit 1。"""
    ls, le = old_line_bounds(target)
    L, h, t = _wsz(live), _wsz(target[:ls]), _wsz(target[le:])
    return L.startswith(h) and L.endswith(t) and len(h) + len(t) <= len(L)


def old_line_pair(live, target):
    """第六則:舊句那一行的兩個版本。線上那一行 = 線上扣掉 head / tail 之後的中段;
    段外對不上時退而求其次,用行號對齊,總之一定要印得出兩行。"""
    ls, le = old_line_bounds(target)
    pre_line = target[ls:le]
    head, tail = target[:ls], target[le:]
    if live.startswith(head) and live.endswith(tail) and len(head) + len(tail) <= len(live):
        return pre_line, live[len(head):len(live) - len(tail)]
    n = target[:ls].count("\n")
    lines = live.split("\n")
    return pre_line, (lines[n] if n < len(lines) else "(線上沒有第 %d 行)" % (n + 1))


# ---------------------------------------------------------------- M8/M9 (b) 長度對寫入端 STAMP(只讀)
def stamp_check(vid, live_len):
    """回 (需人判理由清單, new_len)。空清單 = (b) 成立。
    new_len 取法(wF:p5 定案):最後一筆 ok 行 → sent_at 完全相同的 sent 行 → 它的 new_len。
    🔴 ok 行沒有 new_len(fix_period_disclaimer.py:922-924),只有 sent 行有(:893-894)。"""
    if not STAMP.is_file():
        return ["寫入端 STAMP 不存在(%s)⇒ 沒有寫入紀錄可對" % STAMP], None
    rows, bad, alien = [], 0, []
    for ln in STAMP.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            row = json.loads(ln)
        except ValueError:
            bad += 1
            continue
        if not isinstance(row, dict):       # 第三則 C:能解析、但不是 dict 的列也算壞行
            bad += 1
            continue
        if row.get("phase") in STAMP_ALIEN_PHASES or row.get("tool") == TOOL:
            alien.append((row.get("vid"), row.get("phase")))
        if row.get("vid") == vid:
            rows.append(row)
    if alien:
        # 第七則補二:還原的 phase / 本工具的行出現在**寫入端** STAMP ⇒ 還原工具寫錯檔,這本身就是 FAIL。
        raise Refuse("🔴 寫入端 STAMP 被還原紀錄污染(%s)—— 還原紀錄只准進 %s,拒寫、要人判"
                     % (alien[:5], RESTORE_STAMP.name))
    reasons = []
    if bad:
        reasons.append("STAMP 有 %d 行解析不了或不是 dict(可能正是這支的紀錄;未讀到不是通過)" % bad)
    oks = [n for n, r in enumerate(rows) if r.get("phase") == "ok"]
    if not oks:
        reasons.append("STAMP 裡這支沒有 ok 行(這支的 phase 依序:%s;sent 行 new_len 依序:%s,僅供人判)"
                       "⇒ 回應遺失、寫入狀態未知"
                       % ([r.get("phase") for r in rows],
                          [r.get("new_len") for r in rows if r.get("phase") == "sent"]))
        return reasons, None
    ok = rows[oks[-1]]
    # 第三則 B:白名單。認得且無害的 phase 才放行;blocked / 不認得的 phase 一律需人判。
    later = [r.get("phase") for r in rows[oks[-1] + 1:] if r.get("phase") not in STAMP_PHASE_OK_AFTER]
    if later:
        reasons.append("最後一筆 ok 之後還有 %s(白名單 %s 之外一律需人判)⇒ 線上可能是之後那次寫的"
                       % (later, list(STAMP_PHASE_OK_AFTER)))
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


# ---------------------------------------------------------------- M7 還原時間戳(另開檔)
def rstamp(row):
    """一行一筆,逐行 flush + fsync。🔴 只寫 RESTORE_STAMP,絕不寫寫入端 STAMP(見 docstring M7)。"""
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


# 🔴 第五則之後刻意沒有 _post_write():送出之後的落檔失敗不准被吞掉回 False,要一路拋成
#    StateUnknown ⇒ exit 5。把它吞掉正是驗證員 FAIL 的那一種「看起來成功」。


def print_diff(out, live_desc, target):
    # 完整印出、不截斷(給人判用;description 上限 5000 字,量不大)
    for x in difflib.unified_diff(live_desc.split("\n"), target.split("\n"),
                                  fromfile="線上", tofile="還原目標", n=0, lineterm=""):
        out("    " + x)


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

    # M5
    if live_desc == target:
        out("✅ 不需還原:線上 description 已逐字等於 pre_rewrite。不寫。")
        return EXIT_OK
    # (原規格「新舊句都不在 ⇒ 拒寫」已由 wF:p5 刪除、由 (a) 取代 —— 見 docstring M5 / M11)
    # 第六則:不論 (a)(b) 結果如何,一律用 repr 印出舊句那一行的兩個版本(只加輸出,不改判定)
    pre_line, live_line = old_line_pair(live_desc, target)
    out("舊句那一行(第六則:兩個版本都印。N0 分不出這一行裡第三方的等長改動,靠人判前逐字看這兩行):")
    out("      pre_rewrite 版 %r" % (pre_line,))
    out("      線上版         %r" % (live_line,))
    # M6 (a) N0:只准舊句那一行有差;段外有差 ⇒ 直接拒寫,任何旗標都蓋不過
    ols, ole = old_line_bounds(target)
    outside = n0_diff(live_desc, target)
    if outside:
        out("      description 差異(線上 → pre_rewrite),給人判用:")
        print_diff(out, live_desc, target)
        if n0_ws_only(live_desc, target):
            out(WS_ONLY_NOTE)
        raise Refuse("🔴 (a) N0 段外有差 —— 別的 job 動過,拒寫、要人判(旗標蓋不過):" + outside)
    out("(a) N0 ✅ 差異只落在 pre_rewrite 舊句那一行(第 %d–%d 字):段前段後逐位元組相等、行數相同"
        % (ols, ole))
    # M3
    if apply:
        if live_sha1 != confirm_sha1:
            raise Refuse("🔴 線上 description sha1=%s ≠ --confirm-sha1=%s —— dry-run 之後線上被改過(或貼錯),"
                         "拒寫;重跑 dry-run 看過再說" % (live_sha1, confirm_sha1))
    # M8 / M9 (b)
    needs, new_len = stamp_check(vid, len(live_desc))
    out("(b) 寫入端 STAMP(只讀)=%s" % STAMP)
    if needs:
        out("(b) 🟠 需人判:線上長度 %d;照取法取到的 sent 行 new_len=%r;對不上的原因:"
            % (len(live_desc), new_len))
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
            # 第四則 2.:exit 4 可以印旗標名稱,但🔴不給完整的可貼上指令列(免得人直接複製就送出)
            out("%s:不送。🟠 需人判(exit 4)—— 人看過上面的差異與 (b) 理由、決定仍要還原,"
                "才自己把下面這幾個旗標湊成一行跑(刻意不給可貼上的整行):" % DRY_TAG)
            out("      --accept-needs-human")
            out("      --confirm-sha1=%s(這一刻線上 description 的 sha1,會過期)" % live_sha1)
            out("      --vid=%s" % vid)
            out("      還要加上真寫的那個旗標(見 docstring 用法),本行刻意不印。")
            return EXIT_HUMAN
        out("%s:不送。確認上面的差異後,要還原請逐字跑(sha1 是**這一刻**線上 description 的):" % DRY_TAG)
        out(cmd)
        return EXIT_OK
    if needs and not accept_human:
        raise NeedsHuman("🟠 需人判((b) 不成立),沒帶 --accept-needs-human —— 不寫(exit 4):" + " | ".join(needs))
    if accept_human and not needs:
        out("# 註:給了 --accept-needs-human,但本次 (b) 成立、不需人判")
    checks = {"a_n0_old_line": [ols, ole], "b_new_len": new_len, "b_needs_human": needs,
              "accept_needs_human": bool(accept_human)}
    return _apply(yt, vid, live_sn, body, target, src_path, src_file_sha1, out, counter, checks)


def _apply(yt, vid, live_sn, body, target, src_path, src_file_sha1, out, counter, checks):
    stamp = now_tw().strftime("%Y%m%dT%H%M%S%z")          # ISO 8601 基本格式
    base = "%s_%s_" % (stamp, vid)
    meta = {"tool": TOOL, "vid": vid, "taken_at": now_tw().isoformat(timespec="seconds"),
            "source": str(src_path), "source_file_sha1": src_file_sha1, "checks": checks}
    # 🔴 第三則 D:restore_stamp 的 sent 行排在最前面 —— 排在 before/body 證據檔之前。
    #    sent 行寫失敗 ⇒ 什麼都還沒送、也不留任何孤兒證據檔 ⇒ 維持 exit 1。
    sent_at = now_pair()
    try:
        rstamp({"tool": TOOL, "vid": vid, "idx": None, "phase": "sent", "sent_at": sent_at,
                "old_len": len(live_sn.get("description") or ""), "new_len": len(target),
                "accept_needs_human": bool(checks.get("accept_needs_human"))})
    except Exception as exc:  # noqa: BLE001
        raise Refuse("🔴 落不了 %s 的 sent 行(什麼都還沒送,也還沒落任何證據檔)—— 不寫:%s"
                     % (RESTORE_STAMP.name, str(exc)[:160]))
    out("restore_stamp sent 行已落檔(第三則 D:排在證據檔之前)")
    # 🔴 第五則:從這一行以下,sent 行已經在檔案裡了 ⇒ 任何例外都是「寫入狀態未知」= EXIT_UNKNOWN。
    try:
        return _after_sent(yt, vid, live_sn, body, target, out, counter, meta, base, sent_at)
    except StateUnknown:
        raise
    except BaseException:
        raise StateUnknown(vid)


def _after_sent(yt, vid, live_sn, body, target, out, counter, meta, base, sent_at):
    """🔴 sent 行落檔之後的一切。這裡漏出去的任何例外都會被包成 StateUnknown ⇒ exit 5。
    包含:落檔失敗、update 被本機擋下、Google 回錯、回應形狀不對、寫 ok 行失敗、T0 讀回失敗、
    以及第七則的「T0 回讀與預期不符」。刻意沒有任何 except ... : return 0 的路徑。"""
    write_new_json(EVID_DIR / (base + "before.json"),
                   dict(meta, phase="before", note="送出前重讀的線上 snippet", snippet=live_sn,
                        description_sha1=desc_sha1(live_sn.get("description"))))
    write_new_json(EVID_DIR / (base + "body.json"),
                   dict(meta, phase="body", note="videos.update 送出的內容", part="snippet", body=body,
                        description_sha1=desc_sha1(target)))
    out("落檔(sent 行之後、送出之前):%s  %sbefore.json / %sbody.json" % (EVID_DIR, base, base))
    try:
        resp = _execute(yt.videos().update(part="snippet", body=body), "videos.update", counter)
    except ApiError as exc:
        out(str(exc))
        rstamp({"tool": TOOL, "vid": vid, "idx": None, "phase": "blocked" if exc.local else "error",
                "by": "本機 quota_meter" if exc.local else "未知", "sent_at": sent_at,
                "recv_at": now_pair(), "error": str(exc)[:400]})
        write_new_json(EVID_DIR / (base + "update_result.json"),
                       dict(meta, phase="update_result", ok=False, error=str(exc)))
        # 🔴 第五則附帶讀法(wF:p3,總督導同意):sent 行已落檔,即使是本機擋下、這一筆沒離開本機,
        #    也一律算「狀態未知」。保守方向,已接受。
        raise StateUnknown(vid)
    write_new_json(EVID_DIR / (base + "update_result.json"),
                   dict(meta, phase="update_result", ok=True, response=resp))
    got = ((resp or {}).get("snippet") or {}).get("description") if isinstance(resp, dict) else None
    if not isinstance(resp, dict) or got != target:
        out("🔴 videos.update 的回應形狀不對、或回應的 description ≠ 還原目標(回應 sha1=%s、type=%s)"
            % (desc_sha1(got) if isinstance(got, str) else "無", type(resp).__name__))
        raise StateUnknown(vid)
    out("✅ videos.update 已送出;回應的 description == pre_rewrite 原文")
    after = read_live(yt, vid, counter, "videos.list(T0)")
    a_desc = after.get("description") or ""
    rb_at = now_pair()
    write_new_json(EVID_DIR / (base + "after_T0.json"),
                   dict(meta, phase="after_T0", note="T0,不算證據(可能是快取;證據要之後用獨立儀器回讀)",
                        snippet=after, description_sha1=desc_sha1(a_desc)))
    if a_desc != target:
        # 🔴 第七則 + 補一:回讀不符 ⇒ 不准 exit 0、不准寫 ok 行,改寫 readback_mismatch 一行。
        rstamp({"tool": TOOL, "vid": vid, "idx": None,
                "phase": "readback_mismatch",
                "sent_at": sent_at, "readback_at": rb_at, "iso": rb_at["utc"],
                "expected_description_sha1": desc_sha1(target),
                "readback_description_sha1": desc_sha1(a_desc),
                "note": "T0 回讀與預期不符 ⇒ 寫入狀態未知,任何人或程式都不准把這一筆當成還原成功"})
        out("🔴 T0 回讀與預期不符(T0 可能讀到快取,所以不代表寫壞,但絕不是成功):")
        out("      預期 description sha1=%s" % desc_sha1(target))
        out("      讀回 description sha1=%s" % desc_sha1(a_desc))
        raise StateUnknown(vid)  # 第七則:回讀不符不准 exit 0
    rstamp({"tool": TOOL, "vid": vid, "idx": None, "phase": "ok", "sent_at": sent_at,
            "recv_at": now_pair(), "readback_at": rb_at,
            "etag": (resp or {}).get("etag"), "resp_id": (resp or {}).get("id")})
    out("T0 讀回(T0,不算證據):description == pre_rewrite 原文  sha1=%s" % desc_sha1(a_desc))
    for k in _WRITABLE_SNIPPET:
        if k != "description" and _nz(after.get(k)) != _nz(live_sn.get(k)):
            out("  🔴 T0 %s 與送出前不同:%.40r → %.40r" % (k, live_sn.get(k), after.get(k)))
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
    out(blob_line())                                        # 第四則 3.:第一行一律是自算的 blob
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
    except StateUnknown as e:
        # 第五則:sent 行已落檔之後的一切失敗。印 traceback,再加那一行 STATE UNKNOWN。
        out(e.tb.rstrip())
        out(UNKNOWN_LINE % e.vid)
        code = EXIT_UNKNOWN
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
    # 仿真樣本:照 09-11 快照的形狀(舊句自成一行,前後都有正文行與分隔線),舊句在第 6 行(0 起算)
    D_PRE = ("📌 關於片中與 0050 的比較\n"
             "\n"
             "📚 全系列連播:https://example.invalid/pl-all\n"
             "\n"
             "片中提到「同期 0050」的報酬數字,取自「近十年」的共同資料起點。\n"
             "兩組數字各自都是真實回測結果,但放在一起講容易讓人以為是同期對比,特此更正。\n"
             + H_OLD + "\n"
             "\n"
             "━━━━━━━━━━━━\n"
             "▶ 接著看下一集:https://example.invalid/next\n"
             "🔔 訂閱不漏接:https://example.invalid/sub\n"
             "━━━━━━━━━━━━\n"
             "\n"
             "#台股 #個股體檢")
    D_NOW = D_PRE.replace(H_OLD, H_NEW)
    assert D_PRE.split("\n")[6] == H_OLD, "harness 樣本壞了:舊句不在第 6 行、或不自成一行"
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
        def __init__(self, live, fail_list=None, fail_update=None, bad_resp=None, readback=None):
            self.st = {VID: copy.deepcopy(live)}
            self.lists, self.attempts, self.wire = [], [], []
            self.fail_list, self.fail_update = fail_list, fail_update
            self.bad_resp = bad_resp            # 第五則情境:update 回傳非 dict(東西還是寫進去了)
            self.readback = readback            # 第七則情境:T0 讀回傳回不同內容(例如讀到快取)

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
                out = []
                for v in id.split(","):
                    if v not in self.p.st:
                        continue
                    sn = copy.deepcopy(self.p.st[v])
                    if self.p.readback is not None and self.p.wire:
                        sn["description"] = self.p.readback
                    out.append({"id": v, "snippet": sn})
                return {"items": out}
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
                if self.p.bad_resp is not None:
                    return self.p.bad_resp
                return {"id": body["id"], "snippet": copy.deepcopy(new)}
            return Req(f)

    def call(m, yt, argv):
        lines = []
        code = m.main(argv, _service_factory=lambda out: (yt, None), out=lambda s="": lines.append(str(s)))
        return code, "\n".join(lines)

    def tail(o, n):
        return o[-n:].replace("\n", " ⏎ ")

    def no_paste(o):
        """第四則 2.:輸出裡不准有任何一行同時帶 --apply 和 --accept-needs-human(= 可直接貼上的指令列)。"""
        return [ln for ln in o.split("\n") if "--apply" in ln and "--accept-needs-human" in ln]

    T_A = {"utc": "2026-09-12T11:30:01.000+00:00", "tpe": "2026-09-12 19:30:01.000"}
    T_B = {"utc": "2026-09-12T11:30:09.000+00:00", "tpe": "2026-09-12 19:30:09.000"}
    T_C = {"utc": "2026-09-12T12:10:00.000+00:00", "tpe": "2026-09-12 20:10:00.000"}
    OTHER = "zzzzzzzzzzz"

    def stamp_rows(new_len, ok=True, extra=()):
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
        r.extend(extra)
        return "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in r)

    def rrows(m):
        p = m.RESTORE_STAMP
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []

    def setup(m, tmp, name, pre=None, old_json=None, stamp="default", rstamp_path=None):
        d = Path(tmp) / name
        bk = d / "desc_backup"
        bk.mkdir(parents=True)
        m.BACKUP_DIR, m.EVID_DIR = bk, d / "restore"
        m.STAMP, m.RESTORE_STAMP = d / "writer_stamp.jsonl", m.EVID_DIR / "restore_stamp.jsonl"
        if rstamp_path is not None:
            m.RESTORE_STAMP = rstamp_path(d)
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

    def S5(m, tmp):  # 那一行被寫壞到新舊句都不在 ⇒ 照 N0 可還原;dry-run 後段內等長改動(A6c)⇒ confirm-sha1 擋
        f = []
        live_d = D_NOW.replace(H_NEW, "(寫壞的半句")
        setup(m, tmp, "s5", pre=PRE_SN, stamp=stamp_rows(len(live_d)))
        yt = StubYT(dict(LIVE, description=live_d))
        code, o = call(m, yt, DRY)
        if code != 0:
            f.append("a) 那一行新舊句都不在:dry-run exit %d ≠ 0:%s" % (code, tail(o, 160)))
        code, o = call(m, yt, APPLY(H_SHA(live_d)))
        if code != 0:
            f.append("a) 那一行新舊句都不在:apply exit %d ≠ 0:%s" % (code, tail(o, 160)))
        f += ["a) " + x for x in wire_ok(yt, dict(LIVE, description=live_d), D_PRE)]
        setup(m, tmp, "s5b", pre=PRE_SN)
        yt2 = StubYT(LIVE)
        call(m, yt2, DRY)
        # A6c:dry-run 之後第三方在舊句那一行裡做**等長**改動 ⇒ N0 過得去,擋它的只剩 confirm-sha1
        a6c = D_NOW.replace("我會補上更正。", "我會補上訂正。")
        if len(a6c) != len(D_NOW) or a6c == D_NOW:
            f.append("b) A6c 樣本不是等長改動")
        yt2.st[VID]["description"] = a6c
        code, o = call(m, yt2, APPLY(H_SHA(D_NOW)))
        if code != 1 or yt2.attempts:
            f.append("b) A6c(dry-run 後段內等長改動):exit %d、update %d" % (code, len(yt2.attempts)))
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

    def S8(m, tmp):  # API 錯:停、不重試、分主詞。🔴 第五則:sent 行已落檔 ⇒ 一律 exit 5,不是 2
        f = []
        ed = setup(m, tmp, "s8a", pre=PRE_SN)
        yt = StubYT(LIVE, fail_update=HttpErrorStub('<HttpError 500 "backendError">'))
        code, o = call(m, yt, APPLY(H_SHA(D_NOW)))
        if code != 5 or len(yt.attempts) != 1 or "Google 回錯誤" not in o or "本機 quota_meter" in o:
            f.append("a) Google 錯:exit %d ≠ 5、嘗試 %d" % (code, len(yt.attempts)))
        if "STATE UNKNOWN" not in o or "Traceback" not in o:
            f.append("a) 沒印 traceback 或 STATE UNKNOWN 那一行")
        if len(yt.lists) != 1:
            f.append("a) Google 錯之後還讀了 %d 次" % (len(yt.lists) - 1))
        if len([n for n in evid(ed) if n.endswith("update_result.json")]) != 1:
            f.append("a) 沒落 update_result:%s" % evid(ed))
        if [r.get("phase") for r in rrows(m)] != ["sent", "error"]:
            f.append("a) restore_stamp 應 sent,error:%s" % [r.get("phase") for r in rrows(m)])
        setup(m, tmp, "s8b", pre=PRE_SN)
        yt = StubYT(LIVE, fail_update=QuotaExhausted("quota exhausted:videos.update 需 50,今日剩 12"))
        code, o = call(m, yt, APPLY(H_SHA(D_NOW)))
        # 🔴 第五則附帶讀法:sent 行已落檔,本機擋下也算「狀態未知」(保守,總督導已接受)
        if code != 5 or "本機 quota_meter 擋下" not in o or yt.wire or len(yt.attempts) != 1:
            f.append("b) 本機擋:exit %d ≠ 5、上線 %d、嘗試 %d" % (code, len(yt.wire), len(yt.attempts)))
        if [r.get("phase") for r in rrows(m)] != ["sent", "blocked"]:
            f.append("b) restore_stamp 應 sent,blocked:%s" % [r.get("phase") for r in rrows(m)])
        ed = setup(m, tmp, "s8c", pre=PRE_SN)
        yt = StubYT(LIVE, fail_list=HttpErrorStub("<HttpError 503>"))
        code, o = call(m, yt, APPLY(H_SHA(D_NOW)))
        # sent 行落檔**之前**的例外 ⇒ 維持原本的 exit 2(第五則明文)
        if code != 2 or yt.attempts or len(yt.lists) != 1:
            f.append("c) list 錯(sent 之前):exit %d ≠ 2、list %d、update %d"
                     % (code, len(yt.lists), len(yt.attempts)))
        if rrows(m) or evid(ed):
            f.append("c) 沒送卻落了 restore_stamp / 證據檔:%s" % evid(ed))
        return f

    def S9(m, tmp):  # (a) N0 段外有差 ⇒ 拒寫、旗標蓋不過;那一行裡寫壞 ⇒ 照寫(那正是需要還原的形狀)
        f = []
        cases = [("a) 描述最上面加一行", "【置頂】看這裡\n" + D_NOW),
                 ("b) 段後插一段", D_NOW.replace("\n\n━━━━━━━━━━━━\n▶", "\n\n(別的 job 插的一段)\n\n━━━━━━━━━━━━\n▶")),
                 ("c) 新句後同段加一行", D_NOW.replace(H_NEW, H_NEW + "\n(同段補的一行)")),
                 ("d) 改標題行(第一行)", D_NOW.replace("📌 關於片中與 0050 的比較", "📌 關於片中與 0056 的比較"))]
        for i, (lab, live_d) in enumerate(cases):
            setup(m, tmp, "s9%d" % i, pre=PRE_SN, stamp=stamp_rows(len(live_d)))   # (b) 刻意成立
            yt = StubYT(dict(LIVE, description=live_d))
            for argv in (DRY, APPLY(H_SHA(live_d)), APPLY(H_SHA(live_d)) + ["--accept-needs-human"]):
                code, o = call(m, yt, argv)
                if code != 1 or "段外" not in o or "@@" not in o:
                    f.append("%s:%s exit %d(要 1、訊息有「段外」、且印出差異)"
                             % (lab, " ".join(a for a in argv if not a.startswith("--c")), code))
                if no_paste(o):
                    f.append("%s:exit 1 卻印了可貼上的 --accept-needs-human 指令:%r" % (lab, no_paste(o)[:1]))
            if yt.attempts:
                f.append("%s:送了 update" % lab)
        # 陽性:舊句那一行裡寫壞(新句重複兩次)⇒ 差異都在那一行 ⇒ 照寫
        bad_d = D_NOW.replace(H_NEW, H_NEW + H_NEW)
        setup(m, tmp, "s9p", pre=PRE_SN, stamp=stamp_rows(len(bad_d)))
        yt = StubYT(dict(LIVE, description=bad_d))
        code, o = call(m, yt, APPLY(H_SHA(bad_d)))
        if code != 0:
            f.append("e) 那一行裡寫壞:apply exit %d ≠ 0:%s" % (code, tail(o, 160)))
        f += ["e) " + x for x in wire_ok(yt, dict(LIVE, description=bad_d), D_PRE)]
        return f

    def S10(m, tmp):  # (b) 不成立 ⇒ 需人判 exit 4;apply 要同時帶 --accept-needs-human
        f = []
        later = [{"vid": VID, "idx": 1, "phase": "sent", "sent_at": T_C, "privacy": "public",
                  "old_len": len(D_NOW), "new_len": len(D_NOW)},
                 {"vid": VID, "idx": 1, "phase": "error", "by": "未知", "sent_at": T_C, "recv_at": T_C,
                  "error": "x"}]
        cases = [("a) 長度 ≠ new_len", stamp_rows(len(D_NOW) + 3)),
                 ("b) 只有 sent/error 沒有 ok", stamp_rows(len(D_NOW), ok=False)),
                 ("c) STAMP 不存在", None),
                 ("d) STAMP 有解析不了的行", stamp_rows(len(D_NOW)) + "{壞掉的一行\n"),
                 ("e) 最後一筆 ok 之後又有 sent+error", stamp_rows(len(D_NOW), extra=later))]
        for i, (lab, st) in enumerate(cases):
            setup(m, tmp, "s10%d" % i, pre=PRE_SN, stamp=st)
            yt = StubYT(LIVE)
            code, o = call(m, yt, DRY)
            if (code != 4 or "--accept-needs-human" not in o or "@@" not in o
                    or "線上長度 %d" % len(D_NOW) not in o or "new_len=" not in o):
                f.append("%s:dry-run exit %d ≠ 4,或沒印旗標名稱 / 差異 / 線上長度 / new_len" % (lab, code))
            # 第四則 2.:exit 4 可以印旗標名稱,但不准給可直接貼上的整行
            if no_paste(o):
                f.append("%s:exit 4 印了可貼上的整行指令:%r" % (lab, no_paste(o)[:1]))
            code, o = call(m, yt, APPLY(H_SHA(D_NOW)))
            if code != 4 or yt.attempts:
                f.append("%s:apply 沒帶旗標 exit %d、update %d" % (lab, code, len(yt.attempts)))
            if i == 0:
                code, o = call(m, yt, APPLY(H_SHA(D_NOW)) + ["--accept-needs-human"])
                if code != 0:
                    f.append("%s:兩個旗標都帶 apply exit %d ≠ 0:%s" % (lab, code, tail(o, 160)))
                f += [lab + ":" + x for x in wire_ok(yt, LIVE, D_PRE)]
        return f

    # ---- 09-11 快照(未納管目錄;不存在就 fail-closed 報路徑,不准靜默跳過)----
    SNAP_DIR = Path(os.path.abspath(__file__)).resolve().parent.parent / "STUDIO" / "desc_snapshot_20260911"

    def _load_snap():
        if not SNAP_DIR.is_dir():
            return {"err": "🔴 09-11 快照目錄不存在:%s ⇒ 這條情境 fail-closed(不准當成通過)" % SNAP_DIR}
        rows, skipped = [], 0
        for p in sorted(SNAP_DIR.glob("*.json")):
            try:
                o = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                return {"err": "🔴 快照 %s 解析不了" % p.name}
            sn = o.get("snippet") if isinstance(o, dict) else None
            if not isinstance(sn, dict):
                skipped += 1
                continue
            d = sn.get("description") or ""
            if d.count(H_OLD) == 1:
                rows.append((p.name, d))
        if not rows:
            return {"err": "🔴 快照目錄裡沒有任何一支含舊句恰 1 次:%s" % SNAP_DIR}
        return {"rows": rows, "skipped": skipped, "err": None}
    SNAP = _load_snap()

    def ADV(m, tmp):  # 第四則 1.:驗證員的對抗樣本 A1/A2/A3/A4/A12/A13f/A15b + 已接受殘留 A13b/A13e
        f = []
        a4 = "📎" + D_NOW.replace("🔔 訂閱不漏接", "🔔 訂閱不漏")            # 段外加字,再把長度補回來
        a15b = D_NOW.replace("#台股 #個股體檢", "#台股 #個股體檢\n#補").replace("▶ 接著看下一集", "▶ 接著看")
        refuse = [
            ("A1 第一行前插一行", "【置頂】看這裡\n" + D_NOW),
            ("A2 段後插一段", D_NOW.replace("\n\n━━━━━━━━━━━━\n▶", "\n\n(插進來的一段)\n\n━━━━━━━━━━━━\n▶")),
            ("A3 新句後同段加一行", D_NOW.replace(H_NEW, H_NEW + "\n(同段補的一行)")),
            ("A12 導流段插在第一行後",
             D_NOW.replace("📌 關於片中與 0050 的比較\n",
                           "📌 關於片中與 0050 的比較\n\n👉 加入頻道會員:https://example.invalid/join\n")),
            ("A4 段外加字+補回長度", a4),
            ("A15b 段外加行+補回長度", a15b),
            ("A13f 標題行等長改動", D_NOW.replace("📌 關於片中與 0050 的比較", "📌 關於片中與 0056 的比較")),
        ]
        for i, (lab, live_d) in enumerate(refuse):
            if lab.split()[0] in ("A4", "A15b", "A13f") and len(live_d) != len(D_NOW):
                f.append("%s:樣本長度沒補回來(%d vs %d)" % (lab, len(live_d), len(D_NOW)))
            if lab.startswith("A13f") and live_d.count("\n") != D_NOW.count("\n"):
                f.append("%s:樣本行數變了" % lab)
            setup(m, tmp, "adv%d" % i, pre=PRE_SN, stamp=stamp_rows(len(live_d)))     # (b) 刻意成立
            yt = StubYT(dict(LIVE, description=live_d))
            for argv in (DRY, APPLY(H_SHA(live_d)), APPLY(H_SHA(live_d)) + ["--accept-needs-human"]):
                code, o = call(m, yt, argv)
                if code != 1:
                    f.append("%s:%s exit %d ≠ 1" % (lab, argv[0], code))
                if no_paste(o):
                    f.append("%s:exit 1 卻印了可貼上的指令列:%r" % (lab, no_paste(o)[:1]))
            if yt.attempts:
                f.append("%s:送了 update %d 次" % (lab, len(yt.attempts)))
        # A13b / A13e:第三方在**舊句那一行裡**的等長改動 —— N0 分不出來,wF:p3 已接受這個殘留。
        # 照實記:exit 0(會寫)。補救靠第六則 —— 那一行的兩個版本一定印出來給人逐字看。
        for i, (lab, live_d) in enumerate([
                ("A13b 那一行內等長改動", D_NOW.replace("我會補上更正。", "我會補上訂正。")),
                ("A13e 那一行內等長改動(另一處)", D_NOW.replace("仍可能有漏的", "仍可能有錯的"))]):
            if len(live_d) != len(D_NOW) or live_d == D_NOW:
                f.append("%s:樣本不是等長改動" % lab)
            setup(m, tmp, "adv13%d" % i, pre=PRE_SN, stamp=stamp_rows(len(live_d)))
            yt = StubYT(dict(LIVE, description=live_d))
            code, o = call(m, yt, DRY)
            if code != 0:
                f.append("%s(已接受殘留,預期 exit 0):exit %d" % (lab, code))
            if repr(live_d.split("\n")[6]) not in o or repr(H_OLD) not in o:
                f.append("%s:第六則的兩個版本沒印出來" % lab)
        return f

    def N1(m, tmp):  # 換行被吃掉:(a) 句尾那個 ⇒ 段後對不上;(b) 連同行首那個 ⇒ 段前段後都對得上但長度不夠
        f = []
        a = D_NOW.replace(H_NEW + "\n\n━", H_NEW + "\n━")
        b = D_NOW.replace("\n" + H_NEW, "", 1)
        if a.count("\n") != D_NOW.count("\n") - 1 or b.count("\n") != D_NOW.count("\n") - 1:
            return ["樣本不對:沒各吃掉剛好一個換行"]
        for i, (lab, live_d) in enumerate([("a) 吃掉句尾換行", a), ("b) 吃掉行首換行+整行", b)]):
            setup(m, tmp, "n1%d" % i, pre=PRE_SN, stamp=stamp_rows(len(live_d)))
            yt = StubYT(dict(LIVE, description=live_d))
            for argv in (DRY, APPLY(H_SHA(live_d)) + ["--accept-needs-human"]):
                code, o = call(m, yt, argv)
                if code != 1:
                    f.append("%s:%s exit %d ≠ 1(行數不同要 fail-closed)" % (lab, argv[0], code))
            if yt.attempts:
                f.append("%s:送了 update" % lab)
        return f

    def N2(m, tmp):  # 改了舊句的前一行 ⇒ 拒寫(釘住「放寬成 ±1 行」)
        f = []
        live_d = D_NOW.replace("兩組數字各自都是真實回測結果", "兩組數字各自都是真實回測結果(第三方補的)")
        setup(m, tmp, "n2", pre=PRE_SN, stamp=stamp_rows(len(live_d)))
        yt = StubYT(dict(LIVE, description=live_d))
        for argv in (DRY, APPLY(H_SHA(live_d)) + ["--accept-needs-human"]):
            code, o = call(m, yt, argv)
            if code != 1:
                f.append("%s exit %d ≠ 1(改了舊句前一行也要拒寫)" % (argv[0], code))
        if yt.attempts:
            f.append("送了 update")
        return f

    def N3(m, tmp):  # 段外只差空白 ⇒ 仍拒寫,另印 note(釘住「比對前先 strip / 正規化換行」)
        f = []
        for i, (lab, live_d) in enumerate([("結尾多空白", D_NOW + "  "),
                                           ("整份換成 CRLF", D_NOW.replace("\n", "\r\n"))]):
            setup(m, tmp, "n3%d" % i, pre=PRE_SN, stamp=stamp_rows(len(live_d)))
            yt = StubYT(dict(LIVE, description=live_d))
            code, o = call(m, yt, DRY)
            if code != 1:
                f.append("%s:exit %d ≠ 1" % (lab, code))
            if m.WS_ONLY_NOTE not in o:
                f.append("%s:沒印 %r" % (lab, m.WS_ONLY_NOTE))
            if yt.attempts:
                f.append("%s:送了 update" % lab)
        # 陰性對照:段外多的是**真的字**(不是空白)⇒ 拒寫,但不准印 whitespace-only 那一行
        setup(m, tmp, "n3n", pre=PRE_SN, stamp=stamp_rows(len(D_NOW) + 2))
        yt = StubYT(dict(LIVE, description=D_NOW + "#x"))
        code, o = call(m, yt, DRY)
        if code != 1 or m.WS_ONLY_NOTE in o:
            f.append("陰性對照:exit %d、印了 whitespace-only=%s" % (code, m.WS_ONLY_NOTE in o))
        return f

    def N4(m, tmp):  # 寫入端三種壞法(截半 / 重複 / 刪光)都在那一行裡 ⇒ 放行
        f = []
        for i, (lab, line) in enumerate([("截半", H_NEW[:14]), ("重複", H_NEW + H_NEW), ("刪光", "")]):
            live_d = D_NOW.replace(H_NEW, line)
            setup(m, tmp, "n4%d" % i, pre=PRE_SN, stamp=stamp_rows(len(live_d)))
            yt = StubYT(dict(LIVE, description=live_d))
            code, o = call(m, yt, APPLY(H_SHA(live_d)))
            if code != 0:
                f.append("%s:apply exit %d ≠ 0:%s" % (lab, code, tail(o, 140)))
            f += ["%s:%s" % (lab, x) for x in wire_ok(yt, dict(LIVE, description=live_d), D_PRE)]
        return f

    def N5(m, tmp):  # 09-11 真快照:正確改寫過的那一行 ⇒ N0 全數放行(N0 的陰性對照)
        f = []
        if SNAP.get("err"):
            return [SNAP["err"]]
        ok = 0
        for name, desc in SNAP["rows"]:
            ls, le = m.old_line_bounds(desc)
            if desc[ls:le] != H_OLD:
                f.append("%s:舊句不自成一行 %r" % (name, desc[ls:le][:30]))
                continue
            if m.n0_diff(desc.replace(H_OLD, H_NEW), desc) is None:
                ok += 1
            else:
                f.append("%s:正確改寫卻被 N0 擋" % name)
        if ok != len(SNAP["rows"]):
            f.append("放行 %d / 合格 %d" % (ok, len(SNAP["rows"])))
        return f

    def R5a(m, tmp):  # 第五則:update 回應的形狀不對 ⇒ 專屬 code、不准寫 ok 行
        f = []
        setup(m, tmp, "r5a", pre=PRE_SN)
        yt = StubYT(LIVE, bad_resp=[])
        code, o = call(m, yt, APPLY(H_SHA(D_NOW)))
        if code != 5:
            f.append("exit %d ≠ 5:%s" % (code, tail(o, 200)))
        if "STATE UNKNOWN" not in o or VID not in o.split("STATE UNKNOWN")[-1]:
            f.append("沒印 STATE UNKNOWN: ... %s" % VID)
        ph = [r.get("phase") for r in rrows(m)]
        if ph != ["sent"]:
            f.append("restore_stamp 應只有 sent(不准有 ok):%s" % ph)
        return f

    def R5b(m, tmp):  # 第五則:sent 行之後任何落檔失敗都算狀態未知(這裡拿寫 ok 行當代表)
        f = []
        setup(m, tmp, "r5b", pre=PRE_SN)
        orig = m.rstamp

        def boom(row):
            if row.get("phase") == "ok":
                raise IOError("模擬:寫 ok 行時丟例外")
            return orig(row)
        m.rstamp = boom
        try:
            yt = StubYT(LIVE)
            code, o = call(m, yt, APPLY(H_SHA(D_NOW)))
        finally:
            m.rstamp = orig
        if code != 5:
            f.append("exit %d ≠ 5:%s" % (code, tail(o, 200)))
        if "STATE UNKNOWN" not in o or "Traceback" not in o:
            f.append("沒印 traceback 或 STATE UNKNOWN")
        if len(yt.wire) != 1:
            f.append("這條情境本來就已經送出去了:上線 %d 次" % len(yt.wire))
        ph = [r.get("phase") for r in rrows(m)]
        if ph != ["sent"]:
            f.append("restore_stamp 應只有 sent:%s" % ph)
        return f

    def R6(m, tmp):  # 第六則:舊句那一行的兩個版本一律印出來(判定成不成立都要印)
        f = []
        pre_r, live_r = repr(H_OLD), repr(H_NEW)
        setup(m, tmp, "r6a", pre=PRE_SN)
        yt = StubYT(LIVE)
        for argv in (DRY, APPLY(H_SHA(D_NOW))):
            code, o = call(m, yt, argv)
            if pre_r not in o or live_r not in o:
                f.append("%s:沒印兩個版本(pre=%s live=%s)" % (argv[0], pre_r in o, live_r in o))
        for i, (lab, desc, st, want) in enumerate([
                ("(a) 段後有差", D_NOW + "#x", stamp_rows(len(D_NOW) + 2), 1),
                ("(b) STAMP 不存在", D_NOW, None, 4)]):
            setup(m, tmp, "r6%d" % i, pre=PRE_SN, stamp=st)
            yt = StubYT(dict(LIVE, description=desc))
            code, o = call(m, yt, DRY)
            if code != want or pre_r not in o or live_r not in o:
                f.append("%s:exit %d ≠ %d、pre=%s live=%s" % (lab, code, want, pre_r in o, live_r in o))
        # 段前有差 ⇒ 線上那一行對不齊,也一定要印得出兩行(至少 pre_rewrite 版逐字印出來)
        top = "【置頂】\n" + D_NOW
        setup(m, tmp, "r6t", pre=PRE_SN, stamp=stamp_rows(len(top)))
        yt = StubYT(dict(LIVE, description=top))
        code, o = call(m, yt, DRY)
        if code != 1 or pre_r not in o or "線上版" not in o:
            f.append("段前有差:exit %d、pre=%s、有印線上版=%s" % (code, pre_r in o, "線上版" in o))
        return f

    def R7(m, tmp):  # 第七則:T0 回讀不符 ⇒ 專屬 code、不准寫 ok 行、要有 readback_mismatch
        f = []
        setup(m, tmp, "r7", pre=PRE_SN)
        cached = D_NOW                                    # stub:T0 讀回舊內容(像讀到快取)
        yt = StubYT(LIVE, readback=cached)
        code, o = call(m, yt, APPLY(H_SHA(D_NOW)))
        if code != 5:
            f.append("exit %d ≠ 5:%s" % (code, tail(o, 200)))
        if "STATE UNKNOWN" not in o:
            f.append("沒印 STATE UNKNOWN")
        if H_SHA(D_PRE) not in o or H_SHA(cached) not in o:
            f.append("沒印出「預期 / 讀回」兩邊的 sha1")
        rr = rrows(m)
        ph = [r.get("phase") for r in rr]
        if ph != ["sent", "readback_mismatch"]:
            f.append("restore_stamp 應 sent,readback_mismatch:%s" % ph)
        mm = [r for r in rr if r.get("phase") == "readback_mismatch"]
        if mm and (mm[0].get("expected_description_sha1") != H_SHA(D_PRE)
                   or mm[0].get("readback_description_sha1") != H_SHA(cached)
                   or not mm[0].get("iso")):
            f.append("readback_mismatch 行少了 sha1 或 ISO 時間:%s" % mm[0])
        return f

    def BCD(m, tmp):  # 第三則 B / C / D + rstamp 防呆 + 第七則補二(寫入端 STAMP 被還原紀錄污染)
        f = []
        # B:最後一筆 ok 之後出現 blocked / 不認得的 phase ⇒ 白名單擋下 ⇒ 需人判
        blk = [{"vid": VID, "idx": 1, "phase": "blocked", "by": "本機 quota_meter", "sent_at": T_C,
                "recv_at": T_C, "error": "quota exhausted:x"}]
        wat = [{"vid": VID, "idx": 1, "phase": "某個沒人認得的新 phase", "sent_at": T_C}]
        for i, (lab, extra) in enumerate([("B blocked", blk), ("B 不認得的 phase", wat)]):
            setup(m, tmp, "bcd_b%d" % i, pre=PRE_SN, stamp=stamp_rows(len(D_NOW), extra=extra))
            yt = StubYT(LIVE)
            code, o = call(m, yt, DRY)
            if code != 4 or "白名單" not in o:
                f.append("%s:exit %d ≠ 4(或沒說是白名單擋下的)" % (lab, code))
        # C:能解析、但不是 dict 的列 ⇒ 算壞行 ⇒ 需人判
        setup(m, tmp, "bcd_c", pre=PRE_SN, stamp=stamp_rows(len(D_NOW)) + "123\n")
        yt = StubYT(LIVE)
        code, o = call(m, yt, DRY)
        if code != 4 or "不是 dict" not in o:
            f.append("C 非 dict 的列:exit %d ≠ 4(或沒算成壞行)" % code)

        # D:restore_stamp 的 sent 行寫不進去 ⇒ 不留任何孤兒證據檔、維持 exit 1、什麼都沒送
        def blocked_path(d):
            b = d / "blocker"
            b.write_text("x", encoding="utf-8")
            return b / "restore_stamp.jsonl"
        ed = setup(m, tmp, "bcd_d", pre=PRE_SN, rstamp_path=blocked_path)
        yt = StubYT(LIVE)
        code, o = call(m, yt, APPLY(H_SHA(D_NOW)))
        if code != 1 or yt.attempts:
            f.append("D sent 行寫不了:exit %d ≠ 1、update %d" % (code, len(yt.attempts)))
        if evid(ed):
            f.append("D 留下了孤兒證據檔:%s" % evid(ed))
        # 防呆:RESTORE_STAMP 指到寫入端 STAMP ⇒ 拒寫,且寫入端 STAMP 一個位元組都不准變
        setup(m, tmp, "bcd_g", pre=PRE_SN, rstamp_path=lambda d: d / "writer_stamp.jsonl")
        before = m.STAMP.read_bytes()
        yt = StubYT(LIVE)
        code, o = call(m, yt, APPLY(H_SHA(D_NOW)))
        if code != 1 or yt.attempts or m.STAMP.read_bytes() != before:
            f.append("防呆 RESTORE_STAMP==STAMP:exit %d ≠ 1、update %d、STAMP 變了=%s"
                     % (code, len(yt.attempts), m.STAMP.read_bytes() != before))
        # 第七則補二:還原專屬 phase / 本工具的行出現在**寫入端** STAMP ⇒ 寫錯檔,本身就是 FAIL ⇒ 拒寫
        poll = [{"vid": VID, "idx": None, "tool": "restore_desc_pre_rewrite", "phase": "readback_mismatch",
                 "sent_at": T_C}]
        setup(m, tmp, "bcd_p", pre=PRE_SN, stamp=stamp_rows(len(D_NOW), extra=poll))
        yt = StubYT(LIVE)
        code, o = call(m, yt, DRY)
        if code != 1 or "污染" not in o:
            f.append("補二 寫入端 STAMP 被還原紀錄污染:exit %d ≠ 1" % code)
        return f

    def BLOB(m, tmp):  # 第四則 3.:第一行一律是**自算**的 blob(不是寫死的)
        f = []
        raw = Path(os.path.abspath(__file__)).read_bytes()
        want = hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()
        setup(m, tmp, "blob", pre=PRE_SN)
        yt = StubYT(LIVE)
        for argv in (DRY, ["--vid=不合法的 id"], APPLY(H_SHA(D_NOW))):
            code, o = call(m, yt, argv)
            first = o.split("\n")[0]
            if want not in first:
                f.append("%s:第一行不是自算 blob %s…:%r" % (argv[0], want[:8], first[:110]))
        return f

    SCEN = [("S1 正常還原", S1), ("S2 不需還原", S2), ("S3 來源缺", S3), ("S4 只有舊.json", S4),
            ("S5 那一行新舊句都不在/dry-run後被改", S5), ("S6 confirm-sha1不符", S6), ("S7 body多一欄差異", S7),
            ("S8 API錯", S8), ("S9 (a)段外有差", S9), ("S10 (b)需人判", S10),
            ("ADV 對抗樣本", ADV), ("N1 換行被吃掉", N1), ("N2 改到前一行", N2), ("N3 段外只差空白", N3),
            ("N4 寫入端三種壞法", N4), ("N5 09-11真快照", N5),
            ("R5a 回應形狀不對", R5a), ("R5b sent之後落檔失敗", R5b), ("R6 兩個版本一律印", R6),
            ("R7 T0回讀不符", R7), ("BCD 第三則B/C/D+補二", BCD), ("BLOB 自算blob", BLOB)]

    P_M2 = ("    if extra:\n", "    if False:\n")
    P_M4 = ("    body = build_body(vid, live_sn, target)\n", "    body = build_body(vid, src_sn, target)\n")
    P_SENT = ("""    sent_at = now_pair()
    try:
        rstamp({"tool": TOOL, "vid": vid, "idx": None, "phase": "sent", "sent_at": sent_at,
                "old_len": len(live_sn.get("description") or ""), "new_len": len(target),
                "accept_needs_human": bool(checks.get("accept_needs_human"))})
    except Exception as exc:  # noqa: BLE001
        raise Refuse("🔴 落不了 %s 的 sent 行(什麼都還沒送,也還沒落任何證據檔)—— 不寫:%s"
                     % (RESTORE_STAMP.name, str(exc)[:160]))
""", """    sent_at = now_pair()
    meta["_sent_row"] = {"tool": TOOL, "vid": vid, "idx": None, "phase": "sent", "sent_at": sent_at,
                         "old_len": len(live_sn.get("description") or ""), "new_len": len(target),
                         "accept_needs_human": bool(checks.get("accept_needs_human"))}
""")
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
        ("M5", "拿掉「已等於 pre_rewrite ⇒ 不需還原」", [("    if live_desc == target:\n", "    if False:\n")], "S2"),
        ("M6", "拿掉 (a) N0(段外有差 ⇒ 拒寫)", [("    if outside:\n", "    if False:\n")], "S9"),
        ("M6b", "(a) 被 --accept-needs-human 蓋過",
         [("    if outside:\n", "    if outside and not accept_human:\n")], "S9"),
        ("M7", "restore_stamp 改寫進寫入端 STAMP",
         [('    with RESTORE_STAMP.open("a", encoding="utf-8") as fh:\n',
           '    with STAMP.open("a", encoding="utf-8") as fh:\n')], "S1"),
        ("M7g", "拿掉「RESTORE_STAMP 不准等於 STAMP」防呆",
         [("    if RESTORE_STAMP.resolve() == STAMP.resolve():\n", "    if False:\n")], "BCD"),
        ("M8", "new_len 改讀最後一筆 ok 行(ok 行沒有這欄)",
         [('    new_len = sents[0].get("new_len")\n', '    new_len = ok.get("new_len")\n')], "S1"),
        ("M9", "需人判時不檢查 --accept-needs-human",
         [("    if needs and not accept_human:\n", "    if False:\n")], "S10"),
        ("M10", "(a) 換成被駁回的較嚴判準(線上 == pre_rewrite 換新句才寫)",
         [("    outside = n0_diff(live_desc, target)\n",
           "    outside = None if live_desc == target.replace(_SENT_OLD, _SENT_NEW) else \"較嚴判準不符\"\n")], "S5"),
        ("M11", "加回已刪除的「新舊句都不在 ⇒ 拒寫」",
         [("    # (原規格「新舊句都不在 ⇒ 拒寫」已由 wF:p5 刪除、由 (a) 取代 —— 見 docstring M5 / M11)\n",
           "    if _SENT_NEW not in live_desc and _SENT_OLD not in live_desc:\n"
           "        raise Refuse(\"新舊句都不在\")\n")], "S5"),
        # ---- 第三則 N0 的五條承重行 ----
        ("N0a", "N0 不比段前(head)", [("    if not live.startswith(head):", "    if False:")], "ADV"),
        ("N0b", "N0 不比段後(tail)", [("    if not live.endswith(tail):", "    if False:")], "ADV"),
        ("N0c", "N0 不管行數(中段可以有換行)", [('    if "\\n" in mid:', "    if False:")], "ADV"),
        ("N0d", "N0 比對前先 strip(把空白差異吃掉)",
         [("def n0_diff(live, target, _norm=lambda s: s):",
           "def n0_diff(live, target, _norm=lambda s: s.strip()):")], "N3"),
        ("N0e", "N0 拿掉「段外被刪過」的長度護欄",
         [("    if len(head) + len(tail) > len(live):\n", "    if False:\n")], "N1"),
        # ---- 第四則 2.:輸出不准給可貼上的指令列 ----
        ("O1", "exit 4 直接把整行可貼上的指令印出來",
         [('            out("      --accept-needs-human")\n',
           '            out("      %s --accept-needs-human" % cmd)\n')], "S10"),
        ("O2", "exit 1((a) 不成立)也給一行「要蓋過就跑這個」",
         [('        raise Refuse("🔴 (a) N0 段外有差',
           '        out("      要蓋過就跑:--apply --vid=%s --confirm-sha1=%s --accept-needs-human"\n'
           '            % (vid, live_sha1))\n'
           '        raise Refuse("🔴 (a) N0 段外有差')], "S9"),
        # ---- 第四則 3.:自算 blob ----
        ("O3", "blob 改成寫死的位元組",
         [("    raw = Path(os.path.abspath(__file__)).read_bytes()\n", '    raw = b"hardcoded"\n')], "BLOB"),
        ("O4", "第一行不印 blob", [("    out(blob_line())", "    pass  # out(blob_line())")], "BLOB"),
        # ---- 第五則:sent 行之後一律 exit 5 ----
        ("R5", "拿掉「update 回應形狀不對 ⇒ 狀態未知」",
         [("    if not isinstance(resp, dict) or got != target:\n", "    if False:\n")], "R5a"),
        ("R5b", "sent 行之後的例外改吞成別的 code",
         [("    except BaseException:\n        raise StateUnknown(vid)\n",
           "    except BaseException:\n        raise ApiError(\"吞掉了\")\n")], "R5b"),
        # ---- 第六則 ----
        ("R6", "不印 pre_rewrite 那一行",
         [('    out("      pre_rewrite 版 %r" % (pre_line,))\n', "    pass\n")], "R6"),
        ("R6b", "段外對不上時就不印線上那一行",
         [('    return pre_line, (lines[n] if n < len(lines) else "(線上沒有第 %d 行)" % (n + 1))\n',
           '    return pre_line, "(略)"\n')], "R6"),
        # ---- 第七則 ----
        ("R7a", "T0 回讀不符照樣往下走(寫 ok 行、exit 0)",
         [("        raise StateUnknown(vid)  # 第七則:回讀不符不准 exit 0\n", "        pass\n")], "R7"),
        ("R7b", "回讀不符寫成一般 error,不是 readback_mismatch",
         [('                "phase": "readback_mismatch",\n', '                "phase": "error",\n')], "R7"),
        ("R7c", "根本不比 T0 回讀", [("    if a_desc != target:\n", "    if False:\n")], "R7"),
        # ---- 第三則 B / C / D ----
        ("B", "白名單放寬成「認得的 phase 都算無害」",
         [("STAMP_PHASE_OK_AFTER = ()\n", 'STAMP_PHASE_OK_AFTER = ("sent", "ok", "blocked", "error")\n')], "BCD"),
        ("C", "能解析但不是 dict 的列靜默跳過(不算壞行)",
         [("        if not isinstance(row, dict):       # 第三則 C:能解析、但不是 dict 的列也算壞行\n"
           "            bad += 1\n            continue\n",
           "        if not isinstance(row, dict):\n            continue\n")], "BCD"),
        ("D1", "sent 行寫不進去就當沒事往下送",
         [('    except Exception as exc:  # noqa: BLE001\n'
           '        raise Refuse("🔴 落不了 %s 的 sent 行(什麼都還沒送,也還沒落任何證據檔)—— 不寫:%s"\n'
           '                     % (RESTORE_STAMP.name, str(exc)[:160]))\n',
           "    except Exception:  # noqa: BLE001\n        pass\n")], "BCD"),
        ("D2", "sent 行改排到 before/body 證據檔**之後**",
         [P_SENT,
          ('    out("落檔(sent 行之後、送出之前):%s  %sbefore.json / %sbody.json" % (EVID_DIR, base, base))\n',
           '    rstamp(meta["_sent_row"])\n')], "BCD"),
        ("ALIEN", "不檢查寫入端 STAMP 有沒有被還原紀錄污染",
         [('        if row.get("phase") in STAMP_ALIEN_PHASES or row.get("tool") == TOOL:\n',
           "        if False:\n")], "BCD"),
    ]

    print("# %s --self-test  %s  離線;假 client;突變只作用在 SELF-TEST 標記以上" % (TOOL, now_tw().isoformat(timespec="seconds")))
    print("# 判準:上線 body 由本 harness 拿送出前的線上 snippet 逐欄比對(不用受測模組的 body_problems)\n")
    allpass = True
    if re.search(r"^\s*(import|from)\s+fix_period_disclaimer", prod, re.M):
        print("❌ 正式路徑 import 了 fix_period_disclaimer")
        allpass = False
    # 第七則補二：本工具「不讀」 restore_stamp —— 正式路徑只允許寫，不允許拿它做任何決定
    _reads = [ln.strip() for ln in prod.split("\n") if "RESTORE_STAMP" in ln
              and re.search(r"read_text|read_bytes|readlines|is_file|exists\(|glob\(|json\.loads", ln)]
    print("# 第七則補二：正式路徑有沒有讀 restore_stamp 來做決定 → %s" % (_reads or "不讀（只寫）"))
    if _reads:
        allpass = False
    print("# 09-11 真快照 %s：%s"
          % (SNAP_DIR.name,
             SNAP["err"] or "%d 支含舊句恰 1 次（另 %d 個非 snippet 檔略過）；是不是自成一行由 N5 情境判"
             % (len(SNAP["rows"]), SNAP["skipped"])))
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
