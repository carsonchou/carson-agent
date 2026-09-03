# -*- coding: utf-8 -*-
"""驗收:①8 支已知洩漏全被接住(逐支前後對照)②745 支母體零誤刪。"""
import sys, collections
from pathlib import Path
sys.path.insert(0, 'scripts')
import produce_batch as pb
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

KNOWN = {'L_資產再平衡真的能多賺我用模擬揭露這個頻率沒抓對十年報':'資產再平衡(未發布,已攔)',
 'L_個股體檢金居835815年賺24倍但套牢58年腰斬4':'金居(未發布,已攔)',
 'L_個股體檢宜特3289長期持有報酬248這檔個股腰斬3':'宜特(已發布)',
 'L_個股體檢矽力-KY641512年賺10倍但最大回撤8':'矽力(已發布)',
 'L_個股體檢立隆電247220年暴賺32399但847最':'立隆電(已發布)',
 'L_個股體檢竑騰7751毛利率雪崩式下滑股價竟還飆漲這檔':'竑騰(已發布)',
 'L_個股體檢至上811218年報酬2114最大回撤-78':'至上(已發布)',
 'L_個股體檢譜瑞-KY4966長抱譜瑞-KY149年總報':'譜瑞(已發布)',
 'L_個股體檢盟立246420年暴賺1498這檔冷門股套牢':'盟立(督導判無洩漏)'}

print("【驗收一】8 支已知洩漏 —— 前後對照\n")
for f, nm in KNOWN.items():
    t = Path(f'output/{f}.voice.txt').read_text(encoding='utf-8', errors='replace')
    kill, gray = pb._prompt_leak_suspects(t)
    gate = pb._long_prompt_leak(t)
    after = pb._strip_prompt_leak(t)
    resid, _ = pb._prompt_leak_suspects(after)
    print(f"── {nm}")
    print(f"   閘門觸發: {'是' if gate else '否'}｜刪 {len(kill)} 句、標記 {len(gray)} 句"
          f"｜字數 {len(t)} → {len(after)}｜殘留 {len(resid)}")
    for s in sorted(kill)[:2]:
        print(f"     刪:{s.strip()[:62]}")
    for s in gray[:1]:
        print(f"     標:{s[:62]}")

print("\n\n【驗收二】745 支母體零誤刪 —— 所有被刪句子的完整清單\n")
files = list(Path('output').glob('*.voice.txt'))
dele = collections.defaultdict(set)
gray_n = set()
for p in files:
    t = p.read_text(encoding='utf-8', errors='replace')
    k, g = pb._prompt_leak_suspects(t)
    stem = p.name[:-len('.voice.txt')]
    for s in k:
        dele[s.strip()[:46]].add(stem)
    if g:
        gray_n.add(stem)
df = set().union(*dele.values()) if dele else set()
print(f"母體 {len(files)} 支 → 會刪 {len(dele)} 種句子、涉及 {len(df)} 支;另 {len(gray_n)} 支進灰色地帶(標記不刪)\n")
for z, fs in sorted(dele.items(), key=lambda kv: -len(kv[1])):
    print(f"  {len(fs):>3} 支  {z}")
