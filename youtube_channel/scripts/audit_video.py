#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_video.py — 【審核部門】發布前自動品管 + 誠信把關。

規則式審核(不需 AI、可無人值守)。PASS 才允許上架；FAIL 隔離並記錄原因。
檢查：①技術(檔案存在/不過小/有影音軌/片長合理/Shorts≤3分鐘平台上限) ②誠信(禁語：保證賺、
穩賺不賠等) ③合規(有標題、有風險聲明)。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = PROJECT_ROOT / "output"

# 誠信禁語（誇大/保證型，違反誠信鐵則）
BANNED = [
    "保證賺", "保證獲利", "保證收益", "穩賺不賠", "穩賺", "必賺", "包賺",
    "零風險", "一定賺", "一定獲利", "穩定獲利", "躺著就能賺", "閉著眼睛賺",
    "穩定月收", "保本保息", "穩定報酬率",
]

# 否定詞：禁語前若有這些字，視為誠實聲明（如「不保證收益」）而非違規
NEG_CHARS = "不沒別非勿未拒避免絕毋≠"   # ≠:2026-08-11 實測「機構進場≠穩賺」是標準否定寫法
# 破除/反問語境標記：同一句內出現這些詞(如「打臉穩賺神話」「你以為網格穩賺?」)或緊接問號，
# 屬誠實破除，非違規。2026-07 修：舊版只看禁語前 8 字/後 2 字的窄窗，「打臉穩賺神話」這種
# 破除詞在禁語*前*超出窗口、或神話/騙局這類破除詞接在禁語*後*都會漏判，誤擋「拆穿穩賺神話」
# 這類避雷片標題——改成掃整句(標點斷句)才不漏。
DEBUNK = ("以為", "迷思", "真的", "真能", "真會", "別信", "別再", "騙", "假象", "謊",
          "難道", "憑什麼", "怎麼可能", "拆穿", "打臉", "揭穿", "神話", "騙局",
          # 2026-08-11 補:南亞1303「揭露『長期投資必賺』背後的殘酷真相」被誤擋——
          # 「揭露/真相」是本頻道避雷片的招牌句式,和「揭穿/拆穿」同義卻不在表上。
          "揭露", "真相",
          # 2026-07-26 補「流言終結者」franchise 框迷思詞:引用被驗的信仰標籤(「崩盤抄底穩賺
          # (對照信仰:…)」)、「本集要終結的流言:…穩賺不賠」——這些是**被拆的迷思名**非本片保證。
          # 兩詞天生只出現在破除語境(對照信仰=被驗的對照假說、流言=待終結的傳言),不會出現在真喊單句。
          "對照信仰", "流言",
          # 2026-08-11 補「引述他人信念」語型。實測 08-10 上架被攔 41 支,
          # 「含誇大/保證禁語」佔 17 支(第二大原因),抽查三支**全部是誤殺**:
          #   合晶:「抱持著『長期持有穩賺不賠』**觀念**的投資人感到震驚」
          #   晶技:「高殖利率,是否就代表穩賺不賠?**這可不一定**」
          #   宜鼎:「很多人…覺得長期投資穩賺不賠…**但真實情況**往往比你想得更複雜」
          # 這三種都是「先引述迷思、再打掉」的標準破除句型,但用的轉折詞
          # (觀念/可不一定/真實情況/往往)全都不在原詞表裡 → 被判成本片在宣稱。
          # ⚠️ 這些詞單獨看很中性,之所以安全是因為判定條件是**同句內同時出現禁語**——
          #    真喊單句(「跟著我穩賺」)不會同句出現「這可不一定」這種自我否定。
          "觀念", "觀唸", "可不一定", "不一定", "真實情況", "往往", "事實上",
          "並不能", "不代表",
          # 2026-08-11 三修:「號稱/宣稱/所謂/自稱」跟「大家都/認為」語言性質不同——
          # 這批詞天生帶懷疑距離(沒有人喊單會寫「跟著我,號稱穩賺」),降級成 QUOTE_MARKERS
          # 後「網格交易號稱穩賺不賠?」這種避雷 hook 被回頭誤殺。放回無條件破除詞。
          "號稱", "宣稱", "所謂", "自稱")
# 引述詞:「大家都在說X」「擁護者認為X」——只證明**在引用別人的說法**,不證明本片在破除它。
# 喊單片一樣會用(「大家都說這檔穩賺,快上車」),所以不能放進 DEBUNK 無條件放行;
# 必須同句或下一句出現轉折/反駁(REBUT)才算破除語境。
# 「都說/號稱/很多人」這批原本躺在 DEBUNK 裡,有同樣的漏洞,一併移過來收緊。
QUOTE_MARKERS = ("很多人", "多數人", "常聽到", "都說",
                 "大家都", "大家常", "擁護者", "認為", "有人說", "聽說")
REBUT = ("但", "然而", "其實", "事實", "回測", "資料", "數據", "未必", "並不",
         "不一定", "不是這樣", "真相", "揭露", "殘酷", "錯", "迷思", "驗證")
QUESTION = "？?嗎吗"
_SENT_SPLIT_RE = re.compile(r"[。！？!?\n]")


def find_fabricated_stats(blob: str) -> list:
    """回傳「產線不可能算得出來」的統計宣稱。空 = 乾淨。

    ## 為什麼這條是零誤判(2026-08-17 實測建立)
    掃過全部 5 個事實庫(backtest_cards / tw_facts_computed / tw_stock_facts /
    tw_universe_facts / stock_checkup_facts)共 **3,887 組事實,「機率」「勝率」各 0 組**。
    產線的能力是「這檔股票這段期間的含息還原報酬/回撤/套牢」,從來沒有、也沒有工具去算
    「機構減持後 30 天有 47% 機率暴跌」這種條件機率。所以旁白裡出現機率類數字,
    **必然是 LLM 編的**——不是抓可疑,是抓不可能。

    掃描已發布片抓到 30 支中招,樣本:
      「機構減持後30天,比特幣有47%機率暴跌超過20%」
      「假設你在前三次暴跌後進場,有七成機率會再跌33%」
      「歷史上熱錢湧入後三個月,有九成機率會回撥超過百分之二十」
      最嚴重的一支用編造的「回測顯示能少賠58%」直接推銷聯盟商品(網格機器人)。

    ## 為什麼 fact_source_guard 抓不到
    它把數字拿去比對**整個**事實庫,任何兩三位數都「找得到來源」(47 這個數字
    在別支股票的回撤裡存在),而「七成」「九成」是中文數詞,根本沒被當數字。
    這是 memory `yt-integrity-methodology-claims-blindspot` 記的同一個盲區:
    守門只看數字有沒有出處,對「宣稱有研究支持」這種**方法論宣稱**結構上看不見。

    ## 假借權威
    「量化資料顯示」「研究顯示」「統計顯示」「學術研究」——本頻道做的是回測,
    不是研究。講「回測顯示」是誠實的(有 fact_key 溯源),講「研究顯示」是借別人的
    權威講自己沒做過的事。所以 ALLOW 只留「回測顯示/實測」。

    引述語境放行:「有人說有八成機率,但回測打臉」是破除,不是宣稱。
    """
    # 放行語境。除了「引述別人的說法」,還必須放行**教學假設**——這是實測(2026-08-17)
    # 才發現的誤殺:破除型長片整支都在講「假設你看到一個宣稱勝率 90% 的策略…」,
    # 那是要打臉的對象,不是自己的宣稱。而破除型正是本頻道最有價值的內容類型
    # (流言終結者 franchise 全靠它),閘門把它殺光等於閹掉主力。
    # 反過來「量化回測顯示,你有九成機率會虧掉兩成本金」沒有任何假設詞——那才是宣稱。
    QUOTE = ("號稱", "宣稱", "有人說", "謠傳", "迷思", "都在說", "常聽到",
             "傳言", "以為", "騙你", "話術", "看起來像", "他們說",
             "假設", "如果", "舉例", "即使", "就算", "假如", "你相信嗎", "真的嗎")
    PATS = [
        r"[\d.]+\s*%\s*(?:的)?機率", r"[零一二三四五六七八九十]成(?:的)?機率",
        r"機率(?:高達|超過|接近|約)?\s*[\d.]+\s*%", r"[\d.]+\s*成(?:的)?機(?:率|會)",
        r"勝率(?:高達|約|超過)?\s*[\d.]+\s*%",
        r"量化資料顯示", r"研究顯示", r"統計顯示", r"學術研究", r"實證研究(?:顯示|指出)",
        r"行為金融學[^。,，]{0,12}(?:顯示|指出|證明)",
        # 夏普比率:全部事實庫 0 處(只算卡瑪比率)。所以任何具體夏普**數值**都是編的
        # ——「聯詠的夏普比率只有零點八五,遠低於0050的一點二一」實測是憑空生的。
        # 只擋帶數值的宣稱,單純講夏普概念不擋。
        r"夏普(?:比率|值)?[^。,，]{0,6}[零一二三四五六七八九十點]{2,}",
        r"夏普(?:比率|值)?[^。,，]{0,6}[\d]+\.?\d*",
        # 投資人行為統計:事實庫「散戶/認賠」0 處。產線只有價格與財報資料,
        # 沒有任何投資人行為樣本——「散戶平均會在下跌的第十八天認賠」是編的。
        r"散戶[^。,，]{0,8}平均[^。,，]{0,10}第[零一二三四五六七八九十\d]+天",
        r"[零一二三四五六七八九十\d]+\s*成(?:的)?(?:散戶|投資人|人)[^。,，]{0,10}(?:認賠|殺出|賣出|虧)",
    ]
    out = []
    for pat in PATS:
        for m in re.finditer(pat, blob or ""):
            # 句界:往前後找標點,判斷是不是引述/破除語境
            s = max(0, blob.rfind("。", 0, m.start()) + 1)
            e = blob.find("。", m.end())
            sent = blob[s:(e if e > 0 else m.end() + 40)]
            if any(q in sent for q in QUOTE):
                continue
            frag = m.group(0)
            if frag not in out:
                out.append(frag)
    return out


def find_banned_hits(blob: str) -> list:
    """回傳 blob 裡「當真宣稱在用」的禁語清單(破除/否定/反問語境不算)。

    2026-08-11 從 audit() 的巢狀函式抽出來:之前每輪驗證都在測試腳本裡**重刻**這段
    邏輯,重刻版和正式版走岔了兩次(整句掃 NEG 放行真喊單、右側掃 ？ 放行假反問),
    測過=假象。抽成 module-level 之後,測試 import 的就是產線在跑的同一份。

    語境放行規則(按序):
      ①窄窗:前 8 字有否定字、或後 2 字有問號/嗎 —— 歷史行為,保留。
      ②同句左側(禁語前)有否定字:「並不能代表它是一檔穩賺不賠的股票」。
        ⚠️ 只掃左側:禁語「穩賺不賠」自含「不」,掃整句=無條件放行。
      ③同句右側(禁語後)有疑問詞「嗎/吗」:「你還會覺得穩賺不賠嗎?」。
        ⚠️ 只認嗎/吗,**不認光禿問號**——「這檔穩賺不賠?我跟你保證翻倍」
        是假反問真喊單,光禿問號要走⑥(下一句必須有破除詞)才放行。
      ④同句有破除詞(DEBUNK):「打臉穩賺神話」。
      ⑤同句有引述詞(QUOTE_MARKERS)**且**同句或下一句有轉折反駁(REBUT):
        「大家都在說X穩賺不賠,但回測顯示…」。引述詞單獨出現不放行
        (喊單也會寫「大家都說這檔穩賺」)。
      ⑥本句以問號結尾且下一句有破除詞:「是否代表穩賺不賠?這可不一定…」。
      ⑦「穩定獲利」緊鄰「公司/企業/本業」=財務描述非收益承諾:
        「穩定的毛利率是公司穩定獲利的重要基礎」。
    """
    def _ok_context(i, b):
        # 子字串碰撞(2026-08-11):「歸零風險更高」是「歸零+風險」,不是「零風險」宣稱。
        if b == "零風險" and blob[max(0, i - 1):i] == "歸":
            return True
        pre = blob[max(0, i - 8):i]
        post = blob[i + len(b): i + len(b) + 2]
        if any(n in pre for n in NEG_CHARS):       # ① 不/沒保證…
            return True
        if any(q in post for q in QUESTION):       # ① 穩賺？ 反問
            return True
        _l = 0
        for _m in _SENT_SPLIT_RE.finditer(blob[:i]):
            _l = _m.end()
        _rm = _SENT_SPLIT_RE.search(blob, i + len(b))
        _left = blob[_l:i]                                          # 同句、禁語之前
        _right = blob[i + len(b): _rm.start() if _rm else len(blob)]  # 同句、禁語之後
        sentence = _left + b + _right
        if any(n in _left for n in NEG_CHARS):     # ②
            return True
        if "嗎" in _right or "吗" in _right:        # ③
            return True
        # ③b 二選一問句(2026-08-11):「網格機器人穩賺**還是**會被套牢?」——「A還是B?」
        # 是開放疑問不是宣稱。限定:同句右側有「還是」**且**句尾是問號才放行。
        if "還是" in _right and _rm and _rm.group() in "？?":
            return True
        if any(dk in sentence for dk in DEBUNK):   # ④
            return True
        nxt = ""
        if _rm:
            _nm = _SENT_SPLIT_RE.search(blob, _rm.end())
            nxt = blob[_rm.end(): _nm.start() if _nm else len(blob)]
        if any(qm in sentence for qm in QUOTE_MARKERS):   # ⑤
            if any(rb in sentence for rb in REBUT) or any(rb in nxt for rb in REBUT):
                return True
        if _rm and _rm.group() in "？?":            # ⑥
            if any(dk in nxt for dk in DEBUNK):
                return True
        if b == "穩定獲利" and _left[-6:] and any(   # ⑦
                w in _left[-6:] for w in ("公司", "企業", "本業")):
            return True
        return False

    hits = []
    for b in BANNED:
        start = 0
        while True:
            i = blob.find(b, start)
            if i == -1:
                break
            if not _ok_context(i, b):
                hits.append(b)  # 真正當作宣稱在用 → 違規
                break
            start = i + len(b)
    return hits


def _ffmpeg_exe() -> str:
    """robust ffmpeg 解析(對齊 render_ffmpeg._ffmpeg_exe):imageio_ffmpeg 模組缺失時
    退回環境變數或系統 PATH 的 ffmpeg——**不可**讓「探測工具找不到」被誤當「影片壞掉」。
    2026-07-25 血案:系統 python 沒裝 imageio_ffmpeg → 舊 _probe 直接 except 回 (0,False,False)
    → 一支剛渲染好的合格 27.4MB 成片被判『0s/無軌』刪除。fail-DELETE-closed 會靜默摧毀正式產出。"""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        import os
        return os.environ.get("IMAGEIO_FFMPEG_EXE") or "ffmpeg"


def _probe(mp4: Path):
    try:
        ff = _ffmpeg_exe()
        out = subprocess.run([ff, "-i", str(mp4)], capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        txt = out.stderr or ""
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", txt)
        dur = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) if m else 0.0
        return dur, ("Video:" in txt), ("Audio:" in txt)
    except Exception:
        return 0.0, False, False


def _frame_jitter(mp4: Path, dur: float, points: int = 5):
    """整幅位移(畫面抖動)偵測。回傳 (命中數, 檢查幀對數);工具缺失回 (-1, 0) = 不判定。

    ⚠️ 不可用絕對次數當判準:抖動只在 zoom 值跨過整數邊界時發生,同一支片有些段落抖、
    有些不抖,採樣點落在哪決定看不看得到(實測台燿 3/15、勤誠 0/15,兩支都是修復前渲的)。
    故回傳**比率**,由呼叫端依實測分佈定門檻。

    ## 為什麼有這支(2026-08-17,兩位真實觀眾同時回報「畫面會一直抖」)
    渲染端 zoompan 的 x/y 運算含 `iw/zoom/2`,zoom 隨時間變動時整數取整讓**整幅畫面**
    每隔幾幀位移 1~2 px。逐幀量測坐實:同段 12 幀裡 3 次跳動、其中一次整幅位移 2px。
    根因已修(拿掉連續運鏡),本函式是**防回歸**——以後誰再加運鏡,發布前就會被擋。

    ## 判準:為什麼「位移對齊」能區分抖動與正常內容變化
    換卡、字幕換句、動畫都會讓幀間差異變大,但那是**局部**變化,把前一幀整幅平移
    幾像素**不會**讓差異下降。只有整幅位移才會:平移回去後兩幀幾乎重合。
    故條件是「差異夠大」且「平移後差異砍半以上」——內容變化過不了第二關。

    取中央 480x480 原解析度切片(不縮放):1080p 縮到 320 寬時 2px 位移只剩 0.6px 會被抹掉,
    抖動偵測**不能降解析度**。
    """
    try:
        import numpy as np
    except Exception:  # noqa: BLE001
        return -1, 0
    ff = _ffmpeg_exe()
    W = 480
    hits = 0
    pairs = 0
    for i in range(points):
        t = dur * (0.15 + 0.7 * i / max(1, points - 1))
        if t < 4:
            continue
        try:
            out = subprocess.run(
                [ff, "-v", "quiet", "-ss", f"{t:.2f}", "-i", str(mp4), "-frames:v", "14",
                 "-vf", f"crop={W}:{W}:(iw-{W})/2:(ih-{W})/2,format=gray",
                 "-f", "rawvideo", "-"], capture_output=True, timeout=90).stdout
        except Exception:  # noqa: BLE001
            continue
        n = len(out) // (W * W)
        if n < 3:
            continue
        fr = [np.frombuffer(out[i * W * W:(i + 1) * W * W], dtype=np.uint8)
                .reshape(W, W).astype(float) for i in range(n)]
        for a, b in zip(fr, fr[1:]):
            pairs += 1
            base = float(np.abs(a - b).mean())
            if base < 1.0:          # 幾乎靜止 = 正常
                continue
            best = base
            for ax in (0, 1):
                for s in (-2, -1, 1, 2):
                    best = min(best, float(np.abs(np.roll(a, s, axis=ax) - b).mean()))
            # 判準用**補償後的絕對殘差**,不是相對降幅。實測分佈(base→best):
            #   會抖的片: 5.10→0.18、7.14→0.22   ← 純位移,補償後幾乎完全重合
            #   內容變化: 2.04→2.04、2.13→2.13   ← 補償無效
            #   重渲後的: 0.00→0.00 全部          ← 乾淨
            # 相對降幅(best < base*0.5)會把 b-roll 的鏡頭平移一起算進來——那是真實影片
            # 素材在動,場景同時在變,補償後殘差仍大;絕對值判準天然把它排除。
            if best <= 0.5:
                hits += 1
    return hits, pairs


def audit(slug: str):
    """回傳 (ok: bool, reasons: list[str])。reasons 空 = PASS。"""
    reasons = []
    is_short = slug.startswith("S_")
    mp4 = OUTPUT / f"{slug}.mp4"
    mp3 = OUTPUT / f"{slug}.mp3"
    voice = OUTPUT / f"{slug}.voice.txt"
    md = OUTPUT / f"{slug}.md"

    # ① 技術
    if not mp4.exists():
        return False, ["mp4 不存在"]
    size = mp4.stat().st_size
    if size < (150 * 1024 if is_short else 1024 * 1024):
        reasons.append(f"檔案過小（{size // 1024}KB），疑似損壞")
    dur, has_v, has_a = _probe(mp4)
    if dur < 5:
        reasons.append(f"片長過短（{dur:.0f}s）")
    # 🔴 2026-07-30 這條原本是 `dur > 65` + 訊息「Shorts 超過 60 秒」,兩個問題:
    #   ①閾值與訊息不一致(65 vs 60),看訊息會誤判成平台規則。
    #   ②**60 秒這個上限早就過期了**:YouTube Shorts 自 2024-10 起放寬到 **3 分鐘**。
    #     65~68 秒的直式片是完全合法的 Short,YouTube 照樣當 Short 推。
    # 後果不小:quality_score.DEDUCT 對這條硬扣 **18 分**,實測有 2 支底分 86／90 的片
    # 被扣成 68／72,卡死在門檻 75 下不能發——用一個不存在的違規擋掉兩支好片。
    # 現在改成真實的平台上限(留一點探測誤差餘裕)。超過 3 分鐘才是真違規:
    # 那種長度 YouTube 不會當 Short,#Shorts 標籤形同虛設,-18 分是應該的。
    # ⚠️ 這個改動會讓**更多**片通過,方向上是紅旗——所以講清楚為什麼安全:
    #    它修的是一個**過期的事實**,不是放寬安全閘。誠信類閘門(禁語等)完全沒動。
    #    生成端的 30-45 秒偏好(produce_batch 的甜蜜點)也沒動,那是表現偏好、不是硬傷。
    if is_short and dur > 185:
        reasons.append(f"Shorts 超過 3 分鐘上限（{dur:.0f}s）— YouTube 不會當 Short 推")
    if not has_v:
        reasons.append("無視訊軌")
    if not has_a:
        reasons.append("無音軌")

    # ①b 旁白截斷檢查(P0 止血 2026-07-13)：發布前最後一道關卡，不論上游哪條渲染路徑/是否
    # 雲端 code drift 都在這裡兜底攔下——04_0056 事故(旁白218.9s/成品僅61.7s)當時完全沒有
    # 任何一道 gate 比對過 mp4 與旁白 mp3 的長度，結果直接發布到 YouTube。
    # ratio < 0.9 = 疑似截斷(旁白沒剪完就發布)；fail-closed，不放行。
    if mp3.exists() and dur > 0:
        adur, _, _ = _probe(mp3)
        if adur > 0:
            ratio = dur / adur
            if ratio < 0.9:
                reasons.append(f"旁白疑似截斷（成品{dur:.1f}s / 旁白{adur:.1f}s，比值{ratio:.2f}<0.9）")
            # ①c mp3 本身截斷(2026-08-11 實測抓到的盲區):TTS 中途被砍留下 302s 殘骸
            # 配 2388 字的稿(7.9字/秒)。上面的比值檢查抓不到——殘骸 mp3 渲出的 mp4 兩者
            # 長度一致(ratio=1.0)照樣放行,觀眾聽到旁白講到一半戛然而止。
            # 用語速判:中文旁白正常 4~5.5 字/秒(edge +12%/kokoro 實測),>6.5=稿比音長=截斷。
            # 產線端 _speech_rate_sane 只在 produce_batch 生產時跑,重渲路徑(hybrid_render
            # 拿既有 mp3)完全繞過——這裡是發布前最後兜底。fail-closed。
            if voice.exists():
                try:
                    _cjk = len(re.findall(r"[一-鿿]", voice.read_text(encoding="utf-8")))
                    if _cjk > 200 and _cjk / adur > 6.5:
                        reasons.append(f"配音疑似截斷（{_cjk}字/{adur:.0f}s={_cjk / adur:.1f}字/秒>6.5，稿比音長）")
                except Exception:  # noqa: BLE001
                    pass

    # ①d 空殼旁白(2026-08-12 實測抓到):時事片的無憑據數字被剝掉後,整支只剩 77 字
    # 骨架——「升息機率高達 (數字沒了)」+ loop 鉤 + 訂閱 CTA,沒有任何內容。
    # 上游哪條路徑產的都一樣在這裡兜底:Shorts 旁白 <120 中文字=空殼,fail-closed。
    # (正常 Shorts 30-45 秒 ≈ 200-350 字;長片有 A4 長度 gate 這裡不重複管。)
    if is_short and voice.exists():
        _vtext = voice.read_text(encoding="utf-8")
        _vn = len(re.findall(r"[一-鿿]", _vtext))
        if _vn < 120:   # 含 0 字:voice.txt 存在但整檔空白=更徹底的空殼,不可放過
            reasons.append(f"旁白過短({_vn}字)疑似空殼——內容被剝除後只剩骨架")

    # ①e 畫面抖動 + ①f 字幕時間軸(2026-08-17,兩位真實觀眾同時回報)
    # 這兩個 bug 在產線活了很久,**所有內部指標都是綠的**:品質分、完播率、audit 全過,
    # 因為它們量的是「檔案屬性」不是「觀眾看到的畫面」。最後是觀眾在留言區告訴我們的。
    # 教訓落地成閘門:把「只有人眼看得到」的兩件事變成機器每支都查。
    if has_v and dur > 10:
        _j, _tot = _frame_jitter(mp4, dur)
        # 門檻 = 1。定門檻的實測依據:**33 支重渲後的片全掃,命中數全部是 0**(零誤判),
        # 而未修的舊片抓得到 1~2 處。抖動是間歇的(zoom 跨整數邊界才跳),即使每點抽 14 幀
        # ×6 點 = 78 幀對也只會踩到一兩次——所以門檻不能設高,設高就等於沒有這道閘。
        # 反過來說,因為修好的片是**絕對零**,一次命中就足以判定有問題。
        # ⚠️ 誠實記下限制:這道閘門能抓「整支片都在抖」的回歸,但對極稀疏的個案仍可能漏抓
        # (台燿那支是觀眾親口回報會抖的,78 幀對也只踩到 1 次)。它是安全網不是保證。
        # -1 = 工具缺失,不判定,不可當壞片。
        if _j >= 1 and _tot > 0:
            reasons.append(f"畫面整幅位移 {_j}/{_tot} 幀對(抖動)——檢查渲染端 zoompan 的 x/y 運算")
    # ①f 字幕時間軸:旁白 3 秒片頭後才開始,字幕若沒加片頭位移就全片系統性早 3 秒。
    # 已發生過:上傳的 CC 用 mp4 總長度分配 + 零位移,越後面偏差越大。確定性檢查,零誤判。
    _wt = OUTPUT / f"{slug}.wordtimes.json"
    if _wt.exists() and dur > 0:
        try:
            import json as _json
            _d = _json.loads(_wt.read_text(encoding="utf-8"))
            _end = max((float(w.get("t", 0)) + float(w.get("d", 0))) for w in _d) if _d else 0.0
            from make_video import INTRO_DURATION as _INTRO
            if _end > 0 and (_end + _INTRO) > dur * 1.02:
                reasons.append(f"字幕時間軸超出影片({_end + _INTRO:.1f}s > {dur:.1f}s)——旁白/成品長度不一致")
        except Exception:  # noqa: BLE001
            pass

    # ② 誠信禁語（辨識否定詞，避免把「不保證收益」這種誠實聲明誤判）
    blob = ""
    if voice.exists():
        blob += voice.read_text(encoding="utf-8")
    if md.exists():
        blob += "\n" + md.read_text(encoding="utf-8")
    # 判定邏輯抽到 module-level find_banned_hits(),讓測試能 import 產線同一份;
    # 語境放行規則與歷次血案全記在該函式 docstring。
    hits = find_banned_hits(blob)
    if hits:
        reasons.append("含誇大/保證禁語（非破除語境）：" + "、".join(hits))
    # ②b 編造統計(2026-08-17):事實庫 3,887 組事實裡機率/勝率 0 組——產線算不出這種數字,
    # 出現就是編的。fail-closed。詳見 find_fabricated_stats docstring。
    fab = find_fabricated_stats(blob)
    if fab:
        reasons.append("含產線算不出的統計宣稱（機率/研究）：" + "、".join(fab[:4]))

    # ③ 合規
    if md.exists():
        mdt = md.read_text(encoding="utf-8")
        first = mdt.splitlines()[0] if mdt.splitlines() else ""
        if "🎬" not in first and not first.startswith("# "):
            reasons.append("缺影片標題")
        if ("風險" not in mdt) and ("不構成投資建議" not in mdt):
            reasons.append("缺風險聲明")
    else:
        reasons.append(".md 腳本不存在")

    return (len(reasons) == 0), reasons


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: audit_video.py <slug>")
        return 2
    slug = sys.argv[1]
    ok, reasons = audit(slug)
    print(("PASS " if ok else "FAIL ") + slug)
    for r in reasons:
        print("  - " + r)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
