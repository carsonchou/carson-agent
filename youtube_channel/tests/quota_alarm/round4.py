# -*- coding: utf-8 -*-
import sys, json, io, pathlib, tempfile, contextlib, datetime as dt
sys.path.insert(0, 'scripts')
import quota_meter as qm, daily_health as dh
tmp = pathlib.Path(tempfile.mkdtemp()) / 'l.json'; qm.STATE = tmp
today = qm._pacific_date(); T = dt.date.fromisoformat(today)
def ago(n): return (T - dt.timedelta(days=n)).isoformat()
W = lambda sp, rj, ru=0: {'spent': sp, 'rejected_calls': rj, 'rejected_units': ru, 'calls': 1}

def run(days, label, expect, want=None):
    tmp.write_text(json.dumps({'days': days}), encoding='utf-8')
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): dh.main()
    out = buf.getvalue().splitlines()
    got = 'warn' if out[-1].startswith('🔴') else 'info'
    ok = got == expect and (want is None or any(want in l for l in out))
    print(f"\n### {label}\n    期望={expect}{'/含「'+want+'」' if want else ''} 實得={got} {'PASS' if ok else '**FAIL**'}")
    for l in out:
        if 'YouTube 配額' in l or 'ℹ️' in l or '🔴 **' in l or l.startswith('🔴 有異常') or l.startswith('✅'):
            print('    ' + l.strip()[:180])

print("="*78); print("一、不再每次都說「第一次」")
for k in range(1, 5):
    d = {ago(i): W(19645, 300, 9000) for i in range(k)}
    run(d, f'連續第 {k} 天撞牆(帳本裡只有這些撞牆日)', 'warn')
run({today: W(19645, 300, 9000)}, '帳本裡真的只有今天一天', 'warn', want='沒有別的日子')
run({ago(1): {'spent': 25206, 'rejected_calls': 0, 'calls': 1}, today: W(12000, 40, 400)},
    '沒有前牆,但昨天成功花了 25,206 → 該用它當參考點', 'warn', want='帳本最高的單日成功花費')

print("\n"+"="*78); print("二、65% 帶寬:合法低牆不准變紅")
base = {ago(25): W(26001, 31, 325), ago(24): W(23341, 2, 850), ago(20): W(21858, 16, 16)}
for v, exp in [(19645, 'info'), (19500, 'info'), (17000, 'info'), (16800, 'warn'), (12000, 'warn')]:
    d = dict(base); d[today] = W(v, 20, 200)
    run(d, f'今天撞牆於 {v:,}(最高牆 26,001 的 {v/26001*100:.1f}%)', exp)

print("\n"+"="*78); print("三、重複告警帶天數")
d = dict(base)
for k in range(1, 4):
    for i in range(k): d[ago(i)] = W(12000, 40, 400)
    run(dict(d), f'腰斬第 {k} 天', 'warn', want=(f'已連續 {k} 天' if k >= 2 else None))
d2 = dict(base)
for i in range(17): d2[ago(i)] = W(12000, 40, 400)
run(d2, '腰斬第 17 天', 'warn', want='已連續 17 天')
