#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""web_dashboard.py — 量化阿森決策中心（網頁版，Flask）。
分頁：🏠總覽 / 🧠決策 / 📋匯報 / 🎬倉庫 / 🟢已發布 / 👥人事 / 🎛控制台
"""
from __future__ import annotations
import argparse, glob, html, json, os, re, subprocess, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from flask import Flask, request, redirect

ROOT = Path(__file__).resolve().parent.parent
STUDIO = ROOT / "STUDIO"
REPORTS = STUDIO / "REPORTS"
OUT = ROOT / "output"
LOGS = ROOT / "logs"
LEDGER = STUDIO / "uploaded_ledger.json"
BUFFER = STUDIO / "scheduled_buffer.json"
DIRECTIVES = STUDIO / "boss_directives.json"
PENDING = STUDIO / "pending_decisions.json"
BOSS_DEC = STUDIO / "boss_decisions.json"
QUALITY = STUDIO / "quality_scores.json"
METRICS = STUDIO / "metrics_history.json"
HEADCOUNT = STUDIO / "headcount.json"
TW = timezone(timedelta(hours=8))
ACCESS_KEY = os.environ.get("DASHBOARD_KEY", "carson2026")
SUB_GOAL, VIEW_GOAL = 1000, 10_000_000

DEPTS = [
    ("①","長片部門"),("②","Shorts部門"),("③","創作靈感"),("④","頻道整理"),
    ("⑤","流量部門"),("⑥","宣傳部門"),("⑦","數據分析"),("⑧","社群留言"),
    ("⑨","審核上架"),("⑩","總監管"),("⑪","決策部門"),("⑫","回顧檢討"),
    ("⑬","人事部"),("⑭","財務部"),("⑮","縮圖CTR"),("⑯","競品情報"),
    ("⑰","美編部門"),("⑱","消息部門"),
]
D_DEF = {"①":3,"②":4,"③":2,"④":2,"⑤":2,"⑥":2,"⑦":2,"⑧":2,
         "⑨":3,"⑩":1,"⑪":2,"⑫":1,"⑬":2,"⑭":2,"⑮":2,"⑯":2,"⑰":2,"⑱":2}

app = Flask(__name__)

# ── helpers ──────────────────────────────────────────────
def _j(p, d):
    try: return json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else d
    except: return d

def _now(): return datetime.now(TW).strftime("%Y-%m-%d %H:%M:%S")
def _today(): return datetime.now(TW).strftime("%Y-%m-%d")
def _k(): return request.args.get("key","") or request.form.get("key","")
def _auth(): return _k() == ACCESS_KEY

def _queue():
    led = set(_j(LEDGER,{}).keys())
    return len(set(Path(p).stem for p in glob.glob(str(OUT/"*.mp4"))) - led)

def _today_count():
    td = _today()
    return sum(1 for p in glob.glob(str(OUT/"*.mp4"))
               if datetime.fromtimestamp(Path(p).stat().st_mtime,TW).strftime("%Y-%m-%d")==td)

def _pub_total(): return len(_j(LEDGER,{}))

def _buf():
    now = datetime.now(timezone.utc); c = 0
    for b in _j(BUFFER,[]):
        try:
            dt = datetime.strptime(b.get("publishAt",""),"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if dt > now: c += 1
        except: pass
    return c

def _running():
    MAP = [("produce_batch","🎬補產"),("daily_publish","🚀上傳"),("decision_dept","🧠決策"),
           ("daily_check","🩺大檢查"),("intel_dept","🔍競品"),("news_dept","📰時事"),
           ("quality_score","🎯評分"),("train_depts","📚進修"),("traffic_dept","📊流量")]
    return [l for kk,l in MAP if subprocess.run(["pgrep","-f",kk],capture_output=True).returncode==0]

def _cron_ok():
    try:
        r = subprocess.run(["crontab","-l"],capture_output=True,text=True)
        return r.returncode==0 and "run.sh" in r.stdout
    except: return False

def _tail(path, n=30):
    p = Path(path)
    if not p.exists(): return ""
    try: return "\n".join(p.read_text(encoding="utf-8",errors="replace").splitlines()[-n:])
    except: return ""

def _bg(script, args=None):
    LOGS.mkdir(exist_ok=True)
    log = open(LOGS/f"{script}.log","a",encoding="utf-8")
    subprocess.Popen([str(ROOT/"run.sh"),f"scripts/{script}.py"]+(args or[]),
                     stdout=log, stderr=log, cwd=str(ROOT))

def _strategy():
    if not REPORTS.exists(): return ""
    files = sorted(REPORTS.glob("*_決策.md"), reverse=True)
    if not files: return ""
    m = re.search(r"\*\*戰略判斷\*\*：(.+)", files[0].read_text(encoding="utf-8"))
    return m.group(1).strip() if m else ""

def _kpis():
    hist = _j(METRICS, [])
    if hist: return hist[-1].get("subs"), hist[-1].get("views")
    return None, None

def _qsum():
    q = _j(QUALITY, {}); s = q.get("summary",{})
    return s.get("pending",0), s.get("pass",0), s.get("reject",0), q.get("min_score",70)

def _att():
    td = _today()
    def rep(s): return (REPORTS/f"{td}_{s}.md").exists()
    return {"決策":rep("決策"),"大檢查":rep("大檢查"),"人事監察":rep("人事監察"),
            "回顧檢討":rep("回顧檢討"),"自動上架":rep("自動上架"),"營運匯報":rep("營運匯報")}

# ── CSS ──────────────────────────────────────────────────
CSS = """*{box-sizing:border-box;margin:0;padding:0}
body{background:#0b1224;color:#eef2ff;font-family:-apple-system,sans-serif;font-size:14px}
.hdr{background:#111a31;padding:10px 14px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #28395f;position:sticky;top:0;z-index:100}
.hdr h1{color:#ffd23f;font-size:17px}.hdr .ts{color:#8da3c4;font-size:11px}
.tabs{display:flex;overflow-x:auto;background:#111a31;border-bottom:1px solid #28395f;-webkit-overflow-scrolling:touch;scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tabs a{display:inline-block;padding:9px 12px;color:#8da3c4;text-decoration:none;font-size:12px;white-space:nowrap;border-bottom:2px solid transparent}
.tabs a.on{color:#ffd23f;border-bottom-color:#ffd23f}
.pad{padding:10px}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}
.card{background:#182543;border-radius:8px;padding:12px;text-align:center}
.num{font-size:28px;font-weight:bold;color:#ffd23f}
.lbl{color:#8da3c4;font-size:11px;margin-top:3px}
.box{background:#182543;border-radius:8px;padding:10px;margin-bottom:10px}
.box h3{color:#5b8cff;margin-bottom:6px;font-size:12px;font-weight:bold}
.tag{display:inline-block;background:#28395f;border-radius:5px;padding:2px 7px;margin:2px;font-size:12px}
.ok{color:#46d98a}.err{color:#ff6b6b}.warn{color:#ffd23f}
.log{background:#111a31;border-radius:6px;padding:8px;font-family:monospace;font-size:10px;white-space:pre-wrap;word-break:break-all;max-height:180px;overflow-y:auto;color:#8da3c4;margin-top:4px}
.g2b{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:10px}
.btn{background:#ffd23f;color:#0b1224;border-radius:7px;padding:11px;font-size:13px;font-weight:bold;text-decoration:none;display:block;text-align:center;border:none;cursor:pointer;width:100%;margin-bottom:6px}
.b2{background:#28395f;color:#eef2ff}
.msg{background:#46d98a22;color:#46d98a;border-radius:7px;padding:8px;margin-bottom:10px;text-align:center;font-size:13px}
.emsg{background:#ff6b6b22;color:#ff6b6b}
.sec{color:#ffd23f;font-size:13px;font-weight:bold;margin:12px 0 5px}
input[type=text],textarea,select{background:#182543;color:#eef2ff;border:1px solid #28395f;border-radius:6px;padding:7px;font-size:13px;width:100%;margin-bottom:7px}
textarea{height:70px;resize:vertical}
.dc{background:#182543;border-radius:8px;padding:12px;margin-bottom:10px}
.dc .q{color:#ffd23f;font-size:13px;font-weight:bold;margin-bottom:5px}
.dc .rec{color:#8da3c4;font-size:12px;margin-bottom:7px}
.dc .opts{display:flex;flex-wrap:wrap;gap:5px}
.dc .opts button{background:#5b8cff;color:#fff;border:none;border-radius:5px;padding:7px 12px;font-size:12px;cursor:pointer}
.rlist{list-style:none}.rlist li{padding:7px 10px;border-bottom:1px solid #28395f;font-size:12px;color:#8da3c4}
.rlist li.on{color:#ffd23f;background:#1a2840}
.rcont{font-size:11px;font-family:monospace;white-space:pre-wrap;color:#eef2ff;background:#111a31;padding:10px;border-radius:7px;max-height:360px;overflow-y:auto;margin-top:8px}
table{width:100%;border-collapse:collapse;font-size:12px}
th{background:#182543;color:#8da3c4;padding:5px 7px;text-align:left;font-size:11px}
td{padding:5px 7px;border-bottom:1px solid #1d2c4d;color:#eef2ff;font-size:12px}
.pb{background:#28395f;border-radius:3px;height:8px;overflow:hidden;margin:3px 0}
.pbf{background:#ffd23f;height:100%;border-radius:3px}
.pbg{background:#46d98a}"""

TABS = [("0","🏠総覧"),("1","🧠決策"),("2","📋匯報"),("3","🎬倉庫"),
        ("4","🟢已発布"),("5","👥人事"),("6","🎛控制台")]

def _page(t, body, msg="", err=""):
    k = _k()
    tl = "".join(f'<a href="/?key={k}&t={i}" class="{"on" if t==i else ""}">{n}</a>' for i,n in TABS)
    mh = f'<div class="msg">{msg}</div>' if msg else ""
    eh = f'<div class="msg emsg">{err}</div>' if err else ""
    return (f'<!DOCTYPE html><html lang="zh-TW"><head>'
            f'<meta charset=UTF-8><meta name=viewport content=width=device-width,initial-scale=1>'
            f'<title>決策中心</title><meta http-equiv=refresh content=120>'
            f'<style>{CSS}</style></head><body>'
            f'<div class=hdr><h1>⚙️量化阿森決策中心</h1><div class=ts>{_now()}</div></div>'
            f'<div class=tabs>{tl}</div>'
            f'<div class=pad>{mh}{eh}{body}</div>'
            f'<script>document.querySelector(".tabs .on")?.scrollIntoView({{block:"nearest",inline:"center"}});</script>'
            f'</body></html>')

# ── Tab: 總覽 ─────────────────────────────────────────────
def t_overview():
    q=_queue(); pt=_today_count(); pub=_pub_total(); buf=_buf()
    subs,views=_kpis(); strategy=_strategy(); running=_running(); cron_ok=_cron_ok()
    pend=_j(PENDING,[]); qp,qok,qrej,qmin=_qsum(); k=_k()
    net=None
    try:
        fin=STUDIO/"finance.json"
        if fin.exists(): net=_j(fin,{}).get("summary",{}).get("net")
    except: pass
    sp=min(100,int((subs or 0)/SUB_GOAL*100))
    vp=min(100,int((views or 0)/VIEW_GOAL*100))
    rh="".join(f'<span class=tag>{r}</span>' for r in running) or '<span class=tag>⏳待排程</span>'
    pa=(f'<div class="msg warn">📌 {len(pend)} 件待拍板 → '
        f'<a href="/?key={k}&t=1" style="color:#0b1224">去決策</a></div>') if pend else ""
    sd=f"{subs:,}" if subs else "—"; vd=f"{views:,}" if views else "—"
    nd=f"NT${net:,.0f}" if net is not None else "—"
    cc="ok" if cron_ok else "err"; ct="✅" if cron_ok else "❌"
    ops_log=html.escape(_tail(STUDIO/"ops_log.txt",15))
    cron_log=html.escape(_tail(LOGS/"cron.log",10))
    strat=html.escape(strategy) if strategy else "（待今日決策部門運行後顯示）"
    return (f'{pa}'
            f'<div class=g2>'
            f'<div class=card><div class=num>{q}</div><div class=lbl>📦庫存待上傳</div></div>'
            f'<div class=card><div class=num>{pt}</div><div class=lbl>🎬今日已產</div></div>'
            f'<div class=card><div class=num>{pub}</div><div class=lbl>✅累計上架</div></div>'
            f'<div class=card><div class=num>{buf}</div><div class=lbl>📅排程囤片</div></div>'
            f'</div>'
            f'<div class=g2>'
            f'<div class=card><div class=num>{sd}</div><div class=lbl>👥訂閱</div></div>'
            f'<div class=card><div class=num>{vd}</div><div class=lbl>👁總觀看</div></div>'
            f'<div class=card><div class=num>{nd}</div><div class=lbl>💰淨利</div></div>'
            f'<div class=card><div class=num>{qp}</div><div class=lbl>🎬倉庫待發</div></div>'
            f'</div>'
            f'<div class=box><h3>📈 YPP達標</h3>'
            f'訂閱 {sd}/{SUB_GOAL:,}'
            f'<div class=pb><div class="pbf" style="width:{sp}%"></div></div>'
            f'Shorts觀看 {vd}/{VIEW_GOAL//10000}萬'
            f'<div class=pb><div class="pbf pbg" style="width:{vp}%"></div></div></div>'
            f'<div class=box><h3>🧭 今日戰略</h3>'
            f'<div style="color:#ffd23f;font-size:12px">{strat}</div></div>'
            f'<div class=box><h3>⚡ 目前運行</h3>{rh}'
            f'<div style="margin-top:6px;font-size:11px">排程:<span class={cc}>{ct}</span>'
            f' 倉庫:達標{qok}/退件{qrej}/門檻{qmin}</div></div>'
            f'<div class=g2b>'
            f'<a href="/?key={k}&t=6" class="btn">🎛控制台</a>'
            f'<a href="/?key={k}&t=1" class="btn b2">🧠決策</a>'
            f'</div>'
            f'<div class=box><h3>📜工廠心跳</h3><div class=log>{ops_log}</div></div>'
            f'<div class=box><h3>📋Cron日誌</h3><div class=log>{cron_log}</div></div>')

# ── Tab: 決策 ─────────────────────────────────────────────
def t_decisions():
    k=_k(); pend=_j(PENDING,[])
    d=_j(DIRECTIVES,{"directives":[],"format_override":"auto","paused":False})
    dirs=d.get("directives",[]); fmt=d.get("format_override","auto"); paused=d.get("paused",False)
    ph=""
    for p in pend:
        q2=html.escape(p.get("question","")); rec=html.escape(p.get("recommendation",""))
        pid=html.escape(p.get("id",""))
        oh=""
        for o in p.get("options",[]):
            oe=html.escape(o)
            oh+=(f'<form method=post action=/decide style=display:inline>'
                 f'<input type=hidden name=key value="{k}">'
                 f'<input type=hidden name=pid value="{pid}">'
                 f'<input type=hidden name=choice value="{oe}">'
                 f'<input type=hidden name=question value="{q2}">'
                 f'<button type=submit>{oe}</button></form> ')
        ph+=(f'<div class=dc><div class=q>❓{q2}</div>'
             f'{"<div class=rec>💡建議："+rec+"</div>" if rec else ""}'
             f'<div class=opts>{oh}</div></div>')
    if not ph:
        ph='<div style="color:#8da3c4;font-size:12px;padding:6px">（目前沒有待拍板決策）</div>'
    dh="\n".join(
        f'<div style="padding:3px 0;border-bottom:1px solid #28395f;font-size:12px">'
        f'{i}. {html.escape(x)}</div>' for i,x in enumerate(dirs,1)
    ) or '<div style="color:#8da3c4;font-size:12px">（無指令，工廠照決策部門自行判斷）</div>'
    fo=[("auto","自動"),("short","主Shorts"),("long","主長片"),("both","並重")]
    fh=""
    for v,t2 in fo:
        cls="btn" if fmt==v else "btn b2"
        chk="✅" if fmt==v else ""
        fh+=f'<a href="/fmt?key={k}&v={v}" class="{cls}" style="flex:1;padding:8px;font-size:12px;margin:0">{chk}{t2}</a>'
    pt2="▶恢復全自動" if paused else "⏸暫停全自動"
    return (f'<div class=sec>📌 待拍板決策</div>{ph}'
            f'<div class=sec>② 主攻格式</div>'
            f'<div style="display:flex;gap:5px;margin-bottom:10px">{fh}</div>'
            f'<div class=sec>① 下指令給工廠</div>'
            f'<form method=post action=/directive>'
            f'<input type=hidden name=key value="{k}">'
            f'<textarea name=text placeholder="例：多做派網教學Shorts、停掉定投題材"></textarea>'
            f'<button type=submit class=btn>＋送出指令</button></form>'
            f'<div class=sec style="margin-top:12px">③ 目前生效指令</div>'
            f'<div class=box>{dh}</div>'
            f'<div class=g2b>'
            f'<a href="/directive?key={k}&clear=1" class="btn b2" '
            f'onclick="return confirm(\'清空所有指令？\')">🗑清空指令</a>'
            f'<a href="/fmt?key={k}&toggle_pause=1" class="btn b2" '
            f'onclick="return confirm(\'{pt2}？\')">{pt2}</a>'
            f'</div>')

# ── Tab: 匯報 ─────────────────────────────────────────────
def t_reports():
    k=_k(); sel=request.args.get("r",""); reps=[]
    if REPORTS.exists(): reps=sorted(REPORTS.glob("*.md"),reverse=True)
    lh="".join(
        f'<li class="{"on" if p.name==sel else ""}"><a href="/?key={k}&t=2&r={p.name}" '
        f'style="color:inherit;text-decoration:none">{html.escape(p.stem)}</a></li>'
        for p in reps[:40])
    ch=""
    target=REPORTS/sel if sel else (reps[0] if reps else None)
    if target and Path(target).exists():
        try: ch=f'<div class=rcont>{html.escape(Path(target).read_text(encoding="utf-8"))}</div>'
        except: ch='<div style=color:#ff6b6b>讀取失敗</div>'
    return f'<div class=box><h3>📂 報告（最近40份）</h3><ul class=rlist>{lh}</ul></div>{ch}'

# ── Tab: 倉庫 ─────────────────────────────────────────────
def t_library():
    k=_k(); q=_j(QUALITY,{}); pend=q.get("pending",[]); s=q.get("summary",{}); mn=q.get("min_score",70)
    sh=f'📦未發布{len(pend)}支 ✅通過{s.get("pass",0)} ⚠️退件{s.get("reject",0)} 門檻{mn}分'
    rows=""
    for it in pend[:30]:
        sc=it.get("score","—"); st=it.get("status","pass"); slug=it.get("slug","")
        tit=html.escape((it.get("title") or slug)[:35])
        sc_cls="ok" if st in("pass","published") else "err"
        st_txt="✅" if st=="pass" else "⚠️"
        rows+=(f'<tr><td class={sc_cls}>{sc}</td><td class={sc_cls}>{st_txt}</td><td>{tit}</td>'
               f'<td><a href="/reject?key={k}&slug={slug}" '
               f'onclick="return confirm(\'退件？\')" style="color:#ff6b6b;font-size:11px">退件</a></td></tr>')
    return (f'<div class=box><h3>🎬倉庫品質評分</h3>'
            f'<div style="color:#ffd23f;font-size:12px;margin-bottom:7px">{sh}</div>'
            f'<div class=g2b>'
            f'<a href="/action?key={k}&sc=quality_score&t=3" class="btn b2">🔄重新評分</a>'
            f'<a href="/action?key={k}&sc=quality_score&arg=--tidy&t=3" class="btn b2">🧹整理倉庫</a>'
            f'</div></div>'
            f'<table><tr><th>分</th><th>狀態</th><th>標題</th><th>操作</th></tr>'
            f'{rows or "<tr><td colspan=4 style=color:#8da3c4;text-align:center>（請先跑品質評分）</td></tr>"}'
            f'</table>')

# ── Tab: 已發布 ───────────────────────────────────────────
def t_published():
    k=_k(); q=_j(QUALITY,{}); pub=q.get("published",[]); led=_j(LEDGER,{})
    rows=""
    for i,it in enumerate(pub[:50]):
        tit=html.escape((it.get("title") or it.get("slug",""))[:35])
        v=it.get("views"); rt=it.get("retention"); sc=it.get("score","—"); vid=it.get("videoId","")
        vd=f"{int(v):,}" if v else "—"; rd=f"{rt:g}%" if rt else "—"
        lk=f'<a href="https://youtu.be/{vid}" style="color:#5b8cff">YT</a>' if vid else "—"
        rows+=f'<tr><td>{i+1}</td><td>{tit}</td><td>{vd}</td><td>{rd}</td><td>{sc}</td><td>{lk}</td></tr>'
    if not rows:
        for i,(vid,slug) in enumerate(list(led.items())[:50]):
            rows+=f'<tr><td>{i+1}</td><td>{html.escape(slug[:35])}</td><td>—</td><td>—</td><td>—</td><td><a href="https://youtu.be/{vid}" style="color:#5b8cff">YT</a></td></tr>'
    return (f'<div class=box><h3>🟢已發布（{len(led)}支）</h3></div>'
            f'<table><tr><th>#</th><th>標題</th><th>觀看</th><th>留存</th><th>評分</th><th>連結</th></tr>'
            f'{rows or "<tr><td colspan=6 style=color:#8da3c4>（無數據）</td></tr>"}'
            f'</table>')

# ── Tab: 人事 ─────────────────────────────────────────────
def t_hr():
    k=_k(); hc=_j(HEADCOUNT,D_DEF); att=_att()
    total=sum(hc.get(t,D_DEF.get(t,0)) for t,_ in DEPTS)
    arh="".join(
        f'<tr><td>{n}</td><td class="{"ok" if ok else "err"}">{"✅" if ok else "🕒"}</td></tr>'
        for n,ok in att.items())
    drh="".join(
        f'<tr><td>{t}</td><td>{n}</td><td>{hc.get(t,D_DEF.get(t,0))}</td></tr>'
        for t,n in DEPTS)
    errs=[]
    try:
        for ln in (STUDIO/"ops_log.txt").read_text(encoding="utf-8").splitlines()[-80:]:
            if any(kw in ln for kw in ("⚠️","FAIL","失敗","錯誤","FATAL")): errs.append(ln.strip())
    except: pass
    eh=("".join(f'<div style="color:#ff6b6b;font-size:11px">- {html.escape(e[:70])}</div>' for e in errs[-5:])
        or '<div class=ok>✅近期無異常</div>')
    return (f'<div class=box><h3>🗓今日出勤</h3><table>{arh}</table></div>'
            f'<div class=box><h3>🩺系統健康</h3>{eh}</div>'
            f'<div class=box><h3>🧑‍💼員額（總計{total}）</h3>'
            f'<table><tr><th>標號</th><th>部門</th><th>員額</th></tr>{drh}</table></div>'
            f'<a href="/action?key={k}&sc=hr_dept&t=5" class="btn b2">🔄跑人事監察</a>')

# ── Tab: 控制台 ───────────────────────────────────────────
def t_control():
    k=_k(); d=_j(DIRECTIVES,{"paused":False}); paused=d.get("paused",False)
    ACTS=[
        ("decision_dept","🧠立即決策","","b2"),
        ("produce_batch","🎬補產13支","--shorts 13 --long 0 --target 300","btn"),
        ("daily_publish","🚀上傳6支","--max 6","btn"),
        ("quality_score","🎯品質評分","","b2"),
        ("daily_check","🩺大檢查","","b2"),
        ("retro_dept","🔁回顧檢討","","b2"),
        ("traffic_dept","📊流量分析","","b2"),
        ("intel_dept","🔍競品情報","--no-learn","b2"),
    ]
    bh=""
    for sc,lbl,arg,cls in ACTS:
        url=f'/action?key={k}&sc={sc}&t=6' + (f'&arg={arg}' if arg else '')
        bh+=f'<a href="{url}" class="btn {cls}">{lbl}</a>\n'
    running=_running()
    rh="".join(f'<span class=tag>{r}</span>' for r in running) or '<span class=tag>⏳無腳本運行</span>'
    pt="▶恢復全自動" if paused else "⏸暫停全自動"
    cron_log=html.escape(_tail(LOGS/"cron.log",20))
    return (f'<div class=box><h3>⚡目前運行</h3>{rh}</div>'
            f'<div class=sec>🎛 操作</div>{bh}'
            f'<a href="/fmt?key={k}&toggle_pause=1&t=6" class="btn b2" '
            f'onclick="return confirm(\'{pt}？\')">{pt}</a>'
            f'<div class=box style="margin-top:10px"><h3>📋Cron日誌（最新20行）</h3>'
            f'<div class=log>{cron_log}</div></div>'
            f'<div class=box><h3>🔗快速連結</h3>'
            f'<a href="https://www.youtube.com/channel/UCqP5JQXlQR5ZDLtEiBt4kLA" class="btn b2" style="margin-bottom:6px">▶我的頻道</a>'
            f'<a href="https://studio.youtube.com/channel/UCqP5JQXlQR5ZDLtEiBt4kLA" class="btn b2">🎚YouTube Studio</a>'
            f'</div>')

# ── Routes ────────────────────────────────────────────────
@app.route("/")
def index():
    if not _auth(): return "<h2>403</h2>", 403
    t=request.args.get("t","0"); msg=request.args.get("msg",""); err=request.args.get("err","")
    fn={"0":t_overview,"1":t_decisions,"2":t_reports,"3":t_library,
        "4":t_published,"5":t_hr,"6":t_control}
    return _page(t, fn.get(t, t_overview)(), msg, err)

@app.route("/action")
def action():
    if not _auth(): return "403", 403
    sc=request.args.get("sc",""); arg=request.args.get("arg","")
    t=request.args.get("t","6"); k=_k()
    if sc: _bg(sc, arg.split() if arg else [])
    return redirect(f"/?key={k}&t={t}&msg=✅+{sc}+已啟動")

@app.route("/decide", methods=["POST"])
def decide():
    if not _auth(): return "403", 403
    k=_k(); pid=request.form.get("pid",""); choice=request.form.get("choice","")
    q2=request.form.get("question","")
    if pid and choice:
        bd=_j(BOSS_DEC,{}); ts=datetime.now(TW).strftime("%Y-%m-%d %H:%M")
        bd[pid]={"question":q2,"choice":choice,"ts":ts}
        BOSS_DEC.parent.mkdir(parents=True,exist_ok=True)
        BOSS_DEC.write_text(json.dumps(bd,ensure_ascii=False,indent=2),encoding="utf-8")
        pend=[x for x in _j(PENDING,[]) if x.get("id")!=pid]
        PENDING.write_text(json.dumps(pend,ensure_ascii=False,indent=2),encoding="utf-8")
        _bg("decision_dept")
    return redirect(f"/?key={k}&t=1&msg=✅已記錄：{choice}")

@app.route("/directive", methods=["POST","GET"])
def directive():
    if not _auth(): return "403", 403
    k=_k()
    if request.args.get("clear"):
        d=_j(DIRECTIVES,{"directives":[],"format_override":"auto","paused":False})
        d["directives"]=[]
        DIRECTIVES.parent.mkdir(parents=True,exist_ok=True)
        DIRECTIVES.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")
        return redirect(f"/?key={k}&t=1&msg=✅指令已清空")
    txt=request.form.get("text","").strip()
    if txt:
        d=_j(DIRECTIVES,{"directives":[],"format_override":"auto","paused":False})
        d.setdefault("directives",[]).append(txt)
        DIRECTIVES.parent.mkdir(parents=True,exist_ok=True)
        DIRECTIVES.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")
        _bg("decision_dept")
    return redirect(f"/?key={k}&t=1&msg=✅指令已送出")

@app.route("/fmt")
def fmt():
    if not _auth(): return "403", 403
    k=_k(); d=_j(DIRECTIVES,{"directives":[],"format_override":"auto","paused":False})
    if request.args.get("toggle_pause"):
        d["paused"] = not d.get("paused",False)
    else:
        v=request.args.get("v")
        if v: d["format_override"]=v
    DIRECTIVES.parent.mkdir(parents=True,exist_ok=True)
    DIRECTIVES.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")
    return redirect(f"/?key={k}&t={request.args.get('t','1')}&msg=✅已更新")

@app.route("/reject")
def reject():
    if not _auth(): return "403", 403
    k=_k(); slug=request.args.get("slug","")
    if slug:
        q=_j(QUALITY,{})
        for p in q.get("pending",[]):
            if p.get("slug")==slug: p["status"]="reject"; break
        QUALITY.parent.mkdir(parents=True,exist_ok=True)
        QUALITY.write_text(json.dumps(q,ensure_ascii=False,indent=2),encoding="utf-8")
        mp4=OUT/f"{slug}.mp4"
        if mp4.exists():
            rd=OUT/"_rejected"; rd.mkdir(exist_ok=True); mp4.rename(rd/f"{slug}.mp4")
    return redirect(f"/?key={k}&t=3&msg=✅已退件")

def main():
    global ACCESS_KEY
    p=argparse.ArgumentParser()
    p.add_argument("--port",type=int,default=8080)
    p.add_argument("--key",default=ACCESS_KEY)
    a=p.parse_args(); ACCESS_KEY=a.key; LOGS.mkdir(exist_ok=True)
    print(f"決策中心：http://0.0.0.0:{a.port}/?key={ACCESS_KEY}")
    app.run(host="0.0.0.0",port=a.port,debug=False)

if __name__=="__main__":
    main()
