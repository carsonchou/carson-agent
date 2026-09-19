# -*- coding: utf-8 -*-
"""第五輪:溫和調降(砍 31%)必須叫,而且要說得出第幾天。"""
import sys, json, io, pathlib, tempfile, contextlib, datetime as dt
sys.path.insert(0,'scripts'); import quota_meter as qm, daily_health as dh
# 🔴 2026-09-03:原本直接讀 STUDIO/quota_meter.json(活的產線帳本)。
# 獨立驗證員指出那讓套件的預期結果綁在今天的產線資料上 —— ledger_broken 的 E3
# 甚至是一句「今天的真帳本 → info」的活斷言:產線哪天真的撞牆,daily_health 正確
# 地回 🔴,E3 就 FAIL,於是任何人驗一個完全無關的修法都會看到紅字。那是
# verification-that-cannot-fail 的「一定叫」型,和 run_all 那個「不會叫」是同一枚硬幣。
# 改讀凍結快照(進版控、可 review、跟著程式一起演進);活帳本只留 replay10.py 一個消費者。
_FIXTURE = pathlib.Path(__file__).resolve().parent / 'fixtures' / 'ledger_snapshot.json'
tmp = pathlib.Path(tempfile.mkdtemp())/'l.json'; qm.STATE = tmp
today = qm._pacific_date(); T = dt.date.fromisoformat(today)
ago = lambda n: (T - dt.timedelta(days=n)).isoformat()
W = lambda sp, rj, ru=0, cal=200: {'spent':sp,'rejected_calls':rj,'rejected_units':ru,'calls':cal}

def run(days, label, expect, want=None):
    tmp.write_text(json.dumps({'days':days}), encoding='utf-8')
    buf=io.StringIO()
    with contextlib.redirect_stdout(buf): dh.main()
    out=buf.getvalue().splitlines()
    got='warn' if out[-1].startswith('🔴') else 'info'
    ok = got==expect and (want is None or any(want in l for l in out))
    print(f"### {label}: 期望={expect}{'/含「'+want+'」' if want else ''} 實得={got} {'PASS' if ok else '**FAIL**'}")
    if not ok or '砍 31%' in label:
        for l in out:
            if '🔴 **' in l or 'ℹ️' in l: print('      '+l.strip()[:165])

# 前牆 26,001 放在 25 天前,不會被覆蓋
base = {ago(25): W(26001,31,325,182), ago(24): W(23341,2,850,334)}

print("【方向一】配額砍 31%(26,001 → 18,000 = 69.2%),四種真實被拒量級各跑五天")
for rj, ru, cal, tag in [(2,850,334,'08-28 量級'),(16,16,440,'08-29 量級'),
                         (31,325,182,'08-31 量級'),(935,45491,287,'08-27 量級')]:
    d = dict(base)
    for k in range(1,6):
        for i in range(k): d[ago(i)] = W(18000, rj, ru, cal)
        exp = 'warn' if (k>=3 or rj==935) else 'info'
        run(dict(d), f'砍 31% 第 {k} 天({tag}:被拒 {rj} 次/{ru:,} units/calls {cal})', exp)
    print()

print("【方向二】今天必須維持綠字")
real = json.loads(_FIXTURE.read_text(encoding='utf-8'))['days']
run(dict(real), '凍結快照原樣(高水位日、被拒 0)', 'info')

print("\n【方向四】腰斬 12,000 第 2、3 天仍然叫")
for k in (2,3):
    d = dict(base)
    for i in range(k): d[ago(i)] = W(12000,40,400,200)
    run(d, f'腰斬第 {k} 天', 'warn', want=f'已連續 {k} 天')

print("\n【比例門檻】同樣被拒 31 次,calls 不同意義不同")
for cal, exp in [(182,'info'), (50,'warn')]:
    d = dict(base); d[today] = W(26001, 31, 325, cal)
    run(d, f'被拒 31 次 / calls={cal}(rej/calls={31/cal*100:.0f}%)', exp)
d = dict(base); d[today] = W(26001, 31, 325, 1)
run(d, '被拒 31 次 / calls=1(合成測試常見;calls<50 不套比例)', 'info')
