# -*- coding: utf-8 -*-
"""拿真帳本回放 10 天,比對「修前 / 只修 bug / 分預期內與真異常」三版的告警。

關鍵:每一天的 effective_limit 都用**當天為止**的帳本重算(把後面的日子切掉),
否則等於拿今天才知道的 26,001 去審 08-27,那天的牆其實是 19,645 —— 就是
memory yt-period-swap-integrity 的期間偷換。
"""
import sys, json, io, pathlib, tempfile, contextlib
sys.path.insert(0, 'scripts')
import quota_meter as qm, daily_health as dh

# 🔴 2026-09-03:這是**唯一**還讀活產線帳本的一支,而那是刻意的 ——
# 它本來就在 run_all 之外、本來就是手動跑,它的全部意義就是「拿產線回放」。
# 其餘四支已改讀 tests/quota_alarm/fixtures/ledger_snapshot.json(凍結快照)。
# 這裡失敗時要指名產線,不要讓人以為是測試壞了。
_LIVE = pathlib.Path('STUDIO/quota_meter.json')
try:
    real = json.loads(_LIVE.read_text(encoding='utf-8'))
except Exception as _e:
    print("🔴 讀不到/解不開**產線帳本** %s:%r" % (_LIVE, _e))
    print("   這是**產線問題,不是測試問題** —— replay10 的輸入就是活帳本。")
    print("   先看 STUDIO/quota_meter.json 與它的 .bak,再回來跑。")
    print("   (其餘四支用凍結快照,不受影響,可以照跑。)")
    raise SystemExit(2)
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
