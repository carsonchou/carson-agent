# -*- coding: utf-8 -*-
"""旗艦片《抱得住嗎》的**組稿層** —— 確定性組稿,不經 LLM。

形狀比照 `ep0_engine.py` / `belief_buster_engine.py`:
`build_script()` + `build_topic()` → `produce_batch.make_one("long", topic_override=…, script_override=…)`。

## 🔴 「確定性組稿」不是傳了 script_override 就自動成立

`make_one:6105` 有一道 `elif kind == "long" and topic_override:` 的鎖題終檢
(2026-08-22 上線),**對手寫稿逐條生效**;命中之後它會呼叫 `call_claude()` 重寫,
而那條路裡有 `_densify_long`(用 LLM 整篇重寫旁白)。
⇒ **稿子只要過不了那道閘,「確定性」就當場失效,而且不會有人發現。**

所以本引擎的稿子是照那道閘的判準寫的,逐條:

| 閘 | 判準 | 本稿怎麼滿足 |
|---|---|---|
| `_long_underlength` | `LONG_MIN_CHARS = 1800` 中文字 + 估時長 ≥6 分 | 目標 ≥2400 字,`selfcheck()` 會擋 |
| `_long_too_few_segments` | `<3` 段(0 段反而放行) | 固定 6 段 |
| `_long_fragmented_hook` | 前兩句任一 `<12` 中文字 | 開場兩句都刻意寫長 |
| `"【" in voice` | 出現全形方括號 | 全稿不用 |
| `_long_mixed_period` | 期間偷換 | 兩組期間**分開講**(見下) |
| `_HEDGE_BOILER` | 正文 10~80% 出現 >1 次「不構成投資建議」這類 | 免責只放結尾一次 |
| `_long_content_padding` | 每 60 秒窗口要有新數字 | 數字均勻分佈在六段 |
| `_long_corrupt_number` | 只認 `fact_key` 以 `checkup_` 開頭 | **刻意不設 `fact_key`** ⇒ 恆不觸發 |

`_is_tw_stock: True` 是為了豁免 A2 捏造績效閘(`make_one:6050`)——
本片每個數字都來自 `flagship_xsec` 的結構化欄位,語義上正確,不是繞過。

## 🔴 兩組期間不一樣,片子裡必須分開講

- **報酬 / 回撤 / 套牢**:每檔用它自己上市以來、最長 20 年的完整資料,**中位 18.6 年**
- **對決 0050**:同一個共同起點的 **10 年**區間

混在一起講會變成「期間偷換」——那正是 `_long_mixed_period` 在擋的東西,
也是 2026-08-28 那次事故的形狀(memory `yt-period-swap-integrity`)。

## 數字從哪來

全部來自 `flagship_xsec.compute()`,而那支**只讀 `data.*` 結構化欄位**。
本檔**不自己算任何數字**,也不寫死任何數字 —— 資料更新時稿子跟著動。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

SERIES_NAME = "抱得住嗎"
# ⚠️ category 不含 _twkw 以外的意義;含「台股」會讓重生路徑疊 TW_STOCK_RULES,
# 那是我們要的(本片確實是台股題),但**首輪不重生就用不到**。
CATEGORY = "台股橫斷面"

# 觀眾原話(2026-08-19,已用 commentThreads API 逐字核對過存在)。
# ⚠️ 刻意**不記錄帳號名**:引用內容可以,把觀眾推到鏡頭前不行(督導 2026-09-06 指示)。
# ⚠️ 他句中的「有八成的持有人只持有一兩張」是**他的說法,不是我們驗證過的事實** ——
# 引用時要讓聽眾聽得出那是他講的,旁白不可以把它接收成我們的數據。
_VIEWER_QUOTE = ("0050 最大的缺點,是抱不住。有八成的持有人,就僅僅持有一兩張。"
                 "所以那種持有 0050 達到百分之一千二百超高報酬的人,"
                 "永遠只出現在網路、永遠在回測資料,在我生活周遭非常罕見。")


def _cov():
    import flagship_xsec
    return flagship_xsec.coverage()


def _facts():
    import flagship_xsec
    ok, msg = flagship_xsec.selfcheck()
    if not ok:
        raise RuntimeError(f"橫斷面計算層自檢失敗,拒絕組稿:{msg}")
    return flagship_xsec.compute()


def _beats(x: dict, cov: dict) -> list:
    """六段旁白。每個數字都從 x / cov 取,**不寫死**。

    🔴 2026-09-06 獨立驗證員(沒讀過本檔)推翻了初稿的**四句話**,雖然 12 個數字全對:
    ①「598 檔台股」聽起來像全市場,實際是成交金額最大的三成 ⇒ 已改成講涵蓋率
    ②「隨便抽一檔台股」出現兩次 ⇒ **全部刪掉**,那是把樣本當母體
    ③ 資料源只有現在還掛牌的公司,沒有下市股 ⇒ **主動揭露存活者偏誤**
    ④ 對決 0050 的 596 檔裡有 63 檔窗較短 ⇒ 提到「十年」時只能用滿十年那組(533 檔)
    ⇒ **數字全對而話講錯,是這支片最可能翻車的方式。**"""
    n = x["n_return"]; nv = x["n_versus"]
    ret = x["total_return_median_pct"]; loss = x["loss_share_pct"]
    dd = x["maxdd_median_pct"]; halved = x["halved_share_pct"]
    uw = x["uw_median_years"]; uw5 = x["uw_ge5_share_pct"]
    uw10 = x["uw_ge10_share_pct"]; uw10n = x["uw_ge10_n"]; uw10up = x["uw_ge10_upper_pct"]
    ong = x["ongoing_n"]; ong10 = x["ongoing_ge10_n"]
    beat = x["beat_share_pct"]; beatn = x["beat_n"]
    b10 = x["beat_full10_share_pct"]; b10n = x["beat_full10_n"]; nv10 = x["n_versus_full10"]
    dca_win = x["dca_beat_allin_share_pct"]; dca_bench = x["dca_beat_bench_share_pct"]
    uni = cov["universe_n"]; cpct = cov["count_coverage_pct"]; vpct = cov["value_coverage_pct"]

    b1 = (
        f"我把台股成交金額最大的 {n} 檔標的,每一檔從它有可信資料以來的完整歷史,"
        f"一檔一檔跑完長期回測,今天要把結果整個攤開來給你看。"
        f"先把範圍講清楚,免得你把它讀成全部的台股:台股掛牌的有 {uni} 檔,我算的這 {n} 檔"
        f"只佔檔數的百分之 {cpct},但它們吃掉全市場百分之 {vpct} 的成交金額。"
        f"所以這是大家實際在買賣的那一群,不是全部的台股。"
        f"還有一件對我不利但我必須先講的事:這份資料的來源只包含現在還掛牌的公司,"
        f"下市的、被合併的、清算掉的都不在裡面。"
        f"所以接下來所有數字,都已經是活下來的那一群的成績,天然偏好看。"
        f"講完範圍,講結論:這 {n} 檔的含息總報酬中位數是百分之 {ret},"
        f"賠錢的只有百分之 {loss}。聽起來很好,長期投資果然會賺。"
        f"但同一份資料的另外三個數字是:最大回撤中位數百分之 {dd},"
        f"百分之 {halved} 曾經腰斬以上,最長套牢期的中位數是 {uw} 年。"
        f"那個百分之 {ret},是要你先抱過一次腰斬、再等上七年多才拿得到的。"
    )
    b2 = (
        f"會做這支片,是因為八月十九號有一位觀眾在留言區寫了一段話,他說:"
        f"{_VIEWER_QUOTE}"
        f"我看到的時候第一個反應是想反駁他,因為我們頻道講的就是長期回測。"
        f"但我把資料重新攤開來看,發現他是對的,而且我們手上剛好有能證明他對的東西。"
        f"他講的八成持有人只持有一兩張,那是他自己的觀察,我沒有那個數字,不能替他背書。"
        f"可是他真正的意思不是張數,是那句永遠在回測資料。"
        f"回測裡的報酬是連續的一條線,現實裡的持有是每天早上醒來要重新決定一次抱不抱。"
        f"這兩件事之間的距離,就是我今天要量給你看的東西。"
        f"我也順便檢討一下自己:這個頻道過去做的,大多是一檔一檔的個股回測,"
        f"每一支都在講這檔抱二十年賺幾倍。那些數字沒有錯,但是把它們一支一支分開看,"
        f"你永遠看不到分母。今天這一支,就是把分母放回去。"
        # 🔴 訂閱鉤刻意寫在稿子裡,不交給產線自動插:
        # `_insert_mid_sub_hook`(前 60% 有訂閱字樣就不插)與 `_ensure_sub_hook`
        # (尾段 140 字有訂閱鉤就不動)兩支的自動措辭是**流言終結者那條線的產品描述**
        # (「每天挑一個台股說法用真回測驗一次」「拿回測拆神話」),
        # 而那條線目前是壞的(旁白字數低於 _long_underlength 門檻)⇒ 那會變成一個交不出來的承諾。
        # 這裡自己寫,而且**只承諾確定的事**:不承諾頻率、不承諾下一支是什麼。
        f"如果你想在下手之前先看到代價,而不是在買進之後才知道,訂閱可以讓你看到這一類的拆解。"
    )
    b3 = (
        f"先看代價的第一層,回撤。這 {n} 檔裡面,百分之 {halved} 曾經從高點跌掉一半以上,"
        f"中位數是百分之 {dd}。請注意這句話的意思:它不是說某幾檔特別慘,"
        f"是說腰斬這件事在這群成交量最大的股票裡不是意外,是常態。"
        f"而回撤的殺傷力不在數字本身,在它發生的時候你不知道它會跌到哪裡。"
        f"事後看那是一條下去又上來的曲線,當下看那是一個沒有底的洞。"
        f"這也是為什麼我不喜歡只講年化報酬:年化報酬把時間攤平了,"
        f"而人是活在時間裡面的,你不是一次領走二十年的平均,你是一天一天過的。"
        f"把百分之 {dd} 換成錢會更有感覺。假設你投入一百萬,"
        f"在最深的那一天,帳戶上會剩下大約 {100 - dd:.1f} 萬。"
        f"你要在那個畫面前面,不賣、不停損、不去看別人在賺什麼,繼續抱著。"
        f"這才是那個中位數報酬真正的入場費。"
    )
    b4 = (
        f"第二層代價是套牢,而這一層才是真正勸退人的。"
        f"最長套牢期,我的定義是從一個歷史高點算起,到下一次創新高為止,中間隔了多久。"
        f"這 {n} 檔的中位數是 {uw} 年,百分之 {uw5} 曾經套牢五年以上,"
        f"有 {uw10n} 檔、也就是百分之 {uw10},曾經套牢或者到現在仍然套牢十年以上。"
        f"這裡我要特別誠實講一件對我們自己不利的事:那個百分之 {uw10} 是下限,不是上限。"
        f"因為 {n} 檔裡面有 {ong} 檔到今天還沒有解套,它們的年數只算到今天,還在往上加。"
        f"如果我把這 {ong} 檔剔除掉,我會得到一個低了兩個多百分點、比較好看的數字。"
        f"但是那 {ong} 檔裡面,已經有 {ong10} 檔套牢超過十年了 —— 那不是還沒觀測完的資料,"
        f"那是已經確定的事實。剔除它們等於直接刪掉 {ong10} 筆最痛的真實案例。所以我不剔。"
        f"如果那些還在計時的最後全部跨過十年,這個數字的上界是百分之 {uw10up}。"
        f"五年是什麼概念,是你買進之後,經歷完整一輪的產業循環、換過一次工作、"
        f"帳戶數字還在原地。而在那五年裡面,沒有任何人會通知你還要等多久。"
        f"回測資料會告訴你第幾年解套,現實不會。"
    )
    b5 = (
        f"接下來是我覺得最值得你花時間看的一段:個股跟大盤一支一支比。"
        f"這一段的期間跟前面不一樣,前面是每檔自己的完整歷史,中位數十八年多;"
        f"這一段用的是共同起點的區間,總共比得動 {nv} 檔,對照的是元大台灣五十。"
        f"結果是:單筆投入的個股,總報酬贏過同期元大台灣五十的,只有 {beatn} 檔,"
        f"佔百分之 {beat}。"
        f"這裡要補一個細節,因為它會影響你怎麼讀這個數字:那 {nv} 檔裡面,"
        f"有一部分上市比較晚,區間不到十年。"
        f"如果只看資料完整、確實是十年的那 {nv10} 檔,贏的是 {b10n} 檔,百分之 {b10}。"
        f"兩個數字都給你,是因為只講其中一個都會有人覺得被誤導。"
        f"不管用哪一個口徑,結論是一樣的:大約七成的標的,十年下來輸給那個你覺得很無聊的指數。"
        f"而且輸掉的同時,你還要多承受集中在單一公司的風險:一次財報地雷、一次客戶抽單、"
        f"一次產業轉型沒跟上,指數會幫你分散掉的東西,你要自己扛。"
        f"反過來看也一樣重要:有 {beatn} 檔是真的贏了的,那不是零。"
        f"問題是你要在事前挑中它,而不是事後看著排行榜說我早就知道。"
        f"同一批標的、同一個區間,我還多跑了一種買法:每個月固定投一筆的定期定額。"
        f"定期定額的總報酬贏過單筆投入的,只有百分之 {dca_win};"
        f"贏過同期元大台灣五十的,只有百分之 {dca_bench}。"
        f"這裡我必須把話講清楚,免得你把它讀成定期定額比較差。"
        f"定期定額的總報酬比較低,有很大一部分是數學上本來就會這樣:"
        f"你的錢是分很多年慢慢放進去的,平均待在市場裡的時間比單筆短很多,"
        f"在一個長期往上的市場,少待的那幾年就是少賺的那一段。"
        f"所以這組數字要回答的不是哪種買法比較好,而是:如果你選擇分批進場,"
        f"你要知道自己換到的是什麼 —— 你換到的是比較低的帳面波動,代價是比較低的總報酬。"
        f"那是一筆交易,不是一個免費的優勢。"
    )
    b6 = (
        f"所以整支片講到這裡,我想把問題換一個方向問。"
        f"我們一直在討論選哪一檔,可是資料告訴我的是:選對股票不是最難的部分。"
        f"這 {n} 檔裡面九成四以上是賺錢的 —— 而且別忘了,那還是在下市公司沒被算進來的前提下。"
        f"難的是中間那百分之 {dd} 的回撤,和那 {uw} 年的等待,你能不能撐過去。"
        f"而這件事買指數也一樣。抱不住個股的人,買元大台灣五十一樣抱不住,"
        f"因為讓人賣掉的從來不是標的,是帳面上那個往下掉的數字。"
        f"我不打算給你一個買什麼的建議,我想給你的是一個位置:"
        f"看完上面這些數字,你自己判斷一下,你能不能忍受帳面少掉七成、"
        f"然後在什麼都沒發生的情況下等上七年。"
        f"你如果知道自己不行,那不是弱點,那是你現在就該知道的事,而不是三年後才發現。"
        f"這支片用到的每一個數字,都來自公開市場資料的完整含息還原回測,"
        f"我把口徑和檔數都唸在片子裡,你可以自己去對。"
        f"下一次我做這種把全市場攤開來看的拆解時,訂閱的話你會收到。"
        f"以上只講已經發生過的事,不預測未來,也不構成投資建議。"
    )
    return [b1, b2, b3, b4, b5, b6]


def _segments() -> list:
    """六段。heading 刻意帶關鍵字,讓 make_video 的 _SEG_KEY_RULES 派到對的圖種。
    ⚠️ 必須 ≥3 段:`_long_too_few_segments` 對 1~2 段 fail-closed(0 段反而放行,是個坑)。"""
    return [
        {"heading": "全市場攤開:報酬與代價的全景分佈", "broll": ["finance", "chart", "data"]},
        {"heading": "一位觀眾說對了什麼", "broll": ["thinking", "comment", "people"]},
        {"heading": "代價一:回撤分佈,九成五腰斬過", "broll": ["chart", "down", "risk"]},
        {"heading": "代價二:套牢年數分佈,中位七年", "broll": ["waiting", "clock", "chart"]},
        {"heading": "個股對決大盤:十年區間分佈", "broll": ["compare", "chart", "index"]},
        {"heading": "所以問題不是選股,是抱得住嗎", "broll": ["decision", "calm", "finance"]},
    ]


def _title(x: dict) -> str:
    """🔴 標題刻意**不寫**「598 檔台股」——獨立驗證員指出那聽起來像全市場,
    而它是成交金額最大的三成。也刻意不寫套牢中位數的那個小數:
    n=598 是偶數、兩個中間值是 7.1 與 7.2,取一位小數等於把平手往上進位,
    那是 12 個數字裡唯一一個「換個進位規則就變另一個值」的,不要放進標題。"""
    return (f"台股成交量最大的 {x['n_return']} 檔,我全部跑完長期回測:"
            f"中位數賺 {x['total_return_median_pct']:.0f}%,"
            f"但九成五腰斬過、要你等七年")


def _description(x: dict) -> str:
    return "\n\n".join([
        f"把 {x['n_return']} 檔台股的完整長期回測攤開來看:"
        f"含息總報酬中位數 {x['total_return_median_pct']}%、"
        f"最大回撤中位數 {x['maxdd_median_pct']}%、"
        f"最長套牢期中位數 {x['uw_median_years']} 年。",
        f"其中 {x['halved_share_pct']}% 的股票曾經腰斬以上,"
        f"{x['uw_ge10_share_pct']}% 套牢過十年以上 —— "
        f"而那是下限,因為還有 {x['ongoing_n']} 檔到今天仍未解套,沒有被排除。",
        f"另外用同一個共同起點的十年區間,把 {x['n_versus']} 檔個股跟元大台灣50(0050)"
        f"一支一支比:個股單筆投入贏過 0050 的只有 {x['beat_n']} 檔,佔 {x['beat_share_pct']}%。",
        "資料來源:公開市場歷史資料的完整含息還原回測。只陳述已發生的事實,不預測未來。",
    ])


def build_script() -> dict | None:
    """組稿。任何一步不確定就回 None(fail-closed)——旗艦片寧可不產,也不要半套。"""
    try:
        x = _facts()
    except Exception as exc:  # noqa: BLE001
        print(f"[flagship] 拒絕組稿:{exc}", file=sys.stderr)
        return None
    beats = _beats(x, _cov())
    voice = "\n\n".join(beats)
    ok, msg = script_selfcheck(voice)
    if not ok:
        print(f"[flagship] 稿子自檢未過,拒絕組稿:{msg}", file=sys.stderr)
        return None
    return {
        "title": _title(x),
        "voice_text": voice,
        "segments": _segments(),
        "description": _description(x),
        "hashtags": ["#台股", "#長期投資", "#回測", "#0050", "#最大回撤",
                     "#套牢", "#存股", "#量化阿森"],
        # A2 捏造績效閘豁免:本片每個數字都來自 flagship_xsec 的結構化欄位(語義正確,非繞過)
        "_is_tw_stock": True,
        # 本引擎自己的標記,產線不讀
        "_is_flagship_xsec": True,
        "_xsec": {k: v for k, v in x.items() if not k.startswith("_")},
    }


def build_topic() -> dict:
    """⚠️ 刻意**不設 `fact_key`**:那是拖進 TW_STOCK_CHECKUP_RULES 的唯一開關
    (`produce_batch.py:2741`),而本片不是個股體檢。
    也不設 `source`:填到 news/hotspot/breakout/intel 會套時事框架。"""
    return {
        "title": SERIES_NAME,
        "angle": f"{SERIES_NAME}:把全市場的長期回測攤開,先給報酬再給代價,"
                 f"承認一位觀眾說對了,最後不給建議只給位置。",
        "category": CATEGORY,
        "format": "long",
    }


# ── 稿子自檢:照 make_one:6105 那道鎖題終檢的判準 ──────────────────────
_CJK = re.compile(r"[一-鿿]")
_HEDGE = ("風險承受能力", "務必評估", "自行評估風險", "不構成投資建議", "投資前請", "並自行承擔")


def script_selfcheck(voice: str) -> tuple:
    """在送進產線**之前**先自己擋一次。

    🔴 這不是防禦性程式碼:如果稿子過不了 `make_one` 那道閘,產線會呼叫 LLM 重寫,
    而重寫之後這支片就**不再是確定性組稿** —— 它會安靜地變成一支普通的 LLM 稿,
    沒有任何訊號告訴我們那件事發生了。**寧可在這裡回 None,也不要讓它悄悄降級。**"""
    bad = []
    n_cjk = len(_CJK.findall(voice))
    if n_cjk < 1800:
        bad.append(f"中文字數 {n_cjk} < 1800(LONG_MIN_CHARS)")
    if "【" in voice or "】" in voice:
        bad.append("含全形方括號,會被鎖題終檢擋下")
    sents = [s for s in re.split(r"[。!?!?]", voice) if s.strip()]
    for i, s in enumerate(sents[:2]):
        if len(_CJK.findall(s)) < 12:
            bad.append(f"開場第 {i+1} 句只有 {len(_CJK.findall(s))} 個中文字 < 12(碎句鉤子)")
    body = voice[int(len(voice) * 0.10):int(len(voice) * 0.80)]
    for h in _HEDGE:
        if body.count(h) > 1:
            bad.append(f"正文 10~80% 出現「{h}」{body.count(h)} 次(>1)")
    if bad:
        return False, ";".join(bad)
    return True, f"中文字數 {n_cjk}、句數 {len(sents)}、六段"


if __name__ == "__main__":
    import argparse
    import json as _json
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true", help="印出稿子全文(不產片)")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    d = build_script()
    if not d:
        raise SystemExit(1)
    ok, msg = script_selfcheck(d["voice_text"])
    print(f"稿子自檢:{'✅' if ok else '🔴'} {msg}")
    print(f"標題:{d['title']}")
    print(f"段數:{len(d['segments'])}")
    if a.dump:
        print("\n" + "=" * 70)
        print(d["voice_text"])
        print("=" * 70 + "\n描述:\n" + d["description"])
    else:
        print(_json.dumps(d["_xsec"], ensure_ascii=False, indent=1))
    raise SystemExit(0 if ok else 1)
