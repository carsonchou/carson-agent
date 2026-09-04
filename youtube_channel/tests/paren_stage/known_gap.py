#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""括號式分鏡指示:閘門在構造上豁免它 —— **這支現在會 FAIL,那是刻意的。**

用法:cd youtube_channel && .venv/Scripts/python.exe tests/paren_stage/known_gap.py

一句話說完這個洞:**同一句話,不加括號被抓,加了括號全部放行。**

    鏡頭切到健策的K線圖,疊上0050做對照。          → _long_stage_direction 抓到 ✔
    (鏡頭切健策K線疊加0050)健策這十年的報酬…      → 每一道閘門都放行 ✘

根因在 `_long_stage_direction`:它先用 `_STAGE_RE.sub(" ")` 把**括號內容整段扣掉**再找分鏡詞,
理由寫在產線註解裡 ——「那類由 `_fix_artifacts` 自動清掉」。
**那個前提是假的**:實測 `_fix_artifacts` 對這五句一句都沒清掉(半形全形都一樣)。
於是括號變成豁免區,而**明白包成指令的形式反而比裸的更安全**。

這不是推論,是 5 支已上架影片的實據(獨立驗證員拿 `.wordtimes.json` ——
edge-tts 合成當下吐的 SentenceBoundary,與 mp3 同一次呼叫 —— 逐支確認真的唸出去了):
    ULkaLj4d_tA 健策「(鏡頭切健策K線疊加0050)」 音檔 t=473.7s
    OhrPgVP_CR8 友達「(鏡頭拉近)」
    WFJoOC-4izg 群創「(鏡頭拉近)」「(畫面字卡:留言區投票下一檔想拆解的股票)」
    H3Sk1AfUVT0 力成「(停頓半秒)」「(最後畫面字卡)」
    jsIt1qA1aj8 順達「(螢幕標註:所有資料皆為歷史回測…)」
健策那一句**正是 produce_batch.py 註解裡當範例寫的那句** —— 例子在原始碼,片子在線上,
而兩份洩漏普查都沒數到它(普查用的兩支偵測器對它們全部回 None)。

⚠️ **為什麼今天不修**(2026-09-04):
逐月實測 07 月 5/436、08 月 2/229(最後一次 08-11)、**09 月 0/69** —— 這個洞已休眠三週。
而明天 06:07 是「重生回饋」上線後第一次被真的行使,加一道閘門會改變重生負載、汙染那次觀測。
「今晚修」相對「觀測完再修」的價值很小,風險是真的。**所以留這支會失敗的測試,而不是留一則註解**
—— 註解會被讀過就忘,失敗的測試每次跑都會叫。修好之後它自己變綠。

修法建議(不是硬性):括號式分鏡指示是**純指令、零內容**,刪掉不損失任何真資料,
與 `【】`、項目符號同一個性質 → 走**確定性刪除**(在 `_fix_artifacts` 用 `_STAGE_RE`),
而不是觸發重生。重生的成本要用「接近 r」估不是 r^n(見 memory `yt-period-swap-integrity`)。
`_STAGE_RE` 本身已經帶了負向前瞻排除「來源/出處/單位/註:」,合法括號不會被咬到。
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
if not (BASE / "scripts").is_dir():
    print(f"**FAIL** cwd 不對:找不到 {BASE / 'scripts'}。請 cd youtube_channel 再跑。")
    raise SystemExit(2)
sys.path.insert(0, str(BASE / "scripts"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import produce_batch as pb  # noqa: E402


def gates(v):
    """產線放行前真正跑的那幾道(見 produce_batch.py `_others` 那組 lambda)。"""
    out = []
    if pb._long_prompt_leak(v):
        out.append("prompt洩漏")
    if pb._long_stage_direction(v):
        out.append("分鏡指示")
    if "【" in v:
        out.append("【】")
    return out


LEAK = [   # 已上架影片的真實原句,已由 wordtimes 證實唸出去了
    "（鏡頭切健策K線疊加0050）健策這十年的報酬其實沒有你想的那麼平順。",
    "(鏡頭切健策K線疊加0050)健策這十年的報酬其實沒有你想的那麼平順。",
    "（鏡頭拉近）友達的毛利率在這一段時間發生了什麼事?",
    "（畫面字卡:留言區投票下一檔想拆解的股票）群創的故事還沒完。",
    "（停頓半秒)力成這個數字,我第一次看到也不敢相信。",
    "（螢幕標註:所有資料皆為歷史回測)順達的年化報酬是這樣算出來的。",
]
KEEP = [   # 🔴 修的時候不准咬到這些:合法括號,誤刪會賠掉真資料或合規聲明
    "健策(3653)這十年的報酬其實沒有你想的那麼平順。",
    "總報酬 1523%(資料來源:證交所還原股價)。",
    "年化報酬 12.4%(註:所有資料皆為歷史回測,非未來獲利保證)。",
    "台積電(2330)與聯電(2303)的差距在這十年拉開。",
]
BARE = [   # 陽性對照:同一件事不加括號,現在就抓得到 —— 證明偵測器本身是活的
    "鏡頭切到健策的K線圖,疊上0050做對照。",
    "畫面定格在那根跌停的K棒上。",
]

fails = 0
print("【一】括號式分鏡指示必須被擋(或被確定性刪除)—— 目前全部放行")
for s in LEAK:
    g = gates(s)
    cleaned = pb._fix_artifacts(s)
    caught = bool(g) or ("(" not in cleaned and "（" not in cleaned)
    fails += 0 if caught else 1
    print(f"  {'PASS' if caught else '**FAIL**'}  閘門={','.join(g) or '全部放行'}"
          f"  _fix_artifacts清掉={'是' if ('(' not in cleaned and '（' not in cleaned) else '否'}"
          f"  {s[:26]}")

print("\n【二】合法括號不准被咬到(誤刪比漏擋貴:賠真數字或合規聲明)")
for s in KEEP:
    g = gates(s)
    cleaned = pb._fix_artifacts(s)
    ok = not g and cleaned.count("(") + cleaned.count("（") == s.count("(") + s.count("（")
    fails += 0 if ok else 1
    print(f"  {'PASS' if ok else '**FAIL**'}  閘門={','.join(g) or '放行'}  {s[:34]}")

print("\n【三】陽性對照:裸分鏡現在就該被抓 —— 沒抓到代表偵測器整個死了,不是這個洞")
for s in BARE:
    g = gates(s)
    fails += 0 if g else 1
    print(f"  {'PASS' if g else '**FAIL**'}  閘門={','.join(g) or '**全部放行**'}  {s[:30]}")

print(f"\n合計 FAIL = {fails}")
if fails:
    print("⚠️ 【一】全紅是**已知且刻意留著**的(2026-09-04,見本檔 docstring):洞已休眠三週")
    print("   (09 月 0/69),而明天 06:07 是重生回饋第一次被行使,不在觀測前夜動執行路徑。")
    print("   🔴 但【二】或【三】變紅就不是已知狀態 —— 那代表有人動壞了別的東西,立刻查。")
raise SystemExit(1 if fails else 0)
