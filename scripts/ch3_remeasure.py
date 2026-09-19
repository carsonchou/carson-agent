#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ch3_remeasure.py — 用**官方 Data API** 重抽 09-09 轉型研究的 7 個 query(三輪)。

## 為什麼
`docs/ch3-pivot-directions-2026-09-09.md` 的每個數字都是**單次抽樣**,而產生它們的
儀器是爬 YouTube HTML(ToS III.E.6,已停、已刪)。那份文件自己列的限制②是
「同 query 半小時就變組成」,而它最強的對照(`how to manifest` 與
`is manifestation real` 贏的是同一支片)被總督導同日獨立抽樣推翻。
⇒ 這支工具量的是**重現率**。目的不是證明原文件對或錯。

## 只准三支端點
search.list(type=video、publishedAfter=本輪開跑當下往前 365 天)、videos.list、
channels.list。🔴 不准 yt-dlp、不准抓任何 youtube.com HTML。

## 預算寫在程式裡,不是只寫在派工單上
- 研究帳:每個配額日(太平洋時間換日)上限 `RESEARCH_DAILY_CAP`;開一輪前檢查
  「本日研究已用 + 本輪估計 ≤ 上限」,且「共用帳 `quota.remaining()` − 本輪 ≥ `SHARED_FLOOR`」,
  任一不成立就拒跑並印原因。**每一次呼叫之前**還會再檢查一次硬上限 ——
  估計值錯了也不會超。
- 每次呼叫後照實記進共用帳 `quota.spend()`:共用帳要知道研究花了多少,
  否則發布端會以為額度還在(memory `yt-api-quota-structural-overrun`)。
- 失敗的呼叫也照全價記(估貴不估便宜);403 quotaExceeded → `quota.note_exhausted()`,
  停,不重試。

## 用法
    python scripts/ch3_remeasure.py --check     # 對照+分類樣例+預算狀態,不打 API
    python scripts/ch3_remeasure.py --round 1
    python scripts/ch3_remeasure.py --round 2 --not-before 2026-09-12T08:30+08:00
    python scripts/ch3_remeasure.py --report    # 從落盤原始 JSON 重算並印 markdown 報表

原始資料一律落在 `DATA`(不進 repo;競品資料屬 Non-Authorized Data,2026-10-12 前刪或重抓)。
"""
import argparse
import hashlib
import json
import pathlib
import re
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "ch3_lab"))
import quota  # noqa: E402  —— 只准呼叫 spend / remaining / report / note_exhausted

TOKEN = REPO / "yt_ch2" / "token.json"        # youtube.readonly;不要用 token_manage.json
EXPECT_PROJECT = "881902283633"
DATA = pathlib.Path(r"D:\yt_nonauth_data\ch3_remeasure_2026-09-12")
LEDGER = DATA / "research_ledger.json"

QUERIES = [
    "productivity methods that actually work",
    "study tips backed by science",
    "how to remember what i read",
    "how to manifest",
    "is manifestation real",
    "how to improve memory",
    "dopamine detox",
]
#: 取樣參數 —— **三輪固定不變**,每一輪都原樣落盤。
SEARCH_PARAMS = dict(part="snippet", type="video", order="relevance",
                     regionCode="US", relevanceLanguage="en", maxResults=50)
WINDOW_DAYS = 365

COST_SEARCH = 100
COST_LIST = 1
RESEARCH_DAILY_CAP = 2000
SHARED_FLOOR = 8500
#: 一輪 = 每個 query 一次 search + 一次 videos.list + 一次 channels.list
ROUND_EST = len(QUERIES) * (COST_SEARCH + 2 * COST_LIST)
MIN_GAP = timedelta(hours=2)

#: 勝出判準(照原文件):v/s ≥3 且 觀看 ≥5 萬,訂閱 <15 萬。
SUB_MAX = 150_000
VS_MIN = 3.0
VIEWS_MIN = 50_000

TPE = timezone(timedelta(hours=8))


# ─────────────────────────── 時間 ───────────────────────────
def now_utc():
    return datetime.now(timezone.utc)


def fmt_utc(t):
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_tpe(t):
    return t.astimezone(TPE).strftime("%Y-%m-%d %H:%M:%S")


def pacific_day(t=None):
    """配額日 = 太平洋時間的日期(夏令 UTC-7 → 台北 15:00 換日;冬令 UTC-8 → 16:00)。
    自己算 DST,不依賴 tzdata(Windows 上可能沒裝)。"""
    t = (t or now_utc()).astimezone(timezone.utc)
    y = t.year

    def nth_sunday(month, nth):
        d = datetime(y, month, 1, tzinfo=timezone.utc)
        d += timedelta(days=(6 - d.weekday()) % 7)
        return d + timedelta(days=7 * (nth - 1))

    dst_on = nth_sunday(3, 2) + timedelta(hours=10)
    dst_off = nth_sunday(11, 1) + timedelta(hours=9)
    off = 7 if dst_on <= t < dst_off else 8
    return (t - timedelta(hours=off)).strftime("%Y-%m-%d")


# ─────────────────────────── 判準 ───────────────────────────
def judge(subs, views, hidden):
    """一支片的判定:'hidden' / 'missing' / 'big' / 'win' / 'lose'。
    hidden 訂閱**不算分母也不算勝出**,另列。"""
    if hidden:
        return "hidden"
    if subs is None or views is None:
        return "missing"
    if subs >= SUB_MAX:
        return "big"
    vs = views / subs if subs else float("inf")
    return "win" if (vs >= VS_MIN and views >= VIEWS_MIN) else "lose"


def tally(rows):
    """分母=小頻道(win+lose);hidden / missing / big 都不進分母。
    🔴 對照要走這一支 —— 對照測的必須是真正計數的那條路,不是另寫一份。"""
    return {
        "small": sum(1 for r in rows if r["verdict"] in ("win", "lose")),
        "win": sum(1 for r in rows if r["verdict"] == "win"),
        "hidden": sum(1 for r in rows if r["verdict"] == "hidden"),
        "missing": sum(1 for r in rows if r["verdict"] == "missing"),
        "big": sum(1 for r in rows if r["verdict"] == "big"),
    }


def controls():
    """會產生輸出的對照:三條每輪都印 PASS/FAIL,任一 FAIL 就中止。"""
    def row(subs, views, hidden):
        return {"verdict": judge(subs, views, hidden)}
    neg = tally([row(108, 3_542, False)])
    pos = tally([row(29_000, 3_061_295, False)])
    hid = tally([row(None, 10_000_000, True)])
    return [
        ("陰性:108 訂閱 / 3,542 觀看 必須被擋",
         neg["small"] == 1 and neg["win"] == 0),
        ("陽性:29,000 訂閱 / 3,061,295 觀看 必須勝出",
         pos["small"] == 1 and pos["win"] == 1),
        ("hidden 訂閱 必須不計入(不進分母、不勝出)",
         hid["small"] == 0 and hid["win"] == 0 and hid["hidden"] == 1),
    ]


# ─────────────────── 判斷欄位的分類規則(先於資料寫定)───────────────────
# 🔴 這兩張規則表在看到第一輪結果**之前**寫定並 commit,之後照表分,不邊看邊改。
#    規則只看**標題**(另一需求另看頻道名);第一條命中即停;每一筆都附命中的字詞。
#    規則分錯的,報告裡另列「人工複核異議」,不回頭改規則。
_AUDIO = (r"\b(affirmations?|subliminals?|meditations?|guided|hypnosis|binaural|\d+\s?hz"
          r"|frequenc(?:y|ies)|asmr|music|playlist|lo-?fi|white noise|sleep sounds?)\b")
_FIRST = (r"(?:^|[^\w'])(?:i|i'm|im|i've|ive|i'd)\s+(?:tried|tested|did|spent|used|followed"
          r"|read|studied|practi[cs]ed|manifested|quit|stopped|gave up|went|lived|became"
          r"|made|changed|learned|learnt|memori[sz]ed|took|was|am|got|finally|failed|ran"
          r"|built|found|asked|forced|survived|swapped|replaced|deleted|cut|broke|started"
          r"|hacked)\b"
          r"|\bmy (?:experience|results?|journey|story|routine|honest|\d+[- ]day)\b"
          r"|\bhow i\b|\bwhat happened when i\b|\bwhy i\b|\(it worked\)")
_MYTH = (r"\b(myths?|lies|lied to|misconceptions?|wrong about|stop believing|isn'?t true"
         r"|not true|overrated)\b")
_VERDICT = (r"(?:^|[?.!:|\-(]\s*)(?:is|are|does|do|did|can|could|will|should)\s+"
            r"(?!this\b|these\b|that\b)[\w' ]{0,40}?\b(?:real|work|works|true|legit|fake"
            r"|scam|myth|bs|nonsense|worth it|effective|a lie)\b"
            r"|\b(?:debunk\w*|scam|pseudoscience|fraud|the truth about|truth behind"
            r"|myth or (?:fact|reality)|fact or (?:fiction|myth)|real or fake|exposed"
            r"|what science (?:really )?says)\b"
            r"|^(?:is|are|does|do|did|can|could|will|should)\b(?!\s+(?:this|these|that)\b)[^?]*\?\s*$")
_FILTER = (r"\b(that (?:actually|really) work\w*|actually works?|backed by (?:science|research)"
           r"|science[- ]backed|science[- ]based|evidence[- ]based|research[- ]based|proven"
           r"|scientifically|according to (?:science|research|neuroscien\w*|psycholog\w*"
           r"|a (?:neuroscientist|psychologist|doctor))|neuroscientists?|psychologists?"
           r"|harvard|stanford|studies show|research shows)\b")
_METHOD = (r"\b(how to|how do (?:i|you)|ways? to|tips?|techniques?|methods?|strateg(?:y|ies)"
           r"|steps?|hacks?|habits?|tricks?|guide|system|rules?|secrets?|routine|formula"
           r"|framework|exercises?|do this|try this|rewire|mistakes?|advice|lessons?)\b")
_IMPERATIVE = (r"^(?:stop|do|try|use|make|start|learn|read|study|remember|improve|boost|train"
               r"|rewire|change|reset|fix|build|get|quit|master|memori[sz]e|manifest|never"
               r"|always|don'?t)\b")
#: 「X to <目標動詞>」與「like a pro」也是方法字(例:Simple Science to Burn Fat Like a Pro)
_PURPOSE = (r"\bto (?:burn|lose|build|boost|improve|remember|memori[sz]e|learn|study|focus"
            r"|stop|quit|beat|fix|get|become|manifest|read|rewire|reset|increase|sharpen"
            r"|train|master|enjoy|manage|change|attract|overcome|break|cure|heal|detox"
            r"|double|triple|retain|unlock|reprogram|control)\b|\blike a pro\b")

UNCLASSIFIED = "未分類"

POSTURE_RULES_DOC = [
    ("P1", "其他(音訊/冥想/肯定語)", "標題含 affirmation / subliminal / meditation / guided / hypnosis / binaural / Hz / frequency / ASMR / music / playlist / lofi / white noise / sleep sounds"),
    ("P2", "第一人稱實測", "主詞是 I(I tried / I tested / I did / I spent / I used / I followed / I read / I quit / I manifested … 等經驗動詞)、my experience / my results / my journey / my N-day、How I、Why I、What happened when I、(it worked)"),
    ("P3", "迷思清單", "myth(s) / lies / lied to / misconception(s) / wrong about / stop believing / isn't true / not true / overrated"),
    ("P4", "裁決", "子句開頭的 is/are/does/do/can… + real/work/true/legit/fake/scam/myth/worth it/effective(排除 do this/these/that);debunk / scam / pseudoscience / the truth about / real or fake / exposed / what science says;或整個標題是 is/are/does/do/can… 開頭、? 結尾的問句"),
    ("P5", "篩過的方法", "證據/篩選詞(that actually work / actually works / backed by science / science-based / evidence-based / proven / scientifically / according to science / neuroscientist / psychologist / Harvard / Stanford / studies show)**且**有方法字(見 P6)"),
    ("P6", "純方法", "方法字:how to / ways to / tip(s) / technique(s) / method(s) / strategy / step(s) / hack(s) / habit(s) / trick(s) / guide / system / rule(s) / secret(s) / routine / formula / framework / exercise(s) / do this / try this / rewire / mistake(s) / advice / lesson(s);或標題以祈使動詞開頭(Stop / Do / Try / Use / Learn / Remember / Improve / Rewire / Memorize / Manifest / Never / Don't …);或「to + 目標動詞」(to burn / to remember / to improve / to manifest / to focus …)、like a pro"),
    ("P7", "未分類(只有證據詞)", "只命中 P5 的證據詞,沒有方法字 —— **不落到任何預設類別**,報表計數,勝出片由人工補判並標明"),
    ("P8", "未分類", "以上皆否 —— 同上"),
]

_ESL = r"\b(english|esl|ielts|toefl|toeic|graded reader)\b"
_NONEN_WORD = (r"\b(hindi|urdu|tamil|telugu|bangla|bengali|marathi|español|espanol"
               r"|portugu[eê]s|tagalog|arabic)\b")
_EXAM = r"\b(SAT|ACT|MCAT|USMLE|GCSE|NEET|JEE|UPSC|CBSE|A-?Levels?)\b"   # 大小寫敏感
_RELIGION = (r"\b(bible|biblical|god|jesus|christ|christian|church|pastor|sermon|scripture"
             r"|allah|islam|islamic|quran|sinful|occult|demonic)\b")
_BOOK = (r"\b(book summary|summary|summari[sz]ed|audiobook|audio book|book review"
         r"|animated book|atomic habits|deep work|think and grow rich|the power of habit"
         r"|thinking,? fast and slow|how to win friends|psychology of money|make it stick"
         r"|moonwalking with einstein|ultralearning|7 habits|can'?t hurt me"
         r"|power of your subconscious mind|feeling is the secret|dopamine nation"
         r"|the magic of thinking big)\b")
_BOOK_CH = r"(book|summar|audiobook)"
_PRODUCT = (r"\b(preview|app|apps|my course|course|masterclass|free trial|use code|coupon"
            r"|webinar|sponsored|free pdf|download)\b")

OTHER_RULES_DOC = [
    ("O1", "其他(非英語受眾)", "標題字母中非拉丁文字 ≥30%,或標題/頻道名含 Hindi / Urdu / Tamil / Telugu / Bangla / Bengali / Marathi / Español / Português / Tagalog / Arabic"),
    ("O2", "ESL 英語學習", "標題或頻道名含 English / ESL / IELTS / TOEFL / TOEIC / Graded Reader"),
    ("O3", "其他(特定考試)", "標題含 SAT / ACT / MCAT / USMLE / GCSE / NEET / JEE / UPSC / CBSE / A-Level(大小寫敏感)"),
    ("O4", "其他(宗教觀點)", "標題含 Bible / God / Jesus / Christ / Christian / church / pastor / sermon / scripture / Allah / Islam / Quran / sinful / occult / demonic"),
    ("O5", "其他(音訊/冥想)", "同 P1(需求是『聽』,不是『學怎麼做』)"),
    ("O6", "單本書摘要", "標題含 summary / summarized / audiobook / book review / animated book,或點名一本書(Atomic Habits / Deep Work / Think and Grow Rich / The Power of Habit / Thinking Fast and Slow / How to Win Friends / Psychology of Money / Make It Stick / Moonwalking with Einstein / Ultralearning / 7 Habits / Can't Hurt Me / Power of Your Subconscious Mind / Feeling Is the Secret / Dopamine Nation / The Magic of Thinking Big);或頻道名含 book / summar / audiobook"),
    ("O7", "產品廣告", "標題含 preview / app / course / masterclass / free trial / use code / coupon / webinar / sponsored / free pdf / download"),
    ("O8", "不確定", "頻道名(≥4 字元)原樣出現在標題裡(可能是自家產品,也可能只是署名 —— 不猜);或標題缺漏"),
    ("O9", "未分類(無需求字詞命中)", "以上皆否。**沒命中不等於「無」**(沒看到證據≠證明沒有)⇒ 不落到「無」這個預設類別;報表計數,勝出片由人工讀標題/頻道名補判(無 或其他)並標明是人工判的"),
]

#: 🔴 規則的陽性對照(總督導 09-12 指定)—— 每輪開跑前、`--check` 都印 PASS/FAIL,任一 FAIL 就中止。
#:    最後兩條是「未分類」那條路的陽性對照:證明沒命中的標題真的會被標成未分類,
#:    而不是被某個預設類別默默吃掉。
RULE_CONTROLS = [
    ("姿態", "I Tried the World's Simplest Productivity Hack for 1 Year", "", "第一人稱實測"),
    ("姿態", "Simple Science to Burn Fat Like a Pro", "", "純方法"),
    ("姿態", "30 Years Of Law Of Attraction Advice In 15 Minutes", "", "純方法"),
    ("姿態", "How to REMEMBER Absolutely Everything", "", "純方法"),
    ("姿態", "Dopamine Detox: Cure or Scam?", "", "裁決"),
    ("姿態", "Manifestation: cure or scam?", "", "裁決"),
    ("姿態", "Cold Showers: Cure or Scam?", "", "裁決"),
    ("另一需求", "Learn English Through Story - Graded Reader", "", "ESL 英語學習"),
    ("另一需求", "Learn English with a Short Story", "Story Time", "ESL 英語學習"),
    ("另一需求", "Graded Reader Level 2: The Memory Palace", "Stories Channel", "ESL 英語學習"),
    ("另一需求", "Memory palace training with memoryOS preview", "", "產品廣告"),
    ("另一需求", "Memory palace training with memoryOS preview", "memoryOS", "產品廣告"),
    ("姿態", "A Quiet Afternoon in Kyoto", "", "未分類"),
    ("另一需求", "How to REMEMBER Absolutely Everything", "Some Channel", "未分類(無需求字詞命中)"),
]


def _norm(s):
    return (s or "").replace("\u2019", "'").replace("\u2018", "'").strip()


def _hit(pat, s, flags=re.I):
    m = re.search(pat, s, flags)
    return m.group(0).strip(" -:|(?.!") if m else None


def classify_posture(title):
    t = _norm(title)
    if not t:
        return UNCLASSIFIED, "P8", "標題缺漏"
    for rid, pat, lab in (("P1", _AUDIO, "其他(音訊/冥想/肯定語)"),
                          ("P2", _FIRST, "第一人稱實測"),
                          ("P3", _MYTH, "迷思清單"),
                          ("P4", _VERDICT, "裁決")):
        h = _hit(pat, t)
        if h is not None:
            return lab, rid, h
    f = _hit(_FILTER, t)
    m = _hit(_METHOD, t) or _hit(_IMPERATIVE, t) or _hit(_PURPOSE, t)
    if f and m:
        return "篩過的方法", "P5", f"{f} + {m}"
    if m:
        return "純方法", "P6", m
    if f:
        return "未分類(只有證據詞)", "P7", f
    return UNCLASSIFIED, "P8", ""


def _nonlatin_ratio(s):
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if ord(c) > 0x24F) / len(letters)


def classify_other(title, channel):
    t, ch = _norm(title), _norm(channel)
    if not t:
        return "不確定", "O8", "標題缺漏"
    if _nonlatin_ratio(t) >= 0.30:
        return "其他(非英語受眾)", "O1", f"非拉丁字母 {_nonlatin_ratio(t):.0%}"
    h = _hit(_NONEN_WORD, t) or _hit(_NONEN_WORD, ch)
    if h:
        return "其他(非英語受眾)", "O1", h
    h = _hit(_ESL, t)
    if h:
        return "ESL 英語學習", "O2", f"標題「{h}」"
    h = _hit(_ESL, ch)
    if h:
        return "ESL 英語學習", "O2", f"頻道名「{ch}」"
    h = _hit(_EXAM, t, flags=0)
    if h:
        return "其他(特定考試)", "O3", h
    h = _hit(_RELIGION, t)
    if h:
        return "其他(宗教觀點)", "O4", h
    h = _hit(_AUDIO, t)
    if h:
        return "其他(音訊/冥想)", "O5", h
    h = _hit(_BOOK, t)
    if h:
        return "單本書摘要", "O6", f"標題「{h}」"
    if re.search(_BOOK_CH, ch, re.I):
        return "單本書摘要", "O6", f"頻道名「{ch}」"
    h = _hit(_PRODUCT, t)
    if h:
        return "產品廣告", "O7", h
    if len(ch) >= 4 and ch.lower() in t.lower():
        return "不確定", "O8", f"頻道名「{ch}」出現在標題"
    return "未分類(無需求字詞命中)", "O9", ""


def is_unclassified(label):
    return label.startswith(UNCLASSIFIED)


def rule_controls():
    out = []
    for field, title, ch, want in RULE_CONTROLS:
        got = (classify_posture(title) if field == "姿態" else classify_other(title, ch))
        out.append((f"{field}:「{title}」{'/頻道 ' + ch if ch else ''} → {want}(得到 {got[0]} {got[1]})",
                    got[0] == want))
    return out


#: 分類樣例 —— 原文件裡出現過的真實標題。`--check` 印出來給人看,不是斷言:
#: 樣例分錯要在**跑第一輪之前**決定改不改規則,之後就不准改。
SAMPLES = [
    ("I Tried the World's Simplest Productivity Hack for 1 Year", ""),
    ("I'm begging you to manage your time", ""),
    ("How to Rewire Your Brain to Enjoy Discipline", ""),
    ("Memorize Anything So Fast It's Almost Unfair", ""),
    ("30 Years Of Law Of Attraction Advice In 15 Minutes", ""),
    ("How to REMEMBER Absolutely Everything", ""),
    ("7 Brain Exercises to Sharpen Your Mind", ""),
    ("Dopamine Detox: Solution or Scam?", "Psych2Go"),
    ("Does Anyone Really Have a Photographic Memory?", ""),
    ("Learn English Through Story - Graded Reader", "VUS - Learning English"),
    ("How to remember what you read", "English With Ethan"),
    ("Memory palace training with memoryOS preview", "memoryOS"),
    ("Simple Science to Burn Fat Like a Pro", ""),
]


# ─────────────────────────── 資料整理 ───────────────────────────
def iso_dur(s):
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", s or "")
    if not m:
        return None
    d, h, mi, se = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fmt_label(sec):
    if sec is None:
        return "未知"
    if sec <= 60:
        return "Short(≤60s)"
    if sec <= 180:
        return "≤3分(API 分不出 Short/長片)"
    return "長片"


def build_rows(qd, published_after):
    """從**原始回應**重建每一列。抓取時與 --report 走同一支函式,
    所以第三方可以只靠落盤 JSON 從零重算每個勝出判定。"""
    vids = {v["id"]: v for v in (qd.get("videos_raw") or {}).get("items", [])}
    chs = {c["id"]: c for c in (qd.get("channels_raw") or {}).get("items", [])}
    rows = []
    for rank, it in enumerate((qd.get("search_raw") or {}).get("items", []), 1):
        vid = (it.get("id") or {}).get("videoId")
        sn = it.get("snippet") or {}
        v = vids.get(vid) or {}
        vs_ = v.get("snippet") or {}
        st = v.get("statistics") or {}
        cid = vs_.get("channelId") or sn.get("channelId")
        c = chs.get(cid) or {}
        cst = c.get("statistics") or {}
        hidden = bool(cst.get("hiddenSubscriberCount")) if c else False
        subs = int(cst["subscriberCount"]) if ("subscriberCount" in cst and not hidden) else None
        views = int(st["viewCount"]) if "viewCount" in st else None
        if not v or not c:
            verdict = "missing"
        else:
            verdict = judge(subs, views, hidden)
        title = vs_.get("title") or sn.get("title") or ""
        chname = vs_.get("channelTitle") or sn.get("channelTitle") or ""
        pub = vs_.get("publishedAt") or sn.get("publishedAt") or ""
        # 篩選有沒有套用:search 回的與 videos 回的 publishedAt 任一早於 publishedAfter 都算違反
        pa = parse_ts(published_after)
        viol = any(p and parse_ts(p) < pa for p in (sn.get("publishedAt"), vs_.get("publishedAt")))
        dur = iso_dur((v.get("contentDetails") or {}).get("duration"))
        pos, pos_rid, pos_hit = classify_posture(title)
        oth, oth_rid, oth_hit = classify_other(title, chname)
        rows.append({
            "rank": rank, "videoId": vid, "title": title, "channelId": cid,
            "channelTitle": chname, "subs": subs, "hidden": hidden, "views": views,
            "vs": (round(views / subs, 2) if (views is not None and subs) else None),
            "duration_s": dur, "format": fmt_label(dur), "publishedAt": pub,
            "pub_violation": viol,
            "verdict": verdict,
            "posture": pos, "posture_rule": pos_rid, "posture_basis": pos_hit,
            "other": oth, "other_rule": oth_rid, "other_basis": oth_hit,
        })
    return rows


# ─────────────────────────── 研究帳 ───────────────────────────
def ledger_load():
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    return {"cap_per_quota_day": RESEARCH_DAILY_CAP, "days": {}}


def ledger_spent(day):
    return ledger_load()["days"].get(day, {}).get("spent", 0)


def ledger_spend(cost, label):
    lg = ledger_load()
    day = pacific_day()
    d = lg["days"].setdefault(day, {"spent": 0, "items": []})
    d["spent"] += cost
    d["items"].append({"at_utc": fmt_utc(now_utc()), "cost": cost, "what": label})
    tmp = LEDGER.with_suffix(".tmp")
    tmp.write_text(json.dumps(lg, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(LEDGER)
    return d["spent"]


class Stop(Exception):
    """中止這一輪。不重試。"""


def api_call(req, cost, label, acc):
    day = pacific_day()
    used = ledger_spent(day)
    if used + cost > RESEARCH_DAILY_CAP:
        raise Stop(f"研究帳硬上限:配額日 {day} 已用 {used},再花 {cost} 會超過 "
                   f"{RESEARCH_DAILY_CAP} —— 這一筆不打。")
    from googleapiclient.errors import HttpError
    try:
        resp = req.execute(num_retries=0)
    except HttpError as e:
        body = (e.content or b"").decode("utf-8", "replace")
        ledger_spend(cost, label + "(失敗,照全價記)")
        quota.spend(cost, f"research/remeasure {label}(失敗)")
        acc["units"] += cost
        if e.resp.status == 403 and "quotaExceeded" in body:
            quota.note_exhausted(f"research remeasure {label}")
            raise Stop(f"403 quotaExceeded @ {label} —— 已 note_exhausted,停,不重試")
        raise Stop(f"HttpError {e.resp.status} @ {label}:{body[:300]}")
    ledger_spend(cost, label)
    quota.spend(cost, f"research/remeasure {label}")
    acc["units"] += cost
    return resp


# ─────────────────────────── 憑證 ───────────────────────────
def youtube_client():
    info = json.loads(TOKEN.read_text(encoding="utf-8"))
    got = (info.get("client_id") or "").split("-")[0]
    if got != EXPECT_PROJECT:
        raise SystemExit(f"⛔ {TOKEN.name} 的 client_id 前綴是 {got!r},不是 {EXPECT_PROJECT} —— "
                         f"那是另一本配額帳,中止。")
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    cr = Credentials.from_authorized_user_file(
        str(TOKEN), ["https://www.googleapis.com/auth/youtube.readonly"])
    if not cr.valid:
        cr.refresh(Request())          # 不寫回 token.json
    return build("youtube", "v3", credentials=cr, cache_discovery=False)


# ─────────────────────────── 一輪 ───────────────────────────
def tool_sha():
    return hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()


def round_files(complete_only=True):
    out = {}
    for p in sorted(DATA.glob("r*_*.json")):
        m = re.match(r"r(\d+)_", p.name)
        if not m:
            continue
        if complete_only and p.name.endswith("_ABORTED.json"):
            continue
        out.setdefault(int(m.group(1)), []).append(p)
    return out


def print_controls(res):
    for name, ok in res:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    n_ok = sum(1 for _, ok in res if ok)
    return n_ok, len(res)


def shared_report():
    """把共用帳 `quota.report()` 的輸出原樣收進落盤資料(只呼叫允許的函式)。"""
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        quota.report()
    return buf.getvalue()


def run_round(n, not_before):
    DATA.mkdir(parents=True, exist_ok=True)
    done = round_files()
    if n in done:
        raise SystemExit(f"⛔ 第 {n} 輪已經有完整資料:{done[n][0].name} —— 不重跑。")
    missing_prev = [k for k in range(1, n) if k not in done]
    if missing_prev:
        raise SystemExit(f"⛔ 前面的輪次還沒完成:{missing_prev}")

    if not_before:
        target = datetime.fromisoformat(not_before)
        if target.tzinfo is None:
            raise SystemExit("⛔ --not-before 要帶時區(例如 +08:00)")
        while now_utc() < target:
            time.sleep(min(60, max(1, (target - now_utc()).total_seconds())))

    start = now_utc()
    # 時間閘:距上一輪**結束** ≥ MIN_GAP(以落盤時間戳為準)
    if n > 1:
        prev = json.loads(done[n - 1][0].read_text(encoding="utf-8"))
        prev_end = datetime.fromisoformat(prev["fetched_utc_end"].replace("Z", "+00:00"))
        if start - prev_end < MIN_GAP:
            raise SystemExit(f"⛔ 拒跑:距 r{n-1} 結束({fmt_tpe(prev_end)} 台北)只有 "
                             f"{(start - prev_end)} < {MIN_GAP}")

    print(f"── r{n} 開跑 @台北 {fmt_tpe(start)}(UTC {fmt_utc(start)})"
          f",配額日 {pacific_day(start)}")
    print("判準對照:")
    n_ok, n_all = print_controls(controls())
    if n_ok != n_all:
        raise SystemExit(f"⛔ 判準對照 {n_ok}/{n_all} —— 判準壞了,中止,不打 API。")
    print("分類規則對照:")
    r_ok, r_all = print_controls(rule_controls())
    if r_ok != r_all:
        raise SystemExit(f"⛔ 分類規則對照 {r_ok}/{r_all} —— 中止,不打 API。")

    # 預算閘
    day = pacific_day(start)
    used = ledger_spent(day)
    rem = quota.remaining()
    print(f"  研究帳 配額日 {day} 已用 {used};本輪估計 {ROUND_EST};上限 {RESEARCH_DAILY_CAP}")
    print(f"  共用帳 remaining {rem};扣掉本輪後 {rem - ROUND_EST};地板 {SHARED_FLOOR}")
    if used + ROUND_EST > RESEARCH_DAILY_CAP:
        raise SystemExit(f"⛔ 拒跑:研究帳 {used} + {ROUND_EST} > {RESEARCH_DAILY_CAP}")
    if rem - ROUND_EST < SHARED_FLOOR:
        raise SystemExit(f"⛔ 拒跑:共用帳 {rem} − {ROUND_EST} < {SHARED_FLOOR}")

    yt = youtube_client()
    published_after = fmt_utc(start - timedelta(days=WINDOW_DAYS))
    acc = {"units": 0}
    out = {
        "tool": "scripts/ch3_remeasure.py", "tool_sha256": tool_sha(),
        "round": n, "search_params": SEARCH_PARAMS, "published_after": published_after,
        "criteria": {"SUB_MAX": SUB_MAX, "VS_MIN": VS_MIN, "VIEWS_MIN": VIEWS_MIN},
        "fetched_utc_start": fmt_utc(start), "fetched_taipei_start": fmt_tpe(start),
        "quota_day": day, "controls": [[nm, ok] for nm, ok in controls()],
        "rule_controls": [[nm, ok] for nm, ok in rule_controls()],
        "research_ledger_before": used, "shared_remaining_before": rem,
        "shared_report_before": shared_report(),
        "queries": {}, "status": "running",
    }
    stamp = start.strftime("%Y%m%dT%H%MZ")
    try:
        for q in QUERIES:
            t0 = now_utc()
            qd = {"fetched_utc": fmt_utc(t0), "fetched_taipei": fmt_tpe(t0)}
            out["queries"][q] = qd
            qd["search_raw"] = api_call(
                yt.search().list(q=q, publishedAfter=published_after, **SEARCH_PARAMS),
                COST_SEARCH, f"r{n} {q}", acc)
            ids = [(it.get("id") or {}).get("videoId")
                   for it in qd["search_raw"].get("items", [])]
            ids = [i for i in ids if i]
            qd["videos_raw"] = (api_call(
                yt.videos().list(part="snippet,statistics,contentDetails",
                                 id=",".join(ids), maxResults=50),
                COST_LIST, f"r{n} {q} videos.list", acc) if ids else {"items": []})
            cids = sorted({(v.get("snippet") or {}).get("channelId")
                           for v in qd["videos_raw"].get("items", [])} - {None})
            qd["channels_raw"] = (api_call(
                yt.channels().list(part="snippet,statistics", id=",".join(cids),
                                   maxResults=50),
                COST_LIST, f"r{n} {q} channels.list", acc) if cids else {"items": []})
            rows = build_rows(qd, published_after)
            qd["rows"] = rows
            t10 = tally(rows[:10])
            viol = sum(1 for r in rows if r["pub_violation"])
            print(f"  [{q}] 回傳 {len(rows)} 筆 | publishedAt 違反 {viol} | "
                  f"前10:小頻道 {t10['small']}、勝出 {t10['win']}、hidden {t10['hidden']}"
                  f"、缺資料 {t10['missing']}")
    except Stop as e:
        out["status"] = "aborted"
        out["abort_reason"] = str(e)
        out["fetched_utc_end"] = fmt_utc(now_utc())
        p = DATA / f"r{n}_{stamp}_ABORTED.json"
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        raise SystemExit(f"⛔ r{n} 中止:{e}\n   部分資料:{p}")

    end = now_utc()
    out["status"] = "complete"
    out["fetched_utc_end"] = fmt_utc(end)
    out["fetched_taipei_end"] = fmt_tpe(end)
    out["units"] = acc["units"]
    # 對帳:研究帳是權威(quota.spend() 沒有鎖,和發布端同時寫可能掉一筆)。
    # 共用帳這段期間的變化 = 我的 + 別人同時花的;若小於我的 ⇒ 共用帳掉了我的記錄。
    rem_after = quota.remaining()
    out["research_ledger_after"] = ledger_spent(day)
    out["shared_remaining_after"] = rem_after
    out["shared_report_after"] = shared_report()
    delta_shared = rem - rem_after
    delta_research = out["research_ledger_after"] - used
    out["reconcile"] = {"my_units": acc["units"], "research_ledger_delta": delta_research,
                        "shared_ledger_delta": delta_shared,
                        "same_quota_day": pacific_day(end) == day}
    print(f"  對帳:本輪 {acc['units']} | 研究帳 +{delta_research} | 共用帳 −{delta_shared}"
          + ("" if delta_shared == acc["units"] == delta_research
             else "  ⚠️ 不一致(共用帳 > 本輪 = 同時有別人花;< 本輪 = 共用帳掉記錄;跨配額日則不可比)"))
    p = DATA / f"r{n}_{stamp}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    viol_all = sum(1 for qd in out["queries"].values() for r in qd["rows"] if r["pub_violation"])
    print(f"  落盤 {p}")
    print(f"  publishedAt 違反合計 {viol_all}(期望 0)")
    print(f"r{n} 完成 @台北 {fmt_tpe(end)[11:16]},本輪 {acc['units']} units,"
          f"本日研究累計 {ledger_spent(day)},共用帳剩 {quota.remaining()},"
          f"對照 {n_ok}/{n_all} PASS(分類規則對照 {r_ok}/{r_all})")


# ─────────────────────────── 報表 ───────────────────────────
def load_rounds():
    rs = {}
    for n, ps in round_files().items():
        d = json.loads(ps[0].read_text(encoding="utf-8"))
        for q, qd in d["queries"].items():
            rebuilt = build_rows(qd, d["published_after"])
            if rebuilt != qd["rows"]:
                print(f"⚠️ r{n} [{q}] 從原始回應重算的列與落盤的列不一致", file=sys.stderr)
            qd["rows"] = rebuilt
        rs[n] = d
    return rs


def _k(x):
    return f"{x:,}" if isinstance(x, int) else ("—" if x is None else str(x))


def summarize(rows, k):
    top = rows[:k]
    t = tally(top)
    small = [r for r in top if r["verdict"] in ("win", "lose")]
    wins = [r for r in top if r["verdict"] == "win"]
    best = max(small, key=lambda r: r["vs"] if r["vs"] is not None else float("inf"),
               default=None)
    t["best"] = (f"{best['vs']}x({best['views']:,})" if best and best["vs"] is not None
                 else ("∞" if best else "—"))
    t["med_win"] = int(statistics.median([w["views"] for w in wins])) if wins else None
    # 規則沒命中任何另一需求的勝出片(人工補判之前的上界)
    t["win_clean"] = sum(1 for w in wins if is_unclassified(w["other"]))
    t["win_first"] = sum(1 for w in wins if w["posture"] == "第一人稱實測")
    t["uncl_pos"] = sum(1 for r in top if is_unclassified(r["posture"]))
    t["uncl_oth"] = sum(1 for r in top if is_unclassified(r["other"]))
    t["win_uncl_pos"] = sum(1 for w in wins if is_unclassified(w["posture"]))
    return t


def jaccard(a, b):
    a, b = set(a), set(b)
    return (len(a & b), round(len(a & b) / len(a | b), 3) if (a | b) else None)


def report():
    rs = load_rounds()
    if not rs:
        raise SystemExit("沒有完整的輪次資料")
    N = sorted(rs)
    sha = {rs[n]["tool_sha256"] for n in N}
    print("## 輪次\n")
    print("| 輪 | 台北開始 | 台北結束 | 配額日 | units | 對照 | publishedAt 違反 | 工具 sha256 前 12 |")
    print("|---|---|---|---|---|---|---|---|")
    for n in N:
        d = rs[n]
        v = sum(1 for qd in d["queries"].values() for r in qd["rows"] if r["pub_violation"])
        c = sum(1 for _, ok in d["controls"] if ok)
        print(f"| r{n} | {d['fetched_taipei_start']} | {d['fetched_taipei_end']} | {d['quota_day']} "
              f"| {d['units']} | {c}/{len(d['controls'])} | {v} | `{d['tool_sha256'][:12]}` |")
    print(f"\n工具版本數:{len(sha)}(三輪同一版 = 1)\n")
    print("| 輪 | 研究帳 前→後 | 共用帳 remaining 前→後 | 本輪 units | 一致? |")
    print("|---|---|---|---|---|")
    for n in N:
        d, rc = rs[n], rs[n].get("reconcile", {})
        ok = rc.get("my_units") == rc.get("research_ledger_delta") == rc.get("shared_ledger_delta")
        print(f"| r{n} | {d.get('research_ledger_before')}→{d.get('research_ledger_after')} "
              f"| {d.get('shared_remaining_before')}→{d.get('shared_remaining_after')} "
              f"| {rc.get('my_units')} | {'是' if ok else '否(見文件)'} |")
    print()

    print("## 每個 query × 每輪\n")
    for q in QUERIES:
        print(f"### `{q}`\n")
        print("| 輪 | 回傳 | 前10 小頻道 | 前10 勝出 | 勝出·未命中需求規則 | 勝出·第一人稱 | 勝出·姿態未分類 | hidden | 最佳 v/s(觀看) | 勝出觀看中位 | 前10 未分類 姿態/需求 | 前20 小/勝 | 前50 小/勝 |")
        print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for n in N:
            rows = rs[n]["queries"][q]["rows"]
            a, b, c = summarize(rows, 10), summarize(rows, 20), summarize(rows, 50)
            print(f"| r{n} | {len(rows)} | {a['small']} | {a['win']} | {a['win_clean']} | {a['win_first']} "
                  f"| {a['win_uncl_pos']} | {a['hidden']} | {a['best']} | {_k(a['med_win'])} "
                  f"| {a['uncl_pos']}/{a['uncl_oth']} | {b['small']}/{b['win']} "
                  f"| {c['small']}/{c['win']} |")
        # 跨輪前 10 的組成穩定度
        ids = {n: [r["videoId"] for r in rs[n]["queries"][q]["rows"][:10]] for n in N}
        pairs = [(i, j) for i in N for j in N if i < j]
        if pairs:
            print("\n前 10 跨輪重疊(交集 / Jaccard):" + ";".join(
                f"r{i}–r{j} {jaccard(ids[i], ids[j])[0]}/{jaccard(ids[i], ids[j])[1]}"
                for i, j in pairs))
        # 勝出片(前 10),跨輪合併
        seen = {}
        for n in N:
            for r in rs[n]["queries"][q]["rows"][:10]:
                if r["verdict"] == "win":
                    seen.setdefault(r["videoId"], {"rounds": [], "row": r})
                    seen[r["videoId"]]["rounds"].append(n)
                    seen[r["videoId"]]["row"] = r
        if seen:
            print("\n| videoId | 標題 | 頻道 | 訂閱 | 觀看 | v/s | 長度 | publishedAt | 姿態(規則:依據) | 另一需求(規則:依據) | 勝出於 |")
            print("|---|---|---|---|---|---|---|---|---|---|---|")
            for vid, s in seen.items():
                r = s["row"]
                print(f"| `{vid}` | {r['title'].replace('|', '/')} | {r['channelTitle'].replace('|', '/')} "
                      f"| {_k(r['subs'])} | {_k(r['views'])} | {r['vs']} "
                      f"| {r['duration_s']}s {r['format']} | {r['publishedAt'][:10]} "
                      f"| {r['posture']}({r['posture_rule']}:{r['posture_basis']}) "
                      f"| {r['other']}({r['other_rule']}:{r['other_basis']}) "
                      f"| {' '.join('r%d' % x for x in s['rounds'])} |")
        else:
            print("\n(三輪前 10 皆無勝出片)")
        hid = {r["videoId"]: r for n in N for r in rs[n]["queries"][q]["rows"][:10]
               if r["verdict"] == "hidden"}
        if hid:
            print("\nhidden 訂閱(不計入):" + ";".join(
                f"`{v}` {r['channelTitle']} {_k(r['views'])}" for v, r in hid.items()))
        print()

    print("## manifest 兩個 query 的重疊\n")
    a, b = "how to manifest", "is manifestation real"
    print("| 輪 | 前10 交集/Jaccard | 前50 交集/Jaccard | 前10 勝出交集 | 前50 勝出交集 | rxchelle(how to manifest) | rxchelle(is manifestation real) |")
    print("|---|---|---|---|---|---|---|")
    for n in N:
        ra, rb = rs[n]["queries"][a]["rows"], rs[n]["queries"][b]["rows"]
        j10 = jaccard([r["videoId"] for r in ra[:10]], [r["videoId"] for r in rb[:10]])
        j50 = jaccard([r["videoId"] for r in ra], [r["videoId"] for r in rb])
        w10 = set(r["videoId"] for r in ra[:10] if r["verdict"] == "win") & \
            set(r["videoId"] for r in rb[:10] if r["verdict"] == "win")
        w50 = set(r["videoId"] for r in ra if r["verdict"] == "win") & \
            set(r["videoId"] for r in rb if r["verdict"] == "win")

        def rx(rows):
            hits = [r for r in rows if "rxchelle" in (r["channelTitle"] or "").lower()]
            return ";".join(f"#{r['rank']} `{r['videoId']}` {_k(r['views'])}" for r in hits) or "不在前 50"
        print(f"| r{n} | {j10[0]}/{j10[1]} | {j50[0]}/{j50[1]} | {len(w10)} | {len(w50)} | {rx(ra)} | {rx(rb)} |")

    print("\n## 姿態階梯(前 10 勝出片,七個 query 三輪合併、同一支只算一次)\n")
    ladder = {}
    for n in N:
        for q in QUERIES:
            for r in rs[n]["queries"][q]["rows"][:10]:
                if r["verdict"] == "win":
                    ladder.setdefault(r["posture"], {})[r["videoId"]] = r
    print("| 姿態 | 支數 | v/s 上界 | 觀看範圍 |")
    print("|---|---|---|---|")
    for pos, vids in sorted(ladder.items(), key=lambda kv: -max(r["vs"] or 0 for r in kv[1].values())):
        vs_ = [r["vs"] for r in vids.values() if r["vs"] is not None]
        vw = [r["views"] for r in vids.values()]
        print(f"| {pos} | {len(vids)} | {max(vs_) if vs_ else '—'}x | {min(vw):,}~{max(vw):,} |")


def check():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"現在 台北 {fmt_tpe(now_utc())},配額日(太平洋){pacific_day()}")
    print("判準對照:")
    n_ok, n_all = print_controls(controls())
    print(f"判準對照 {n_ok}/{n_all}")
    print("分類規則對照:")
    r_ok, r_all = print_controls(rule_controls())
    print(f"分類規則對照 {r_ok}/{r_all}")
    print("分類樣例(原文件出現過的標題):")
    for t, ch in SAMPLES:
        p = classify_posture(t)
        o = classify_other(t, ch)
        print(f"  {t[:60]:<60} | {p[0]}({p[1]}:{p[2]}) | {o[0]}({o[1]}:{o[2]})")
    day = pacific_day()
    print(f"研究帳 配額日 {day} 已用 {ledger_spent(day)} / {RESEARCH_DAILY_CAP};一輪估計 {ROUND_EST}")
    print(f"共用帳 remaining {quota.remaining()};地板 {SHARED_FLOOR}")
    print(f"工具 sha256 {tool_sha()}")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int)
    ap.add_argument("--not-before")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.check:
        check()
    elif a.report:
        report()
    elif a.round:
        run_round(a.round, a.not_before)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
