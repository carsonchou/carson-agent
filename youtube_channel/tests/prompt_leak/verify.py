#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""prompt 洩漏偵測驗收。

用法:cd youtube_channel && .venv/Scripts/python.exe tests/prompt_leak/verify.py

## 🔴 這支自己必須先站得住(2026-09-03 第四輪,驗證員實測打掉前一版)

前一版有兩個單一參數,各自都能在**偵測器完全停擺**的情況下讓驗收全綠:
    _LEAK_DEL = 1.01          → 什麼都不刪 → 檢查一、五仍然 PASS
    _HARD_DIRECTIVE 縮成 1 詞 → 語料 0 條、實刪 0 種 → **全部 PASS**
而且 `output/` 是空的時候四條檢查也全 PASS(它印了「母體 0 支」但沒有對它斷言)——
和同一天早上在 run_all.py 上抓到的是同一個病:**一個不會叫的檢查**。

所以這一版的自我約束:
  · `residue()` **自己 AST 掃全檔字串建語料,不套 `_HARD_DIRECTIVE`、不呼叫
    `_leak_corpus()`/`_leak_similarity()`/任何門檻常數** —— 調詞表不能同時讓
    偵測器和驗收一起失明。
  · 每一條檢查都要有**不讀門檻**的平行斷言(看輸出變不變,不看分數)。
  · 母體、對照組載入、例外次數,全部要斷言;印出來不算檢查。

驗收條件是「把偵測器弄壞之後它要變紅」,不是「跑起來全綠」:
    python tests/prompt_leak/verify.py --self-test    # 三個攻擊各跑一次,全部必須 FAIL
"""
import ast
import collections
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

sys.path.insert(0, "scripts")
import produce_batch as pb  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("output")
fails = 0

# ── 驗收自己的語料:AST 掃全檔字串,**不套任何可調詞表** ──────────────────────
_SYN = (("数据", "資料"), ("數據", "資料"), ("数據", "資料"), ("网络", "網路"),
        ("網絡", "網路"), ("软件", "軟體"), ("軟件", "軟體"), ("信息", "資訊"),
        ("质量", "品質"), ("質量", "品質"))
_ENUM = re.compile(r"^[①-⑳0-9０-９一二三四五六七八九十]{1,3}[、.．)）]?")
_SENT = re.compile("(?<=[。！？!?\n;；])")
# 本來就要唸出來的東西不算殘留(和產線的保護清單同概念,但**這份是測試自己的**,
# 不 import 產線那份 —— 否則產線改保護清單就能同時讓驗收失明)。
# 🔴 用**完整說法**不用裸詞。第一版寫 `訂閱|頻道`,而產線 _LEAK_PROTECTED 的註解
# 早就寫著「寫『訂閱』會把『④結尾:引導訂閱與留言』這種真指令一起豁免掉」——
# **產線已經記取的教訓,測試沒跟上。** 實測代價:15 條真指令被測試的排除清單吃掉
# (「①必須明確出現「訂閱」二字」「ⓚ-2 禁止任何頻道自我介紹」
#  「【量化內容嚴謹標準｜務必正確,這是頻道專業度的命脈】」),
# 於是**任何提到「訂閱」或「頻道」的指令原文洩漏,這把尺永遠看不到**,
# 而檢查三、四都是靠它判 FAIL 的 —— 已裝好的地雷,不是已爆的。
_SPEAKABLE = re.compile(
    "不代表未來|不構成投資建議|僅供參考|投資有風險"
    # CTA 模板:產線**故意**寫進旁白的完整句式(訂閱 + 後面接著給觀眾的理由)
    "|訂閱[^。]{0,20}(?:才|就|可以|不會|收得到|收到|跟著|漏掉|錯過|第一時間"
    "|通知你|推給你|每集|下支|下一集|下一組|攤開給你看)"
    "|這個頻道[^。]{0,12}(?:每天|專門|用真)|會這樣拆資料的頻道"
    "|留言告訴我|免費領|檢核表"
    "|我先幫你|別自己送死|背考古題"
    "|不編造精確數字|一臺機車的錢")     # 人設台詞 / 鉤子範本(對抗語料裡列為合法的那些)
# 🔴 16 不是 12,而且這個數字是**校準出來的**不是挑的:
# 未過濾的 AST 語料含大量「產線自己要寫進旁白」的模板(CTA、轉場、鉤子回扣),
# 12 字會把它們全算成殘留 → 745 支量到 276 支,那是誤報不是敏感。
# 排除 CTA/人設模板(用**完整說法**不用裸詞)+ 下限 16 → 剝除前量到 24 支。
# ⚠️ **不要**再寫「與獨立驗證員量法一致」——那是湊數字:當時拿本尺的「剝除前 26」
# 去對驗證員的「剝除後 26」,像對像其實是 26/40 = 65% 與 10/26 = 38%,
# 而且 Jaccard 只有 0.57 / 0.29 —— **量到的根本不是同一批片**。
# 誠實的定位:它是**趨勢尺**不是偵測器,敏感度低於獨立驗證員的量法,
# 已知盲區是正規化後短於 16 字的指令(例:「五種必爆骨架擇一」)。
# 用途只有一個:給第四條門檻一個**不受偵測器參數影響**的基準線。
_RESIDUE_MIN = 16


def _norm(s):
    s = unicodedata.normalize("NFKC", s or "")
    for a, b in _SYN:
        s = s.replace(a, b)
    return re.sub(r"[^\w一-鿿]", "", _ENUM.sub("", s.strip()))


def _build_residue_corpus():
    tree = ast.parse(Path("scripts/produce_batch.py").read_text(encoding="utf-8"))
    docs = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None) or []
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            docs.add(id(body[0].value))
    out = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in docs:
            continue
        for raw in _SENT.split(node.value):
            if not raw.strip() or _SPEAKABLE.search(raw) or raw.rstrip().endswith(("?", "？")):
                continue
            z = _norm(raw)
            if len(z) >= _RESIDUE_MIN:
                out.add(z)
    return sorted(out)


RESIDUE_CORPUS = _build_residue_corpus()


def residue(text):
    """剝完之後還留著哪些指令原文。判準是**原封不動出現**,不用任何相似度門檻。"""
    z = _norm(text or "")
    return [c for c in RESIDUE_CORPUS if c in z]


def check(label, cond, extra=""):
    global fails
    fails += 0 if cond else 1
    print(f"  {'PASS' if cond else '**FAIL**'}  {label}{('  ' + extra) if extra else ''}")


# ── 〇、驗收自己站不站得住 ───────────────────────────────────────────────────
print("【〇】驗收自身的前提(印出來不算檢查,要斷言)")
files = list(OUT.glob("*.voice.txt"))
check(f"母體 >= 700 支", len(files) >= 700, f"實得 {len(files)}")
check(f"殘留語料 >= 200 句(AST 全檔字串,未套 _HARD_DIRECTIVE)",
      len(RESIDUE_CORPUS) >= 200, f"實得 {len(RESIDUE_CORPUS)}")

# 🔴 語料路徑的活體探針。舊的 _PROMPT_LEAK_MARKERS 樣式清單是**另一條獨立路徑**,
# 它還活著的時候,即使語料整個清空(例:_HARD_DIRECTIVE 被縮成一個詞),
# 「閘門有沒有叫」「刪了幾種句型」看起來都正常 —— 實測攻擊二就是這樣騙過前一版。
# 所以要有一句**只有語料路徑抓得到**的探針:它來自 f-string 動態組出的 prompt,
# 不在任何樣式清單裡。它不叫 = 語料路徑死了,不管其他檢查多綠。
# 保護清單被放寬(極端例:改成 `.`)會讓偵測變差而 verify 全綠 —— 實測閘門 37→36 支、
# 靜音出貨 11→14 支,而所有檢查都不叫。用「保護清單**不准**命中這些真指令」擋它。
for _d in ("④嚴禁出現誇大/保證詞：穩賺、穩賺不賠、保證獲利。",
           "五種必爆骨架擇一（可與《拆穿》疊加）：",
           "①你唯一能當成事實講的精確數字，只有上面實證資料區塊給的那幾個。"):
    check(f"保護清單沒有把真指令一起豁免:{_d[:16]}…",
          not pb._LEAK_PROTECTED.search(_d))

CANARY = "只輸出重寫後的完整段落純文字，不要JSON/小標/前字尾。"
check("語料路徑活著(探針句仍被判為要刪)",
      bool(pb._prompt_leak_suspects(CANARY)[0]),
      f"探針相似度 {pb._leak_similarity(CANARY)[0]:.2f};語料 {len(pb._leak_corpus()[0])} 句")

# ── 一、已知洩漏 ─────────────────────────────────────────────────────────────
print("\n【一】已知洩漏:閘門要叫,而且剝除要真的把指令原文拿掉")
known = [p for p in files if p.name.startswith("L_")
         and pb._long_prompt_leak(p.read_text(encoding="utf-8", errors="replace"))]
shrunk = grew = 0
for p in known:
    t = p.read_text(encoding="utf-8", errors="replace")
    b, a = len(residue(t)), len(residue(pb._strip_prompt_leak(t)))
    shrunk += a < b
    grew += a > b
check(f"閘門攔下 {len(known)} 支(>= 30)", len(known) >= 30)
# 平行斷言:不讀任何門檻,只看「指令原文有沒有真的變少」。
# ⚠️ 不要求「每一支都變少」:閘門叫而剝除沒動的那種是 gray-only —— 相似度落在
# 0.60~0.90,**刻意不刪、交重生**。把它算成 FAIL 會逼人去刪灰色地帶,那正是誤刪的來源。
check("剝除讓殘留變少 >= 15 支,且沒有任何一支剝完殘留反而變多",
      shrunk >= 15 and grew == 0, f"減少 {shrunk} 支 / 變多 {grew} 支")

# ── 二、零誤刪 ───────────────────────────────────────────────────────────────
print("\n【二】零誤刪")
ADVERSARIAL = [
    "很多人以為存股就是嚴禁停損，但回測資料顯示不是這樣。",
    "我先幫你用資料試過，別自己送死。",
    "你的網格機器人，是設計來盤整賺錢，還是趁你睡覺把本金歸零？",
    "當沖九成畢業，你以為你是那一成？",
    "無腦存股，結果套在一萬八千點山頂。",
    "假設你連虧三次，帳戶可能只剩六成，這只是打個比方。",
    "這不是喊單頻道，我只做能回測驗證的東西。",
    "以上都是歷史回測，不代表未來，也不構成投資建議。",
    "留言告訴我，這集哪個數字最讓你意外。",
    "訂閱之後，下一集我帶你看同產業的另一檔。",
    "同樣是定期定額0050，光是扣款日的選擇，十年後竟然可以差到一臺機車的錢。",
    "先講一句：後面還有更反直覺的部分。",
    "大盤擇時 vs 長抱不動——用真回測數字比給你看。",
    "這一段講的是最大回撤，也就是你帳面上最痛的那一刻。",
    "背考古題背到滾瓜爛熟，考試還是可能考出新題型。",
    "這只是歷史回測，不代表未來。",
    "別忘了訂閱量化阿森，下一集帶你看同產業的另一檔。",
    "免費領新手回測避雷檢核表，連結放在資訊欄。",
    "不編造精確數字、不保證收益、不喊單、不報明牌。",
]
# 平行斷言:不看分數、不看 kill 集合,只看**文字有沒有被動過**
changed = [s for s in ADVERSARIAL if pb._strip_prompt_leak(s) != s]
check(f"對抗語料 {len(ADVERSARIAL)} 句,剝除後文字一個字都沒變", not changed, str(changed[:2]))

dele = collections.defaultdict(set)
for p in files:
    t = p.read_text(encoding="utf-8", errors="replace")
    a = pb._strip_prompt_leak(t)
    if a != t:
        for s in pb._prompt_leak_suspects(t)[0]:
            dele[s.strip()[:46]].add(p.name)
df = set().union(*dele.values()) if dele else set()
print(f"     母體 {len(files)} 支 → 刪 {len(dele)} 種句子/{len(df)} 支")
check("實際刪除的句型 >= 30 種(偵測器沒有停擺)", len(dele) >= 30, f"實得 {len(dele)}")
for z, fs in sorted(dele.items(), key=lambda kv: -len(kv[1]))[:8]:
    print(f"       {len(fs):>3}  {z}")

# ── 三、不准有任何真洩漏比改動前更安靜 ───────────────────────────────────────
print("\n【三】三版全部當對照(判準看結果:剝完仍有殘留而閘門從叫變不叫)")
tmp = Path(tempfile.mkdtemp())
sys.path.insert(0, str(tmp))
quieter, loaded = [], 0
now_alarm = {p.name: bool(pb._long_prompt_leak(p.read_text(encoding="utf-8", errors="replace")))
             for p in files}
for ref in ("2e864602", "cbfb12e7", "01e0ccfe"):
    src = subprocess.run(["git", "show", f"{ref}:youtube_channel/scripts/produce_batch.py"],
                         capture_output=True, cwd="..", text=False).stdout
    if not src:
        quieter.append(f"<取不到 {ref}>")
        continue
    mod = f"pb_{ref}"
    (tmp / f"{mod}.py").write_bytes(src)
    try:
        old = __import__(mod)
    except Exception as e:  # noqa: BLE001
        quieter.append(f"<{ref} 載入失敗 {e!r}>")
        continue
    loaded += 1
    loss = fmark = errs = 0
    for p in files:
        t = p.read_text(encoding="utf-8", errors="replace")
        try:
            was = bool(old._long_prompt_leak(t))
        except Exception:  # noqa: BLE001
            errs += 1        # 🔴 例外要**計數**:安靜地 continue 會讓迴圈什麼都沒比就 PASS
            continue
        if not was or now_alarm[p.name]:
            continue
        if residue(pb._strip_prompt_leak(t)):
            quieter.append(f"{ref}:{p.name}")
            loss += 1
        else:
            fmark += 1
    print(f"     {ref}:剝完仍有殘留卻靜音 {loss}｜少掉的誤標 {fmark}｜比對時例外 {errs}")
    if errs > len(files) * 0.05:
        quieter.append(f"<{ref} 例外 {errs} 支,比對不可信>")
check("三版全部載入成功", loaded == 3, f"實得 {loaded}")
check("沒有「剝完仍有殘留、閘門卻從叫變不叫」", not quieter, str(quieter[:3]))

# ── 四、帶殘留靜音出貨(結果面總指標)─────────────────────────────────────────
print("\n【四】帶殘留靜音出貨")
before = [p.name for p in files if residue(p.read_text(encoding="utf-8", errors="replace"))]
silent = []
for p in files:
    a = pb._strip_prompt_leak(p.read_text(encoding="utf-8", errors="replace"))
    if residue(a) and not pb._long_prompt_leak(a):
        silent.append(p.name)
print(f"     剝除前含指令原文的支數:{len(before)}(尺的敏感度,前一版只量到 1)")
print(f"     剝除後仍有、而閘門不叫:{len(silent)}")
check("尺夠敏感:剝除前量得到的殘留 >= 20 支", len(before) >= 20, f"實得 {len(before)}")
# 棘輪:這個數字只能往下,不准往上。它不是「目標值」——尺變準之後它會跳(這一輪就
# 從 4 跳到 31 再回到 1,因為裸詞排除清單先低報、補齊 CTA 句式後才校正)。
check("帶殘留靜音出貨 <= 3 支(棘輪,只能往下)", len(silent) <= 3, f"實得 {len(silent)}")
for n in silent[:5]:
    print(f"       {n}")

print(f"\n合計 FAIL={fails}")
raise SystemExit(1 if fails else 0)
