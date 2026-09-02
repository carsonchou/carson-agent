# -*- coding: utf-8 -*-
"""第三輪驗收:三個方向缺一不可。"""
import sys, json, io, pathlib, tempfile, contextlib
sys.path.insert(0, 'scripts')
import quota_meter as qm, daily_health as dh
real = json.loads(pathlib.Path('STUDIO/quota_meter.json').read_text(encoding='utf-8'))['days']
tmp = pathlib.Path(tempfile.mkdtemp()) / 'l.json'; qm.STATE = tmp
today = qm._pacific_date()

def run(days, label, expect):
    tmp.write_text(json.dumps({'days': days}), encoding='utf-8')
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): dh.main()
    out = buf.getvalue().splitlines()
    got = 'warn' if out[-1].startswith('🔴') else 'info'
    print(f"\n### {label}\n    期望={expect} 實得={got} {'PASS' if got==expect else '**FAIL**'}")
    for l in out:
        if 'YouTube 配額' in l or 'ℹ️' in l or '🔴 **' in l or l.startswith('🔴 有異常') or l.startswith('✅'):
            print('    ' + l.strip()[:175])

W = lambda sp, rj, ru=0: {'spent': sp, 'rejected_calls': rj, 'rejected_units': ru, 'calls': 1}

print("=" * 78)
print("方向一:08-27 的 bucket 放進【已經有前牆】的帳本 —— 現在漏掉的那個")
run({'2026-08-20': W(23341, 2, 850), today: W(19645, 935, 45491)},
    '08-27 原封不動(spent 19,645 / 被拒 935 / 浪費 45,491),前牆 23,341', 'warn')
run({'2026-08-20': W(19645, 3, 100), today: W(19645, 935, 45491)},
    '同上但前牆與今天等高(19,645)—— 牆沒變矮,只有沒退避', 'warn')
for n in (1, 31, 935, 5000):
    run({'2026-08-20': W(19645, 3, 100), today: W(19645, n)},
        f'spent 等於前牆,只改被拒次數 = {n}(rejected_units 未記)',
        'warn' if n > 100 else 'info')

print("\n" + "=" * 78)
print("方向二:今天的活樣本必須維持綠字(不准製造誤報)")
run(dict(real), '真帳本原樣(今天 24,571 / 被拒 0)', 'info')
d = dict(real); d[today] = {'spent': 24800, 'rejected_calls': 0, 'calls': 143}
run(d, '推到 24,800(逼過 95%)仍須綠字', 'info')
d = dict(real); d[today] = {'spent': 21858, 'rejected_calls': 16, 'rejected_units': 16, 'calls': 1}
run(d, '08-29 那天(16 次 × 1 unit,全天浪費 0.06%)—— 驗證員判為門檻假象,應綠', 'info')

print("\n" + "=" * 78)
print("方向三:持續性腰斬第二天、第三天必須繼續叫")
base = {'2026-08-25': W(26001, 31, 325)}
for k, day in enumerate(['2026-08-26', '2026-08-27'], 1):
    base[day] = W(12000, 40, 400)
    d = dict(base); d[today] = W(12000, 40, 400)
    run(d, f'配額腰斬到 12,000 的第 {k+1} 天(前面已有 {k} 天同樣爛)', 'warn')
