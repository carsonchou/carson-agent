#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""prompt 洩漏偵測驗收 —— 四個方向缺一不可。

用法:cd youtube_channel && .venv/Scripts/python.exe tests/prompt_leak/verify.py

四條驗收(第 3 條是階段二被咬出來才加的):
  1. 已知洩漏全部接住(閘門會叫 + strip 後零殘留)
  2. 零誤刪:745 支母體 + 對抗語料,合法旁白一句都不准被刪
  3. 🔴 不准有任何案例比改動前更安靜 —— 拿 cbfb12e7^ 那版當對照組逐支比對,
     任何一支從「會叫」變成「不會叫」就是 FAIL。
     (階段二的事故正是這個形狀:`;` 分句 + 長度下限製造出一個永遠刪不掉的碎片,
      於是「刪掉會叫的那半、留下不會叫的那半」→ 閘門 None → 帶著洩漏出貨、零訊號。)
  4. 灰色地帶誤標率;寧可誤標也不要誤刪,兩者衝突時選誤標。
"""
import collections
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "scripts")
import produce_batch as pb  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("output")
fails = 0


def check(label, cond, extra=""):
    global fails
    fails += 0 if cond else 1
    print(f"  {'PASS' if cond else '**FAIL**'}  {label}{('  ' + extra) if extra else ''}")


# ── 一、已知洩漏 ──────────────────────────────────────────────────────────────
print("【一】已知洩漏:閘門要叫,strip 後零殘留")
known = sorted(p for p in OUT.glob("L_*.voice.txt")
               if pb._long_prompt_leak(p.read_text(encoding="utf-8", errors="replace")))
bad = []
for p in known:
    t = p.read_text(encoding="utf-8", errors="replace")
    after = pb._strip_prompt_leak(t)
    kill, _ = pb._prompt_leak_suspects(after)
    if kill:
        bad.append(p.name)
check(f"閘門攔下 {len(known)} 支;strip 後仍有可刪殘留的支數 = 0", not bad, str(bad[:3]))

# ── 二、零誤刪 ────────────────────────────────────────────────────────────────
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
    "不編造精確數字、不保證收益、不喊單、不報明牌。",
]
killed = [s for s in ADVERSARIAL if pb._prompt_leak_suspects(s)[0]]
check(f"對抗語料 {len(ADVERSARIAL)} 句全部放行", not killed, str(killed))

files = list(OUT.glob("*.voice.txt"))
dele, gray_files = collections.defaultdict(set), set()
for p in files:
    k, g = pb._prompt_leak_suspects(p.read_text(encoding="utf-8", errors="replace"))
    for s in k:
        dele[s.strip()[:46]].add(p.name)
    if g:
        gray_files.add(p.name)
df = set().union(*dele.values()) if dele else set()
print(f"     母體 {len(files)} 支 → 刪 {len(dele)} 種句子/{len(df)} 支;灰色地帶 {len(gray_files)} 支")
print("     (被刪句子全列於下,逐句自審是否有真旁白)")
for z, fs in sorted(dele.items(), key=lambda kv: -len(kv[1]))[:12]:
    print(f"       {len(fs):>3}  {z}")

# ── 三、不准有任何案例比改動前更安靜 ─────────────────────────────────────────
print("\n【三】不准有任何案例比改動前更安靜(對照組 cbfb12e7^)")
tmp = Path(tempfile.mkdtemp())
old_src = subprocess.run(["git", "show", "cbfb12e7^:youtube_channel/scripts/produce_batch.py"],
                         capture_output=True, cwd="..", text=False).stdout
quieter = []
if old_src:
    (tmp / "produce_batch_old.py").write_bytes(old_src)
    sys.path.insert(0, str(tmp))
    try:
        import produce_batch_old as old  # noqa: E402
        for p in files:
            t = p.read_text(encoding="utf-8", errors="replace")
            was = bool(old._long_prompt_leak(old._strip_prompt_leak(t))) or \
                bool(old._long_prompt_leak(t))
            now_before = bool(pb._long_prompt_leak(t))
            now_after = bool(pb._long_prompt_leak(pb._strip_prompt_leak(t)))
            # 「更安靜」= 舊版會叫(修前或修後任一)而新版修前修後都不叫
            if was and not (now_before or now_after):
                quieter.append(p.name)
    except Exception as e:  # noqa: BLE001
        print(f"     ⚠️ 對照組載入失敗:{e!r}")
        quieter = ["<對照組載入失敗,本項未驗>"]
else:
    quieter = ["<取不到 cbfb12e7^,本項未驗>"]
check("沒有任何一支從「會叫」變成「不會叫」", not quieter, str(quieter[:3]))

# ── 四、灰色地帶 ──────────────────────────────────────────────────────────────
print("\n【四】灰色地帶(標記交重生,不刪)")
gray_sent = collections.Counter()
for p in files:
    _, g = pb._prompt_leak_suspects(p.read_text(encoding="utf-8", errors="replace"))
    for s in g:
        gray_sent[s[:40]] += 1
print(f"     落灰 {len(gray_files)} 支 / {len(gray_sent)} 種句子(前 6):")
for z, n in gray_sent.most_common(6):
    print(f"       {n:>3}  {z}")

print(f"\n合計 FAIL={fails}")
raise SystemExit(1 if fails else 0)
