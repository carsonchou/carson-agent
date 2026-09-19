#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_period_disclaimer.py — 給「期間偷換」的已發布片加更正說明(只改描述,不動影片)。

## 為什麼(2026-08-20)
個股體檢的事實有兩組**期間不同**的資料:
    long_horizon = 上市以來/近 20 年 —— 這組**沒有** 0050 對照數字
    three_way    = **近 10 年**(共同起點才能跟 0050 比)—— 0050 的數字只在這組
旁白很自然地拿前者的個股報酬,配上後者的 0050 報酬,中間寫「同期」:
    聯鈞:「20 年賺 4322.4%…同期 0050 是 685.3%」→ 685.3% 其實是 10 年的
    台半:「同期無腦買 0050 總報酬 716%」        → 前文講的是 18.6 年
每個數字都是真的,但期間被偷換,效果是**低估 0050**、讓個股顯得比實際好
——正好和頻道「誠實實測」的定位相反,也正好是觀眾最會檢查的地方
(真留言:「0050 相同期間的含息報酬率差不多」)。

掃描 95 支個股體檢旁白:77 支(81%)犯這條,其中 62 支已發布、合計 13,233 次觀看。
產生端已修(LONG_RULES 規則ⓜ + _long_bad 的 _long_mixed_period 閘門)。

## 為什麼是加更正而不是下架
數字本身都是真的、來源都在事實庫裡,錯的是**期間標示不清**,不是編造。
重製會失去 videoId／觀看數／搜尋排名(搜尋是本頻道唯一在成長的來源),
拿那個換掉一個表述問題不划算。加註說明保留全部既有資產,而且觀眾看得到。
Carson 2026-08-20 拍板選這個做法。

## 安全設計
- **插入不取代**:先 videos.list 取回完整 snippet,只在 description 前面插一段,
  title／tags／categoryId 一字不動原樣送回(videos.update 是整包覆蓋,漏帶等於清空)。
- 原 snippet 備份到 STUDIO/desc_backup/<vid>.json(與章節修正共用同一個備份區)。
- 冪等:描述已含更正標記就跳過。
- 依近 30 天觀看排序:先修還有人在看的。
- 預設 dry-run;--max 控配額(videos.list 1 + videos.update 50 ≈ 51/支)。
"""
from __future__ import annotations

import argparse
import json
import sys
import pathlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

SRC = ROOT / "STUDIO" / "_mixed_period_published.json"
DONE = ROOT / "STUDIO" / "period_disclaimer_done.json"
MARK = "📌 關於片中與 0050 的比較"

# ⚠️ YouTube 描述欄**不渲染 Markdown**:寫 **粗體** 會原樣顯示成兩個星號。
# 第一版直接把內部文件的寫法貼過來,結果觀眾看到的是「取自**近十年**的」。
# 純文字要強調就用「」或全形符號。
# 前三句(MARK、期間說明、兩組數字都真實)在改寫時**一字不動**,
# 只有最後一句換掉。拆成 _HEAD 與尾句兩段,讓「哪裡不准動」在程式碼裡看得見。
_HEAD = (
    f"{MARK}\n"
    "片中提到「同期 0050」的報酬數字,取自「近十年」的共同資料起點(兩檔都有可信資料的"
    "那段期間),與片中個股「上市以來／近二十年」的長期報酬並不是同一段期間。\n"
    "兩組數字各自都是真實回測結果,但放在一起講容易讓人以為是同期對比,特此更正。\n"
)

# 🔴 舊尾句是**假的**:它宣稱「之後的影片已改成在同一句標明期間」,而產生端
#    閘門並不涵蓋後續影片 —— 安勤 3479(09-06 產出,閘門上線後第 17 天)是
#    手工確認的反例。⇒ 我們在 84 支已公開的片上,用一則更正啟事講了另一件
#    不成立的事。Carson 2026-09-11 裁示選項 C(改寫成有界的話),下面這句
#    措辭是他**逐字核定**的。🔴 不要「順一下」,要改必須回去問。
_TAIL_OLD = "之後的影片已改成在同一句標明期間。\n"
_TAIL_NEW = "之後的影片已改進做法,但仍可能有漏的;看到請留言告訴我,我會補上更正。\n"

# 🔴 F5(2026-09-11):插入路徑原本寫 `NOTE = _HEAD + _TAIL_OLD`,也就是**今天正在從
#    84 支上撤掉的那一句**。cron 每天 15:05 跑 `--apply --max 15`,只要
#    _refresh_candidates 找到一支新的中招片(09-05 就新增過 1 支),它就會把已撤回的
#    句子寫到新片上 —— 一邊撤一邊發,而且沒有任何東西會察覺。
#    ⇒ 兩條路徑**共用同一個常數**,不要各寫一份:一份改了另一份沒改,正是這個病的根。
NOTE_NEW = _HEAD + _TAIL_NEW    # Carson 2026-09-11 逐字核定的措辭
NOTE = NOTE_NEW                 # 插入模式(--apply)寫的也是這一份
# 84 支線上**現在**帶的那一份(改寫路徑的輸入)。只給 self_test 造樣本用 ——
# 🔴 不准拿去寫任何東西。F5 之後樣本若還用 NOTE 造,造出來的已經是新句,
#    改寫路徑的對照全部會悄悄變成「冪等不動」而不是在量改寫。
NOTE_OLD = _HEAD + _TAIL_OLD

# ── 要改寫的是**那一句**,不是那一段 ─────────────────────────────
# 🔴 這是這支工具最危險的一段:邊界抓錯 = 吃掉觀眾看得到的原本文案,而且不可逆
#    (YouTube 沒有版本史)。
#
# 第一版我寫成「從 MARK 到段落結束(第一個空行)」。w9:p1 的改寫前盤點
# (commit 97906309 §3d)量到:84 支裡有 **7 支**的 MARK 段落**正中間**被另一個
# 工具插了一行「📚 全系列連播…playlist」。用段落邊界定位,那 7 支會被吃掉一條
# 播放清單連結 —— 而且是安靜地吃掉,因為程式本身沒有任何東西會察覺。
#
# ⇒ 錨釘在**那一句本身**。同一份盤點量到這句在 84/84 逐字相符、每支恰好 1 次,
#   所以「整句逐字取代 + 出現次數必須恰好 1,否則拒寫」是最窄也最安全的寫法。
#   段落裡夾了什麼、順序被誰動過,都與這個錨無關。
_SENT_OLD = _TAIL_OLD.rstrip("\n")
_SENT_NEW = _TAIL_NEW.rstrip("\n")


class Refuse(Exception):
    """不符前提 ⇒ **不動它**。契約是寧可不改,不可以改錯。"""


def locate_sentence(desc, sent):
    """回這句在描述裡的 (start, end);出現次數不是恰好 1 就 raise Refuse。"""
    n = desc.count(sent)
    if n != 1:
        raise Refuse("該句出現 %d 次(必須恰好 1 次)" % n)
    i = desc.index(sent)
    return i, i + len(sent)


def rewrite_desc(desc):
    """回 (new_desc, old_sent, new_sent);已是新措辭則回 (None, None, None)。

    任何不符前提的情況一律 raise Refuse,不回傳「盡力而為」的結果。
    """
    nm = desc.count(MARK)
    if nm == 0:
        raise Refuse("描述裡沒有 MARK ⇒ 這支沒被加過更正,不該動它")
    if nm > 1:
        raise Refuse("MARK 出現 %d 次 —— 結構不明" % nm)
    if _SENT_NEW in desc:
        if _SENT_OLD in desc:
            raise Refuse("新舊兩句同時存在 —— 上一次改寫可能只做了一半")
        return None, None, None                      # 冪等:已經是新措辭
    st, en = locate_sentence(desc, _SENT_OLD)
    return desc[:st] + _SENT_NEW + desc[en:], _SENT_OLD, _SENT_NEW


def insert_desc(desc):
    """插入路徑(cron 每天 15:05 走的那條):把 NOTE 插到描述最前面。

    回 None = 已經有 MARK,不必再插。
    🔴 **超過上限一律 raise Refuse,不硬截**。舊版寫 `new_desc[:4990]`,
       那會從**描述尾巴**吃掉字 —— 尾巴放的正是訂閱連結、播放清單、免責聲明,
       而且沒有任何訊號(YouTube 照樣回 200)。契約是寧可不改,不可以改錯。
    """
    if MARK in desc:
        return None
    new = NOTE + "\n" + desc
    if len(new) > DESC_LIMIT:
        raise Refuse("插入後 %d 字元 > %d ⇒ 拒寫(硬截會吃掉描述尾巴)"
                     % (len(new), DESC_LIMIT))
    return new


def route_of(args):
    """這組參數會走哪條路。main() **只**透過這個函式分派,兩邊不會各寫一份。

    🔴 cron 第 644 行的參數(`--apply --max 15`,不帶任何新旗標)必須回 "insert":
       改寫是對外寫入,只能靠 --rewrite-note 這個明確的新旗標觸發。
       self_test 有一格用 cron 那串 argv 原封不動釘住這件事。
    """
    if args.self_test:
        return "self_test"
    if args.rewrite_note:
        return "rewrite"
    return "insert"


def _client_side_quota(exc):
    """這個例外是**我們自己的帳本**丟的,還是 Google 回的?

    quota_meter 在送出**之前**丟 QuotaExhausted(quota_meter.py:762/794/834),
    訊息開頭固定是 `quota exhausted:` 或 `quota reserve:`;Google 的真 403 走
    HttpError,內容是 quotaExceeded。memory `quota-self-throttle-vs-google-403`:
    九次「配額不足」**全部**是客戶端自己丟的,而三個來源都寫成無主詞被動式
    ⇒ 這裡一定要把主詞分出來,不然下一個人又會去找 Google 要配額。
    """
    if type(exc).__name__ == "QuotaExhausted":
        return True
    s = str(exc)
    return s.startswith("quota exhausted:") or s.startswith("quota reserve:")


def invariant_ok(old_desc, new_desc):
    """🔴 除了那一句以外,**每一個字元都必須逐字相同**。

    刻意**不**寫成 `old[:s] + old[e:] == new[:s] + new[s+len(new_sent):]` ——
    那個式子由 rewrite_desc 的建構方式保證成立,是恆真句,量不到任何東西
    (memory `verification-that-cannot-fail`)。
    這裡對新舊描述**各自獨立重新定位**那一句,挖掉,再比剩下的。
    多吃/少吃一個字元、定位有 bug、段落裡的播放清單行被動到,都會在這裡翻面。
    """
    try:
        s1, e1 = locate_sentence(old_desc, _SENT_OLD)
    except Refuse as exc:
        return False, "舊描述重新定位失敗:%s" % exc
    try:
        s2, e2 = locate_sentence(new_desc, _SENT_NEW)
    except Refuse as exc:
        return False, "新描述重新定位失敗:%s" % exc
    if _SENT_OLD in new_desc:
        return False, "新描述裡舊句還在 —— 沒有真的換掉"
    rem_o = old_desc[:s1] + old_desc[e1:]
    rem_n = new_desc[:s2] + new_desc[e2:]
    if rem_o == rem_n:
        return True, "其餘 %d 字元逐字相同" % len(rem_o)
    for k in range(min(len(rem_o), len(rem_n))):
        if rem_o[k] != rem_n[k]:
            return False, ("挖掉那一句之後第 %d 字元起不同:舊 %r / 新 %r"
                           % (k, rem_o[k:k + 26], rem_n[k:k + 26]))
    return False, "長度不同:舊 %d / 新 %d" % (len(rem_o), len(rem_n))


PLAYLIST = "📚 全系列連播｜個股體檢｜台股個股歷史數據連載:https://www.youtube.com/playlist?list=PL"


def _sample(with_playlist):
    """造一支測試用描述。with_playlist = w9 盤點裡那 7 支的形狀。"""
    body = "【某檔 長期回測】原本的文案第一行\n\n⭐ 訂閱:https://example.invalid\n"
    if not with_playlist:
        return NOTE_OLD + "\n" + body
    head = MARK + "\n\n" + PLAYLIST + "\n\n"
    return head + NOTE_OLD[len(MARK) + 1:] + "\n" + body


def self_test():
    """陽性對照:證明上面那把尺**會翻面**,而不是恆綠。不連網。"""
    ok_all = True

    def say(good, label):
        nonlocal ok_all
        ok_all = ok_all and good
        print("  %s %s" % ("OK " if good else "!! ", label))

    old = _sample(False)
    new, o_s, n_s = rewrite_desc(old)
    say(o_s == _SENT_OLD and n_s == _SENT_NEW, "① 切到的就是那一句,前後都沒多吃")
    say(new.startswith(_HEAD[:len(MARK) + 1]), "② MARK 那行原封不動")
    say(_SENT_OLD not in new and _SENT_NEW in new, "③ 尾句換掉了")
    say(invariant_ok(old, new)[0], "④ 不變量:其餘逐字相同")
    say(len(new) - len(old) == len(_SENT_NEW) - len(_SENT_OLD),
        "⑤ 長度只差那一句的差額(%+d 字元)" % (len(_SENT_NEW) - len(_SENT_OLD)))

    # 🔴 w9 盤點裡那 7 支的形狀:播放清單被插在 MARK 段落正中間
    old7 = _sample(True)
    new7, _a, _b = rewrite_desc(old7)
    say(PLAYLIST in new7, "⑥ 那 7 支的形狀:播放清單連結**還在**")
    say(new7.count(PLAYLIST) == old7.count(PLAYLIST) == 1,
        "⑦ 播放清單連結沒被複製也沒被刪")
    say(invariant_ok(old7, new7)[0], "⑧ 那 7 支的形狀也通過不變量")
    say(old7.split(PLAYLIST)[0] == new7.split(PLAYLIST)[0],
        "⑨ 播放清單**之前**的字元逐字相同")

    bad1 = new[:len(_HEAD)] + new[len(_HEAD) + 1:]
    say(not invariant_ok(old, bad1)[0], "⑩【陽性】多吃一個字元被抓到")
    say(not invariant_ok(old, new + "偷加一句")[0], "⑪【陽性】尾巴被加字被抓到")
    say(not invariant_ok(old, new.replace("⭐ 訂閱", "★ 訂閱"))[0],
        "⑫【陽性】那一句**以外**被改一個字被抓到")
    say(not invariant_ok(old7, new7.replace(PLAYLIST, ""))[0],
        "⑬【陽性】播放清單行被吃掉會被抓到 —— 這正是段落取代會犯的錯")
    say(not invariant_ok(old, old)[0], "⑭【陽性】根本沒改(舊句還在)被抓到")

    for lab, d in (("沒有 MARK", "隨便一段描述,沒有更正說明\n"),
                   ("MARK 兩次", old + old),
                   ("新舊句同時在", old.replace(_SENT_OLD, _SENT_OLD + _SENT_NEW))):
        try:
            rewrite_desc(d)
            say(False, "⑮【陽性】%s 應該要被拒" % lab)
        except Refuse as exc:
            say(True, "⑮【陽性】%s ⇒ 拒動:%s" % (lab, str(exc)[:44]))

    n2, _c, _d = rewrite_desc(new)
    say(n2 is None, "⑯ 冪等:已是新措辭就不再動")
    say(invariant_ok(old, new)[0], "⑰【陰性】正常樣本仍然通過(尺沒壞成恆假)")

    # ── 寫入時間戳(督導 wF:p5 2026-09-11 加的驗收條件)──────────
    # 🔴 「每支 update 都會落時間戳」如果沒人驗過,它跟寫在 commit 訊息裡的
    #    「已驗證」是同一種東西(memory `verification-claims-in-commit-messages`)。
    #    下面三格讓這個宣稱會翻面。
    import tempfile as _tf
    import datetime as _dt2
    g = globals()
    real_stamp_path = g["STAMP"]
    try:
        tmpd = pathlib.Path(_tf.mkdtemp(prefix="stamp_selftest_"))
        g["STAMP"] = tmpd / "s.jsonl"
        n1 = _now()
        drift = (_dt2.datetime.fromisoformat(n1["tpe"])
                 - _dt2.datetime.fromisoformat(n1["utc"]).replace(tzinfo=None)
                 ).total_seconds()
        say(abs(drift - 8 * 3600) < 2.0,
            "⑱ _now():台北時間確實 = UTC+8(同一瞬間的兩種寫法,不是兩次 now)")
        _stamp({"vid": "TEST_A", "phase": "sent"})
        _stamp({"vid": "TEST_B", "phase": "ok"})
        rows = [json.loads(x) for x in
                g["STAMP"].read_text(encoding="utf-8").splitlines() if x.strip()]
        say(len(rows) == 2 and rows[0]["vid"] == "TEST_A"
            and rows[1]["vid"] == "TEST_B",
            "⑲ _stamp 兩筆真的落到磁碟、讀得回來、順序沒亂")

        # 🔴【陽性】寫不進去時必須**拋出來**。悄悄少掉幾行的時間戳檔,
        #    比完全沒有時間戳檔更會騙人 —— 它看起來像一份完整紀錄。
        blocker = tmpd / "blocker"
        blocker.write_text("x", encoding="utf-8")
        g["STAMP"] = blocker / "nope" / "s.jsonl"
        try:
            _stamp({"vid": "TEST_C"})
            say(False, "⑳【陽性】寫不進去卻沒出聲 —— 靜默失敗")
        except Exception:  # noqa: BLE001
            say(True, "⑳【陽性】寫不進去會拋例外,不是靜默吞掉")
    finally:
        g["STAMP"] = real_stamp_path

    # ── F1:整包覆寫不准清掉線上原本有值的可寫欄位 ────────────────────
    # 🔴 videos.update 是**整包覆寫**:可寫欄位沒帶就會被清空,而 YouTube 會自己
    #    重猜 defaultAudioLanguage。同一批片 8 月走插入模式時已經發生過一次
    #    (15 支從 zh/zh-Hant 變成 en-US),推翻 fix_audio_language 兩週的成果。
    #    每一格都配一個突變:突變沒翻紅 = 上一格量到的不是它宣稱的那件事
    #    (memory `load-bearing-line-needs-mutation`)。
    nl = chr(10)
    live = {"title": "【某檔 3999】長期回測", "description": old,
            "categoryId": "22", "tags": ["台股", "回測"],
            "defaultLanguage": "zh-Hant", "defaultAudioLanguage": "zh-Hant"}
    b = build_body("VID_TEST", live, new)
    say(body_keeps_fields(live, b)[0], "㉑ F1:body 帶齊線上有值的可寫欄位")
    # .get / pop(…, None):欄位真的不見時要**翻紅**,不是 KeyError 崩潰(崩潰會
    # 讓後面的格子全部沒跑到 —— 原始碼突變實測踩過)。
    say(b["snippet"].get("description") == new
        and b["snippet"].get("title") == live["title"]
        and b["snippet"].get("defaultAudioLanguage") == "zh-Hant",
        "㉑b F1:只有 description 換掉,其餘原樣帶回去")
    for miss in ("defaultAudioLanguage", "defaultLanguage", "title", "tags"):
        mut = {"id": "VID_TEST", "snippet": dict(b["snippet"])}
        mut["snippet"].pop(miss, None)
        mok, mbad = body_keeps_fields(live, mut)
        say((not mok) and any(miss in x for x in mbad),
            "㉑c【突變】body 少帶 %s ⇒ 翻紅(%s)"
            % (miss, (mbad[0][:44] if mbad else "🔴 沒翻紅")))
    mut2 = {"id": "VID_TEST", "snippet": dict(b["snippet"])}
    mut2["snippet"]["defaultAudioLanguage"] = "en-US"
    say(not body_keeps_fields(live, mut2)[0],
        "㉑d【突變】值被改成 en-US(8 月那次的形狀)⇒ 翻紅")

    live_x = dict(live, newWritableField="x")
    say(not body_keeps_fields(live_x, build_body("VID_TEST", live_x, new))[0],
        "㉑e F1:線上出現**不認得的鍵** ⇒ 當成必須帶 ⇒ 拒寫(不是悄悄清空)")
    live_r = dict(live, thumbnails={"default": {}}, channelTitle="量化阿森",
                  publishedAt="2026-09-01T00:00:00Z")
    say(body_keeps_fields(live_r, build_body("VID_TEST", live_r, new))[0],
        "㉑f【陰性】唯讀鍵(thumbnails/channelTitle/publishedAt)沒帶 ⇒ 不該翻紅")

    # ── F3-M3:「那一句出現 2 次要拒寫」要被真的釘住 ──────────────────
    dup = old.replace(_SENT_OLD, _SENT_OLD + nl + _SENT_OLD, 1)
    try:
        locate_sentence(dup, _SENT_OLD)
        say(False, "㉒ F3-M3:同一句出現 2 次居然沒被拒")
    except Refuse as exc:
        say("2" in str(exc), "㉒ F3-M3:同一句出現 2 次 ⇒ 拒寫(%s)" % str(exc)[:40])

    def _mutant_n0(d, s):
        """突變體:把「恰好 1 次」放寬成「不是 0 次就好」。"""
        if d.count(s) == 0:
            raise Refuse("該句出現 0 次")
        i = d.index(s)
        return i, i + len(s)

    try:
        _mutant_n0(dup, _SENT_OLD)
        say(True, "㉒b【突變】次數檢查放寬成 n==0 ⇒ 2 次被放過 ⇒ 上一格釘的就是次數")
    except Refuse:
        say(False, "㉒b【突變】突變體也拒了 ⇒ 上一格量到的**不是**次數檢查")

    # ── F3-M4:核准措辭本身要被釘住(第二份獨立抄寫,不是引用同一個常數)──
    APPROVED = "之後的影片已改進做法,但仍可能有漏的;看到請留言告訴我,我會補上更正。"
    say(_SENT_NEW == APPROVED,
        "㉓ F3-M4:新句逐字等於 Carson 2026-09-11 核定的措辭")
    say(NOTE_NEW.endswith(APPROVED + nl) and _SENT_OLD not in NOTE_NEW,
        "㉓b F3-M4:NOTE_NEW 的尾句就是它,舊句不在裡面")
    for lab, mt in (("逗號換全形", APPROVED.replace(",", "，")),
                    ("分號換全形", APPROVED.replace(";", "；")),
                    ("句號換半形", APPROVED.replace("。", ".")),
                    ("「漏的」改「漏掉的」", APPROVED.replace("漏的", "漏掉的"))):
        say(_SENT_NEW != mt, "㉓c【突變】%s ⇒ 與核定措辭不同(會翻紅)" % lab)

    # ── F5:插入路徑(cron 15:05 走的那條)寫的必須是**新句** ────────────
    say(NOTE is NOTE_NEW, "㉔ F5:插入路徑與改寫路徑共用同一個常數(不是各寫一份)")
    say(_SENT_NEW in NOTE and _SENT_OLD not in NOTE,
        "㉔b F5:插入路徑寫出去的是新句,已撤回的舊句不在裡面")
    say((_HEAD + _TAIL_OLD) != NOTE,
        "㉔c【突變】若把 NOTE 改回 _HEAD + _TAIL_OLD ⇒ 與上一格衝突(會翻紅)")
    plain = "【某檔 3999】原本的文案\n\n⭐ 訂閱:https://example.invalid\n"
    ins = insert_desc(plain)
    say(ins.startswith(MARK) and ins.endswith(plain) and _SENT_NEW in ins,
        "㉔d F5:插入是加在最前面,原文一字不動")
    say(insert_desc(ins) is None, "㉔e F5:已有 MARK 就不再插(冪等)")

    # ── F5:超過上限要**拒寫**,不准硬截(舊版是 new_desc[:4990])────────
    longd = "字" * (DESC_LIMIT + 10)
    try:
        insert_desc(longd)
        say(False, "㉕ F5:插入後超長居然沒被拒(會硬截掉描述尾巴)")
    except Refuse as exc:
        say("拒寫" in str(exc), "㉕ F5:插入後超長 ⇒ 拒寫(%s)" % str(exc)[:46])
    say(len((NOTE + nl + longd)[:DESC_LIMIT]) == DESC_LIMIT
        and (NOTE + nl + longd)[:DESC_LIMIT] != (NOTE + nl + longd),
        "㉕b【對照】硬截確實會吃掉尾巴 —— 這正是不准做的事")

    # ── cron 第 644 行那串參數必須走插入路徑 ───────────────────────────
    # 🔴 `5 15 * * * … fix_period_disclaimer.py --apply --max 15`
    #    改寫 = 未經放行的對外寫入,只能靠 --rewrite-note 這個明確旗標觸發。
    cron_args = _parser().parse_args(["--apply", "--max", "15"])
    say(route_of(cron_args) == "insert",
        "㉖ cron 那行原封不動的參數 ⇒ 走插入路徑(不是改寫)")
    say(cron_args.apply is True and cron_args.max == 15
        and cron_args.rewrite_note is False and cron_args.self_test is False,
        "㉖b cron 參數解析出來就是 --apply --max 15,沒帶任何新旗標")
    say(route_of(_parser().parse_args(["--rewrite-note", "--apply"])) == "rewrite",
        "㉖c 只有 --rewrite-note 才會走改寫路徑")

    class _MutArgs:
        """突變體:有人把改寫做成預設(忘了讀旗標)。"""
        apply, max, rewrite_note, self_test = True, 15, True, False

    say(route_of(_MutArgs()) != "insert",
        "㉖d【突變】旗標被當成恆真 ⇒ cron 參數會走進改寫(上一格會翻紅)")

    # ── F4:配額拒絕要分得出**主詞**(我們自己的帳本 vs Google)─────────────
    # 用**真的** quota_meter.QuotaExhausted,不自己造一個同名類別 —— 造的會跟著
    # 我的假設一起錯。import 不到就記紅,不准靜默跳過。
    try:
        from quota_meter import QuotaExhausted as _QE
    except Exception as exc:  # noqa: BLE001
        _QE = None
        say(False, "㉗ F4:import quota_meter 失敗(%s)⇒ 這幾格量不到" % str(exc)[:40])
    if _QE is not None:
        say(_client_side_quota(_QE("預算用完")),
            "㉗ F4:真的 QuotaExhausted(訊息不帶前綴也算)⇒ 本機帳本擋的")
        say(_client_side_quota(RuntimeError("quota exhausted:videos.update 需 50,今日剩 0")),
            "㉗b F4:`quota exhausted:` 前綴(被包成別的型別也認得)⇒ 本機")
        say(_client_side_quota(RuntimeError("quota reserve:videos.update 需 50 units,今日剩 40")),
            "㉗c F4:`quota reserve:`(cron 帶 YT_QUOTA_RESERVE=23650)⇒ 本機")
        g403 = RuntimeError('<HttpError 403 "The request cannot be completed because '
                            'you have exceeded your quota." reason: quotaExceeded>')
        say(not _client_side_quota(g403),
            "㉗d【陰性】Google 的真 403(quotaExceeded)⇒ **不是**本機擋的")

    print("  " + ("全部通過" if ok_all else "🔴 有格子沒過"))
    return 0 if ok_all else 1



def _views_map():
    try:
        import yt_analytics as ya
        from datetime import date, timedelta
        svc = ya._service()
        if svc is None:
            return {}
        r = svc.reports().query(
            ids="channel==MINE", startDate=(date.today() - timedelta(days=30)).isoformat(),
            endDate=date.today().isoformat(), dimensions="video", metrics="views",
            sort="-views", maxResults=200).execute()
        return {x[0]: x[1] for x in (r.get("rows") or [])}
    except Exception:  # noqa: BLE001
        return {}


def _refresh_candidates(rows):
    """把候選名單重算一次並併回去(2026-08-22 修)。

    原本 SRC 是 2026-08-20 掃出來的**靜態快照**(62 筆),之後新發布的片就算中招也
    永遠不會進名單——實測當天就已經漏了 21 支(全是 08-20 之後發布的)。
    改成每次跑都用產線本尊的 `_long_mixed_period` 重掃台帳,聯集進名單。

    ⚠️ 精準度優先:這支工具的動作是**在已公開的影片上加一則認錯啟事**,
    對沒錯的影片加註等於憑空自認有錯,比漏加更傷。所以這裡比產線閘門嚴一級——
    只收「命中句本身有引到數字(%/倍)」的,濾掉像
    「成千上萬的上班族幾乎都在同一時間領到薪水…元大台灣50」這種順帶提及
    (實測就是這一支被誤收)。產線閘門那邊維持寬鬆(誤判只是多重生一次)。
    """
    import re as _re
    try:
        import produce_batch as _pb
        led = json.loads((ROOT / "STUDIO" / "uploaded_ledger.json").read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 候選名單重算跳過({str(exc)[:60]}),沿用既有名單")
        return rows
    _num = _re.compile(r"\d+(?:\.\d+)?\s*%|\d+(?:\.\d+)?\s*倍|百分之[零一二三四五六七八九十百]+")
    have = {r[1] for r in rows}
    added = 0
    for slug, vid in led.items():
        if not isinstance(vid, str) or not vid or not slug.startswith("L_") or vid in have:
            continue
        vp = ROOT / "output" / f"{slug}.voice.txt"
        if not vp.exists():
            continue
        t = vp.read_text(encoding="utf-8", errors="replace")
        if not _pb._long_mixed_period(t, slug):
            continue
        # 命中句必須自己引了數字才收(見 docstring 的精準度優先)
        hit_sents = [s for s in _re.split(r"(?<=[。!?！？])", t)
                     if _pb._long_mixed_period(s, slug)]
        if not any(_num.search(s) for s in hit_sents):
            continue
        rows.append([slug, vid, "auto-refresh"])
        added += 1
    if added:
        try:
            import studio_common as sc
            sc.save_json_atomic(SRC, rows)
        except Exception:  # noqa: BLE001
            SRC.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        print(f"候選名單重算:新增 {added} 支(名單原本是靜態快照,新發布的片以前進不來)")
    return rows


DESC_LIMIT = 4990        # YouTube 上限 5000;沿用插入模式的安全邊際

# 改寫前的全量原文備份(w9:p1 於 2026-09-11 落下,完整 item,含 status)
SNAP = ROOT / "STUDIO" / "desc_snapshot_20260911"
# 🔴 STUDIO/ 整個被 .gitignore ⇒ 上面那份**只存在這台機器的磁碟上**。
#    第二份鏡像放在 repo 以外,--apply 前必須驗過,否則退路只有一份。
MIRROR = pathlib.Path(r"D:\backup\desc_snapshot_20260911")

# w9 盤點量到的 7 支:MARK 段落**正中間**被插了一行播放清單連結。
# 它們是這次改寫的必測清單 —— 段落取代會在這 7 支吃掉那條連結。
WATCH7 = ("-_aUs0oj1o0", "OtwYzI6XE8Y", "Slty-G_Gdj4", "TBMTuaUTd8A",
          "WNrS46cXiQ8", "l36tPQliBSc", "p6Qvg2mC-9w")
PL_PREFIX = "📚 全系列連播"

# ── 寫入時間戳 ──────────────────────────────────────────────────
# 🔴 有 8 支常駐 job 會 read-modify-write 同一個描述欄(wF:p1 回讀計畫,
#    commit a3994a6f),其中一支週五 16:50 的 industry_playlists --apply
#    就落在寫入窗口內。它們把我們的句子蓋回去,和 YouTube 吐舊快取,
#    在回讀端是**同一個畫面**:兩者都只表現成「回讀讀到舊字」。
#    要分得開,唯一的辦法是留下每一支的送出/回應時間,事後跟那 8 支 job
#    的執行時間對齊。少了它,回讀的結論只能是「不知道」——而「不知道」
#    很容易被讀成「快取而已,再等等」,那是錯的方向。
# ⚠️ ROOT 是 youtube_channel/,**不是** repo 根 —— 第一版寫成 ROOT/"docs"/"ops",
#    會落到一個不存在的 youtube_channel/docs/ops/。dry-run 把路徑印出來才抓到。
#    要進版控的東西路徑寫錯 = 它不在任何人找得到的地方(只在磁碟上都不算)。
STAMP = (ROOT.parent / "docs" / "ops"
         / "2026-09-11_84支更正句改寫_寫入時間戳.jsonl")


def _now():
    """同時記 UTC 與台北。排程表是台北時間,API 回應是 UTC ——
    只記一種,對齊時就多一次心算,而時區錯配已經咬過這個專案一次
    (memory `yt-api-quota-structural-overrun`)。"""
    import datetime as _dt
    u = _dt.datetime.now(_dt.timezone.utc)
    t = u.astimezone(_dt.timezone(_dt.timedelta(hours=8)))
    return {"utc": u.isoformat(timespec="milliseconds"),
            "tpe": t.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]}


def _stamp(row):
    """一行一筆,**逐行 flush + fsync**。

    程式中途掛掉、或 update 送出後才爆,已送出的那幾筆必須還在磁碟上
    ——那正是最需要它的情況(memory `only-what-lands-on-disk-exists`)。
    """
    import os as _os
    STAMP.parent.mkdir(parents=True, exist_ok=True)
    with STAMP.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        _os.fsync(fh.fileno())


def _stamped(vid):
    """這支在時間戳檔裡有沒有我們自己的 sent/ok 紀錄。回 (有沒有, 最後一筆)。

    用途只有一個:線上已經是新措辭時,分辨「是本工具寫的」還是「不明來源」。
    後者不准算成完成 —— 那正是常駐 job 或別人動過手的形狀。
    """
    if not STAMP.exists():
        return False, None
    last = None
    for ln in STAMP.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            row = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        if row.get("vid") == vid and row.get("phase") in ("sent", "ok"):
            last = row
    return last is not None, last


# ── videos.update 是整包覆寫:這張表漏一個欄位,線上那個欄位就被清空 ──
# 🔴 `defaultAudioLanguage` **是可寫欄位**,不是唯讀。這支工具 8 月的插入模式
#    只帶了 title/description/categoryId/tags/defaultLanguage 送出去,把 15 支的
#    defaultAudioLanguage 清掉(ops_log 的「音軌語言還剩」在插入隔天跳升,
#    增量對得上寫入支數)—— 而 repo 裡有 fix_audio_language.py 專門在設它,
#    兩週的成果被一次寫入推翻。ch3_lab/retitle.py:228 已經為同一個欄位踩過一次,
#    「同一句話三份只修最安靜的那份」。
# ⇒ 不寫死預設值,從**寫入當下 videos.list 讀回的 snippet** 原樣帶上去。
# videos.list 回來的 snippet 裡,API 文件列為**唯讀**的鍵(送回去被忽略、不送也不會被清)。
# 2026-09-11 對 desc_snapshot_20260911 的 87 支實測:snippet 恰好 12 個鍵
# = 這 6 個唯讀 + 下面 6 個可寫,沒有第 13 個。
_READONLY_SNIPPET = ("publishedAt", "channelId", "thumbnails", "channelTitle",
                     "liveBroadcastContent", "localized")
_WRITABLE_SNIPPET = ("title", "description", "tags", "categoryId",
                     "defaultLanguage", "defaultAudioLanguage")


def build_body(vid, live_sn, new_desc):
    """只換 description,其餘可寫欄位原樣從線上帶回去。"""
    snip = {}
    for k in _WRITABLE_SNIPPET:
        if k == "description":
            snip[k] = new_desc
            continue
        v = live_sn.get(k)
        if k == "tags":
            snip[k] = list(v) if v else []
        elif v not in (None, ""):
            snip[k] = v
    return {"id": vid, "snippet": snip}


def body_keeps_fields(live_sn, body):
    """🔴 線上原本有值的可寫欄位,body 少帶一個或改了值就翻紅。回 (ok, 問題清單)。

    刻意**不**拿 build_body 自己產生的東西互相比對 —— 那由建構方式保證成立,
    是恆真句(memory `verification-that-cannot-fail`)。這裡拿**線上 snippet**
    當獨立基準,逐欄位問三個問題:你有值嗎 / body 帶了嗎 / 值一樣嗎。
    """
    bad = []
    snip = body.get("snippet") or {}
    # 🔴 迴圈刻意**不**走 _WRITABLE_SNIPPET:那是 build_body 用的同一張表,
    #    有人從表裡拿掉一格,兩邊會一起瞎掉而 self_test 照樣全綠。改成走**線上
    #    snippet 自己的每一個鍵**,只跳過 API 列為唯讀的;不認得的鍵一律當成
    #    必須帶 ⇒ YouTube 哪天加了新的可寫欄位,這裡是拒寫,不是悄悄清空。
    for k in live_sn:
        if k in _READONLY_SNIPPET:
            continue
        v = live_sn.get(k)
        if v in (None, "", []):
            continue
        if k not in snip:
            bad.append("%s:線上有值(%.40r)但 body 沒帶 ⇒ 會被清空" % (k, v))
        elif k != "description" and snip[k] != v:
            bad.append("%s:值被改了,線上 %.40r → body %.40r" % (k, v, snip[k]))
    if not snip.get("description"):
        bad.append("description 沒帶或是空的")
    return (not bad), bad


def _md5(path):
    import hashlib
    return hashlib.md5(path.read_bytes()).hexdigest()


def verify_mirror(verbose=True):
    """第二份備份在不在、對不對。回 (ok, 訊息)。

    🔴 這是 --apply 的硬前置:唯一一份備份 = 沒有退路。
    """
    if not SNAP.is_dir():
        return False, "找不到原始快照 %s" % SNAP
    src = sorted(x for x in SNAP.glob("*.json"))
    if not src:
        return False, "快照目錄是空的:%s" % SNAP
    if not MIRROR.is_dir():
        return False, ("第二份備份不存在:%s(先複製過去再驗 md5)" % MIRROR)
    bad, miss = [], []
    for f in src:
        g = MIRROR / f.name
        if not g.exists():
            miss.append(f.name)
        elif _md5(f) != _md5(g):
            bad.append(f.name)
    if miss or bad:
        return False, ("第二份備份不完整:缺 %d 檔、md5 不符 %d 檔"
                       % (len(miss), len(bad)))
    if verbose:
        print("第二份備份 ✅ %s —— %d 檔 md5 全數相符" % (MIRROR, len(src)))
    return True, "%d 檔相符" % len(src)


def _snapshot_desc(vid):
    """從改寫前的快照讀原文描述;沒有就回 None。"""
    f = SNAP / ("%s.json" % vid)
    if not f.exists():
        return None
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    sn = d.get("snippet") or d
    return sn.get("description")


def rewrite_mode(args) -> int:
    """把已插入的那**一句**換成新措辭,其餘描述一字不動。

    母體是 DONE 名單(已加過更正的),不是待加名單 —— 兩者是不同集合,拿錯會變成
    「對沒加過的片做改寫」(memory `gate-verification-population`)。
    """
    import daily_publish as dp
    nl = chr(10)
    if not DONE.exists():
        print("[X] 找不到 %s ⇒ 沒有已加更正的名單,改寫模式無事可做" % DONE)
        return 1
    vids = json.loads(DONE.read_text(encoding="utf-8"))
    print("改寫母體:DONE 名單 %d 支(已加過更正的)" % len(vids))
    print("錨:整句逐字取代,出現次數必須恰好 1")
    print("  舊 %r" % _SENT_OLD)
    print("  新 %r" % _SENT_NEW)

    mir_ok, mir_why = verify_mirror()
    if args.apply and not mir_ok:
        print("[X] 拒絕進入 --apply:%s" % mir_why)
        print("    唯一一份備份 = 沒有退路。先把 %s 複製到 %s 再跑。" % (SNAP, MIRROR))
        return 1
    if not mir_ok:
        print("第二份備份 ⚠️ %s(dry-run 可以繼續,--apply 會被擋)" % mir_why)
    print("模式:%s" % ("🔴 APPLY(會寫入 YouTube)" if args.apply
                        else "dry-run(唯讀,不會呼叫 videos.update)"))
    # 🔴 有 8 支常駐 job 會 read-modify-write 同一個描述欄(wF:p1,commit a3994a6f)。
    #    被它們蓋回去 vs YouTube 吐舊快取,在回讀端是同一個畫面 —— 靠這份時間戳
    #    跟 job 的執行時間對齊才分得開。把路徑印出來,回讀的人才找得到它。
    if args.apply:
        print("寫入時間戳:%s(每支落 sent/ok 兩行,逐行 fsync)" % STAMP)
        if STAMP.exists():
            print("  ⚠️ 該檔已存在 %d 行 —— 這次會**接在後面**,不會蓋掉舊紀錄"
                  % len(STAMP.read_text(encoding="utf-8").splitlines()))
    else:
        print("寫入時間戳:dry-run 不落。--apply 時會寫到 %s" % STAMP)
    print(nl, end="")

    yt = dp.get_service()
    bk = ROOT / "STUDIO" / "desc_backup"
    bk.mkdir(exist_ok=True)

    ready, already, refused, missing = [], [], [], []
    quota_stop = False
    pub = {"public": 0, "private": 0, "unlisted": 0, "?": 0}
    pl_kept = pl_seen = written = 0
    for idx, vid in enumerate(vids, 1):
        if args.apply and written >= args.max:
            print("[quota] 達本輪寫入上限 %d,其餘下次續(冪等)" % args.max)
            break
        try:
            r = yt.videos().list(part="snippet,status", id=vid).execute()
        except Exception as exc:  # noqa: BLE001
            print("  [warn] %s videos.list 失敗:%s" % (vid, str(exc)[:100]),
                  file=sys.stderr)
            if _client_side_quota(exc):
                print("[quota] 🔴 中止整輪 —— 是**本機 quota_meter** 擋的"
                      "(YT_QUOTA_ENFORCE / YT_QUOTA_RESERVE),不是 Google 回的 403。"
                      "不要改門檻,先確認今天的配額帳本。", file=sys.stderr)
                quota_stop = True
                break
            if "quota" in str(exc).lower():
                print("[quota] 停止本輪(冪等)", file=sys.stderr)
                break
            missing.append((idx, vid, "videos.list 失敗"))
            continue
        items = r.get("items") or []
        if not items:
            # videos.list 讀不到時不報錯、只是不回傳 ⇒ 必須自己分辨
            missing.append((idx, vid, "videos.list 回空(已刪?權限?)"))
            continue
        sn = items[0]["snippet"]
        priv = ((items[0].get("status") or {}).get("privacyStatus")) or "?"
        pub[priv] = pub.get(priv, 0) + 1
        desc = sn.get("description") or ""

        # (a) 基準比對。🔴 **冪等判斷要排在「基準已過期」之前** ——
        #     否則本工具自己寫過的片,重跑時會被記成「線上與快照不一致(有人改過)」。
        #     那個標籤正是時間戳要拿來分辨「被常駐 job 蓋回去」的那一個,兩種
        #     情況混在一起 ⇒ 回讀時分不出是誰動的,等於把最重要的訊號洗掉。
        #     預設 --max 20、84 支要跑好幾輪 ⇒ 這條路徑**必定**會走到。
        snap = _snapshot_desc(vid)
        if snap is None:
            refused.append((idx, vid, "快照裡沒有這支 ⇒ 沒有基準可比"))
            print("  [%2d/%d] %s  ⛔ 快照缺這支,拒動" % (idx, len(vids), vid))
            continue
        expected_new = (snap.replace(_SENT_OLD, _SENT_NEW, 1)
                        if snap.count(_SENT_OLD) == 1 else None)
        if desc != snap:
            if expected_new is not None and desc == expected_new:
                # 線上已經是「快照換掉那一句」的樣子 ⇒ 這支已被改寫過。
                # 🔴 但「已經是新措辭」不等於「是我們寫的」。要在時間戳檔裡
                #    找得到這支的 sent/ok 才算本工具的成果;找不到就是**不明來源**
                #    ——常駐 job、別人的 session、或 Studio 手動都長這樣 ——
                #    不准算成完成(memory `filter-accepted-is-not-filter-applied`:
                #    「結果對」證不了「是這條路徑做的」)。
                seen, last = _stamped(vid)
                if seen:
                    # 最後一筆只有 sent、沒有 ok ⇒ 上一輪送出後回應遺失(中斷/逾時),
                    # 而線上確實已是新措辭 ⇒ 歸「已完成(回應遺失)」,不是拒動。
                    lost = (last or {}).get("phase") == "sent"
                    already.append((idx, vid))
                    print("  [%2d/%d] %s  ✓ 已是新措辭(本工具寫的%s)"
                          % (idx, len(vids), vid,
                             ",回應遺失" if lost else ""))
                    continue
                refused.append((idx, vid,
                                "線上已是新措辭,但時間戳檔沒有這支的紀錄 ⇒ 不明來源"))
                print("  [%2d/%d] %s  ⛔ 已是新措辭但**不是我們寫的**(時間戳無紀錄)"
                      % (idx, len(vids), vid))
                continue
            refused.append((idx, vid, "線上描述與 09-11 快照不同 ⇒ 基準已過期"))
            print("  [%2d/%d] %s  ⛔ 線上與快照不一致(有人改過),拒動"
                  % (idx, len(vids), vid))
            continue

        try:
            new_desc, o_s, n_s = rewrite_desc(desc)
        except Refuse as exc:
            refused.append((idx, vid, str(exc)))
            print("  [%2d/%d] %s  ⛔ 拒動:%s" % (idx, len(vids), vid, str(exc)[:90]))
            continue
        if new_desc is None:
            already.append((idx, vid))
            continue

        ok, why = invariant_ok(desc, new_desc)
        tag = "  ★必測7" if vid in WATCH7 else ""
        print("  [%2d/%d] %s  %s%s" % (idx, len(vids), vid, priv, tag))
        print("         舊句 %r" % o_s)
        print("         新句 %r" % n_s)
        print("         其餘逐字相同:%s —— %s" % ("是" if ok else "🔴 否", why[:110]))
        print("         長度 %d → %d 字元" % (len(desc), len(new_desc)))

        # 必測 7 支:把播放清單那一行原樣印出來,讓人眼看得到它沒被動
        if PL_PREFIX in desc:
            pl_seen += 1
            a = [x for x in desc.split(nl) if x.startswith(PL_PREFIX)]
            b = [x for x in new_desc.split(nl) if x.startswith(PL_PREFIX)]
            same = a == b
            pl_kept += 1 if same else 0
            print("         播放清單行:%s" % ("原封不動 ✅" if same else "🔴 變了"))
            for x in a:
                print("           舊 %r" % x)
            for x in b:
                print("           新 %r" % x)

        if not ok:
            refused.append((idx, vid, "不變量不成立:" + why))
            print("         ⛔ 拒寫(不變量不成立)")
            continue
        if len(new_desc) > DESC_LIMIT:
            refused.append((idx, vid, "改寫後 %d 字元 > %d" % (len(new_desc), DESC_LIMIT)))
            print("         ⛔ 拒寫:超過 %d ——**不硬截**,硬截會吃掉描述尾巴"
                  % DESC_LIMIT)
            continue
        # 🔴 F1:整包覆寫 —— 從**線上讀回來的 sn** 帶齊所有可寫欄位,只換 description。
        #    刻意排在 `if not args.apply` **之前**:dry-run 也要對 84 支真實 snippet
        #    各檢一次,否則這道檢查只在第一次真的寫入時才第一次跑 —— 那時已經來不及。
        body = build_body(vid, sn, new_desc)
        keep_ok, keep_bad = body_keeps_fields(sn, body)
        print("         body 欄位:%s" % ("帶齊 ✅ " + ",".join(
            k for k in body["snippet"] if k != "description")
            if keep_ok else "🔴 會清掉線上欄位"))
        if not keep_ok:
            refused.append((idx, vid, "body 會清掉線上欄位:" + "; ".join(keep_bad)))
            print("         ⛔ 拒寫:body 少帶線上有值的欄位 ⇒ 會被清空")
            for x in keep_bad:
                print("             %s" % x)
            continue
        ready.append((idx, vid, priv))

        if not args.apply:
            continue

        # 🔴 備份:**不覆蓋** desc_backup/<vid>.json —— 那是第一次插入之前的唯一
        #    一份原始版本,蓋掉等於把退路燒掉。改寫前的另存一檔。
        pre = bk / ("%s.pre_rewrite.json" % vid)
        if pre.exists():
            # 🔴 原本一律拒寫,而這會把「上一輪在 update 途中被中斷」的那一支
            #    永久鎖死:備份已經寫好、update 還沒送出,重跑就再也不動它。
            #    備份的用途是**保住改寫前的原文**;內容與快照逐字相同時,
            #    它已經完成了任務,沿用它不會失去任何退路。
            try:
                pre_desc = (json.loads(pre.read_text(encoding="utf-8"))
                            .get("description") or "")
            except Exception as exc:  # noqa: BLE001
                refused.append((idx, vid, "pre_rewrite 讀不動:%s" % str(exc)[:80]))
                print("         ⛔ 拒寫:%s 讀不動" % pre.name)
                continue
            if pre_desc != snap:
                refused.append((idx, vid,
                                "pre_rewrite 已存在且內容與快照不同 ⇒ 來源不明,不覆蓋"))
                print("         ⛔ 拒寫:%s 已存在且與快照不符" % pre.name)
                continue
            print("         ↻ 沿用既有 %s(內容與快照逐字相同)" % pre.name)
        else:
            pre.write_text(json.dumps(sn, ensure_ascii=False), encoding="utf-8")

        # 🔴 送出時間要在呼叫**之前**就落盤。只在成功之後才記的話，
        #    「送出了但回應丟了」這一種——正好是最危險、也最需要紀錄的
        #    那一種——會完全沒有紀錄，而 YouTube 那邊可能已經寫進去了。
        sent = _now()
        _stamp({"vid": vid, "idx": idx, "phase": "sent", "sent_at": sent,
                "privacy": priv, "old_len": len(desc), "new_len": len(new_desc)})
        try:
            resp = yt.videos().update(part="snippet", body=body).execute()
        except Exception as exc:  # noqa: BLE001
            # 🔴 F4:先分主詞。客戶端配額是在**送出之前**丟的 ⇒ 這支沒被寫入,
            #    狀態是**已知**的(和「送出了但回應丟了」完全不同一件事),
            #    而且要中止整輪 —— 繼續跑只會一支一支撞同一道自家的牆。
            client = _client_side_quota(exc)
            _stamp({"vid": vid, "idx": idx,
                    "phase": "blocked" if client else "error",
                    "by": "本機 quota_meter" if client else "未知",
                    "sent_at": sent, "recv_at": _now(),
                    "error": repr(exc)[:400]})
            if client:
                refused.append((idx, vid,
                                "被本機配額帳本擋下(**未送出**):%s" % str(exc)[:110]))
                print("         ⛔ 本機帳本擋的,不是 Google —— 未送出")
                print("[quota] 🔴 中止整輪 —— 是**本機 quota_meter** 擋的"
                      "(YT_QUOTA_ENFORCE / YT_QUOTA_RESERVE),不是 Google 回的 403。"
                      "不要改門檻,先確認今天的配額帳本。", file=sys.stderr)
                quota_stop = True
                break
            refused.append((idx, vid,
                            "update 拋例外，這支狀態**未知**（可能已寫入）：%s"
                            % repr(exc)[:120]))
            print("         ⛔ update 例外 —— 未知狀態，已落時間戳")
            continue
        recv = _now()
        _stamp({"vid": vid, "idx": idx, "phase": "ok", "sent_at": sent,
                "recv_at": recv, "etag": resp.get("etag"),
                "resp_id": resp.get("id")})
        written += 1
        print("         ✅ 已改寫（送出 %s → 回應 %s）"
              % (sent["tpe"], recv["tpe"]))

    print(nl + "=" * 68)
    rp = len([x for x in ready if x[2] == "public"])
    rv = len([x for x in ready if x[2] == "private"])
    print("可改寫 %d 支(public %d / private %d)" % (len(ready), rp, rv))
    print("已是新措辭 %d  /  拒動 %d  /  取不到 %d" % (len(already), len(refused), len(missing)))
    print("讀到的隱私分布:%s" % ", ".join("%s %d" % (k, v) for k, v in pub.items() if v))
    print("帶播放清單行的 %d 支,其中 %d 支那一行原封不動(必測清單 %d 支)"
          % (pl_seen, pl_kept, len(WATCH7)))
    for lab, rows in (("拒動 / 拒寫", refused), ("取不到", missing)):
        if rows:
            print(nl + "【%s】" % lab)
            for idx, vid, whyx in rows:
                print("  %2d  %s  %s" % (idx, vid, str(whyx)[:150]))
    if args.apply:
        print(nl + "已改寫 %d 支" % written)
        try:
            from ops import log_ops
            log_ops("期間更正改寫", "改寫尾句 %d 支" % written)
        except Exception:  # noqa: BLE001
            pass
    else:
        print(nl + "dry-run:全程沒有呼叫 videos.update,YouTube 上一個字都沒改。")
    if quota_stop:
        print(nl + "🔴 本輪被**本機 quota_meter** 中止(不是 Google)—— 上面的數字只涵蓋中止前的部分")
    return 1 if (refused or missing or pl_kept != pl_seen or quota_stop) else 0


def _parser():
    """參數表拆出來,讓 self_test 能用**同一個** parser 餵 cron 那串 argv。"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max", type=int, default=20)
    ap.add_argument("--rewrite-note", action="store_true",
                    help="把已插入的那一句換成新措辭(其餘一字不動)")
    ap.add_argument("--self-test", action="store_true",
                    help="只跑錨定與不變量的對照,不連網")
    return ap


def main() -> int:
    args = _parser().parse_args()

    route = route_of(args)
    if route == "self_test":
        return self_test()
    if route == "rewrite":
        return rewrite_mode(args)

    import daily_publish as dp
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    rows = _refresh_candidates(rows)
    done = set(json.loads(DONE.read_text(encoding="utf-8"))) if DONE.exists() else set()
    views = _views_map()
    cands = [(s, v) for s, v, _ in rows if v not in done]
    cands.sort(key=lambda sv: -views.get(sv[1], 0))
    print(f"待加更正:{len(cands)} 支(已完成 {len(done)});依近 30 天觀看排序\n")

    yt = dp.get_service()
    bk = ROOT / "STUDIO" / "desc_backup"
    bk.mkdir(exist_ok=True)
    n = 0
    skipped, quota_stop = [], False
    for slug, vid in cands:
        if n >= args.max:
            print(f"[quota] 達本輪上限 {args.max},其餘下次續(冪等)")
            break
        try:
            r = yt.videos().list(part="snippet", id=vid).execute()
            items = r.get("items") or []
            if not items:
                done.add(vid)
                continue
            sn = items[0]["snippet"]
            desc = sn.get("description") or ""
            # 🔴 F5:插入的內容、超長的處置都搬進 insert_desc() ——
            #    舊版在這裡直接 `new_desc[:4990]` 硬截,會從描述**尾巴**吃掉
            #    訂閱連結/播放清單,而且完全沒有訊號。
            try:
                new_desc = insert_desc(desc)
            except Refuse as exc:
                print("     ⛔ 拒寫 %s:%s" % (vid, str(exc)[:110]), file=sys.stderr)
                skipped.append((vid, str(exc)))
                continue
            if new_desc is None:
                done.add(vid)
                continue
            # 🔴 F1:整包覆寫 —— 和改寫路徑共用 build_body / body_keeps_fields。
            #    舊版這裡漏帶 defaultAudioLanguage ⇒ 8 月那次 15 支被 YouTube
            #    重猜成 en-US,推翻 fix_audio_language 兩週的成果。
            #    排在 `if not args.apply` 之前:dry-run 也要檢到。
            body = build_body(vid, sn, new_desc)
            keep_ok, keep_bad = body_keeps_fields(sn, body)
            if not keep_ok:
                print("     ⛔ 拒寫 %s:body 會清掉線上欄位 —— %s"
                      % (vid, "; ".join(keep_bad)[:160]), file=sys.stderr)
                skipped.append((vid, "body 會清掉線上欄位:" + "; ".join(keep_bad)))
                continue
            print(f"  ✏ {slug[:40]} (觀看 {views.get(vid, 0)})")
            if not args.apply:
                n += 1
                continue
            (bk / f"{vid}.json").write_text(json.dumps(sn, ensure_ascii=False), encoding="utf-8")
            yt.videos().update(part="snippet", body=body).execute()
            done.add(vid)
            n += 1
            print("     ✅ 已加更正")
        except Exception as exc:  # noqa: BLE001
            print(f"     [warn] {str(exc)[:120]}", file=sys.stderr)
            if _client_side_quota(exc):
                # 🔴 F4:擋人的是**我們自己的** quota_meter(送出之前就丟),
                #    不是 Google 的 403。主詞要印出來,否則下一個人會去找 Google。
                print("[quota] 🔴 中止整輪 —— 是**本機 quota_meter** 擋的"
                      "(YT_QUOTA_ENFORCE / YT_QUOTA_RESERVE),不是 Google 回的 403。"
                      "不要改門檻,先確認今天的配額帳本。", file=sys.stderr)
                quota_stop = True
                break
            if "quota" in str(exc).lower():
                print("[quota] 停止本輪(冪等,下個配額日接著跑)", file=sys.stderr)
                break

    if args.apply:
        # 🔴 write_text 會**先截斷再寫入**:中途拋例外就留下 0 bytes,而空的
        #    DONE 對下游是合法的「零筆」⇒ 84 支全部會被當成沒做過重跑一遍。
        #    (memory `write-truncates-before-it-fails`:我曾因此把活的 crontab
        #     114 個排程清成 0。)⇒ tmp → 讀回逐字比對 → os.replace。
        import os as _os
        payload = json.dumps(sorted(done))
        tmp = DONE.with_name(DONE.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        if tmp.read_text(encoding="utf-8") != payload:
            print("🔴 DONE 暫存檔回讀不符 —— 不敢 replace,原檔保持不動",
                  file=sys.stderr)
            return 1
        _os.replace(tmp, DONE)
        try:
            from ops import log_ops
            log_ops("期間更正", f"加更正說明 {n} 支(累計 {len(done)})")
        except Exception:  # noqa: BLE001
            pass
    print(f"\n{'已加' if args.apply else '將加'} {n} 支")
    if skipped:
        print("\n【拒寫】%d 支" % len(skipped))
        for vid, whyx in skipped:
            print("  %s  %s" % (vid, str(whyx)[:150]))
    return 1 if (skipped or quota_stop) else 0


if __name__ == "__main__":
    raise SystemExit(main())
