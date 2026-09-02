# -*- coding: utf-8 -*-
"""帳本讀不到 vs 帳本合法但很空 —— 前者必須叫,後者必須不叫。"""
import sys, json, io, pathlib, tempfile, contextlib, os, time
sys.path.insert(0, 'scripts')
import quota_meter as qm, daily_health as dh

real = json.loads(pathlib.Path('STUDIO/quota_meter.json').read_text(encoding='utf-8'))
tmpdir = pathlib.Path(tempfile.mkdtemp()); tmp = tmpdir / 'l.json'
qm.STATE = tmp
today = qm._pacific_date()

def run(write, label, expect, age_h=0):
    write(tmp)
    if tmp.exists() and age_h:
        t = time.time() - age_h * 3600
        os.utime(tmp, (t, t))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): dh.main()
    out = buf.getvalue().splitlines()
    got = 'warn' if out[-1].startswith('🔴') else 'info'
    print(f"\n### {label}  期望={expect} 實得={got} {'PASS' if got==expect else '**FAIL**'}")
    for l in out:
        if '配額' in l or 'ℹ️' in l or l.startswith('🔴 有異常') or l.startswith('✅'):
            print('   ' + l.strip()[:190])

print("=== 讀不到:必須叫,且不可說成「配額正常」 ===")
run(lambda p: p.write_text('{"days": {"2026-09-02": {"spent": 12', encoding='utf-8'),
    'D1 半截 JSON(排程 _save 寫到一半被讀走)', 'warn')
run(lambda p: p.write_text('\x00\x00\x00 garbage \xff', encoding='utf-8', errors='replace'),
    'D2 檔案內容壞掉', 'warn')
run(lambda p: p.unlink(missing_ok=True), 'D3 帳本檔不存在', 'warn')
run(lambda p: p.write_text(json.dumps(real), encoding='utf-8'),
    'D4 帳本合法但 24 小時沒被寫過(產線沒在打 API)', 'warn', age_h=30)

print("\n\n=== 不可誤報:合法帳本、剛換配額日 ===")
run(lambda p: p.write_text(json.dumps({'days': {today: {'spent': 172, 'calls': 9}}}), encoding='utf-8'),
    'E1 剛換配額日 spent=172(0%)—— 百分比低不是壞掉', 'info')
run(lambda p: p.write_text(json.dumps({'days': {}}), encoding='utf-8'),
    'E2 帳本真的是空的(檔案也幾乎沒內容)', 'info')
run(lambda p: p.write_text(json.dumps(real), encoding='utf-8'),
    'E3 今天的真帳本', 'info')
