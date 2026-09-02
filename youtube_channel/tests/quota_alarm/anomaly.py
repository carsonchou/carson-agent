# -*- coding: utf-8 -*-
"""降噪之後,真異常還叫不叫得出來 —— 這才是驗收條件。
底稿用真帳本(讓 effective_limit = 26,001 是真的),只改當天那一筆。"""
import sys, json, io, pathlib, tempfile, contextlib
sys.path.insert(0, 'scripts')
import quota_meter as qm, daily_health as dh

real = json.loads(pathlib.Path('STUDIO/quota_meter.json').read_text(encoding='utf-8'))
days = dict(real.get('days') or {})
tmp = pathlib.Path(tempfile.mkdtemp()) / 'l.json'; qm.STATE = tmp
today = qm._pacific_date()

def run(rec, label, expect):
    d = dict(days); d[today] = rec
    tmp.write_text(json.dumps({'days': d}), encoding='utf-8')
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): dh.main()
    out = buf.getvalue().splitlines()
    v = out[-1]
    got = 'warn' if v.startswith('🔴') else 'info'
    ok = 'PASS' if got == expect else '**FAIL**'
    print(f"\n### {label}  期望={expect} 實得={got} {ok}")
    for l in out:
        if '配額' in l or 'ℹ️' in l or '🔴 **' in l or l.startswith('🔴 有異常') or l.startswith('✅'):
            print('   ' + l.strip())

print("=== 真異常三類:必須仍然叫 ===")
run({'spent': 26001, 'rejected_calls': 935, 'unreliable': True},
    'A1 unreliable + 被拒 + 花得很滿(督導點名的自相矛盾案)', 'warn')
run({'spent': 0, 'rejected_calls': 42},
    'A2 spent=0 + 被拒 42 次(整日停權/雙機被吃光)', 'warn')
run({'spent': 9000, 'rejected_calls': 60},
    'A3 只花到 35% 就被拒 60 次(天花板變矮)', 'warn')

print("\n\n=== 預期內兩類:不該進 warn ===")
run({'spent': 25900, 'rejected_calls': 31}, 'B1 花到 100% 才被拒(正常營運)', 'info')
run({'spent': 25200, 'rejected_calls': 0}, 'B2 花到 97% 零被拒(全做成了)', 'info')

print("\n\n=== 檢查自己壞掉:仍須叫 ===")
_o = qm._load
qm._load = lambda: (_ for _ in ()).throw(NameError("name 'warns' is not defined"))
run({}, 'C1 重放原本被吞掉的 NameError', 'warn')
qm._load = _o
