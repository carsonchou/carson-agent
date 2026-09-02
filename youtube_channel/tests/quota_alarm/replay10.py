# -*- coding: utf-8 -*-
"""拿真帳本回放 10 天,比對「修前 / 只修 bug / 分預期內與真異常」三版的告警。

關鍵:每一天的 effective_limit 都用**當天為止**的帳本重算(把後面的日子切掉),
否則等於拿今天才知道的 26,001 去審 08-27,那天的牆其實是 19,645 —— 就是
memory yt-period-swap-integrity 的期間偷換。
"""
import sys, json, io, pathlib, tempfile, contextlib
sys.path.insert(0, 'scripts')
import quota_meter as qm, daily_health as dh

real = json.loads(pathlib.Path('STUDIO/quota_meter.json').read_text(encoding='utf-8'))
days = real.get('days') or {}
tmp = pathlib.Path(tempfile.mkdtemp()) / 'l.json'
qm.STATE = tmp

print(f"真帳本 {len(days)} 天\n")
hdr = f"{'配額日':<12}{'spent':>8}{'rej':>6}{'lim(當天)':>11}{'pct':>6}  {'判定':<10} warn 條目"
print(hdr); print('-' * len(hdr))

n_warn = 0
for d in sorted(days):
    upto = {k: v for k, v in days.items() if k <= d}
    tmp.write_text(json.dumps({'days': upto}), encoding='utf-8')
    qm._pacific_date = (lambda dd: (lambda *a, **k: dd))(d)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        dh.main()
    out = buf.getvalue().splitlines()
    b = days[d]
    lim = qm.effective_limit()
    sp = int(b.get('spent', 0) or 0); rj = int(b.get('rejected_calls', 0) or 0)
    quota_warns = [w for w in (out[-1][len('🔴 有異常: '):].split('、') if out[-1].startswith('🔴') else [])
                   if any(t in w for t in ('配額','被拒','unreliable','撞牆','帳本','牆'))]
    info = any('ℹ️' in l for l in out)
    kind = 'ℹ️ 預期內' if info and not quota_warns else ('🔴 真異常' if quota_warns else '—')
    n_warn += bool(quota_warns)
    print(f"{d:<12}{sp:>8,}{rj:>6}{lim:>11,}{sp/max(lim,1)*100:>5.0f}%  {kind:<10} {'、'.join(quota_warns) or '(無)'}")

print(f"\n10 天裡配額項產生 warn 的天數:{n_warn}")
