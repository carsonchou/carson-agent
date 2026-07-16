#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""weekly_report_v2.py —【旗艦】台股全市場週報引擎 v2。

把 v1 只吐純文字 .md 的 subscription_report 升級成品牌化深色 PDF 週報(+ xlsx 附件)。
主體吃 data_hunter/state.json 全市場掃描(1001 檔 wave_top + 34 板塊 + 強弱 + 法人籌碼 +
真實訊號追蹤),體檢降為深度加值層。規格:
  - 商業篇 docs/ecommerce/REDESIGN_SPEC_business.md §2(8 sections / 資料源 / 誠信)
  - 產品篇 docs/ecommerce/REDESIGN_SPEC_product.md(視覺 token / 分頁 / 渲染管線)

誠信鐵則(生死線,與產線同一條):
  - 寫進 PDF 的每個績效數字都經 Provenance 綁來源欄位並入池(復用 product_factory.Provenance,
    不自造弱化版);組完各 section 後用嚴容差 gate 複驗,查無來源 → 該 section 降級為
    「資料異常已隱藏」卡(fail-closed),絕不炸整份報告、絕不編數字。
  - 任一資料源缺/空(休市/circuit_breaker/signals=[]) → 該 section 降級為明確「本週無資料」卡。
  - 「介紹≠推薦」:估值用位階條不用買賣燈;免責頁必印。

交付:load_send_list() 讀 STUDIO/ecommerce_subscribers.json(不存在回空+log,不硬依賴);
      send 一律 dry_run 預設,本引擎不寄信、不打外部 API。

用法:
  python weekly_report_v2.py                 # 用當前真實資料產一份完整週報 PDF+xlsx
  python weekly_report_v2.py --tier basic    # 只出基礎版 section
  python weekly_report_v2.py --out <dir>
驗證:python -m py_compile quant-service/ecommerce/weekly_report_v2.py
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

# ── 路徑 ─────────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent            # quant-service/ecommerce
QUANT = HERE.parent                                # quant-service
ROOT = QUANT.parent                                # repo root
DATA_HUNTER = QUANT / "data_hunter"
TWDATA = ROOT / "twdata"
STUDIO = ROOT / "youtube_channel" / "STUDIO"
SCRIPTS = ROOT / "youtube_channel" / "scripts"
MOCKUP = HERE / "mockup"

STATE = DATA_HUNTER / "state.json"
CHECKUP_FACTS = STUDIO / "stock_checkup_facts.json"
ADAPTIVE_CSV = TWDATA / "adaptive_per_stock.csv"
SUBSCRIBERS = STUDIO / "ecommerce_subscribers.json"
THEME_CSS = HERE / "report_theme.css"
OUT_DEFAULT = QUANT / "output" / "ecommerce_ready" / "weekly_v2"

# ── 復用產線既有溯源守門 + Provenance(不自造弱化版)──────────────────────────
sys.path.insert(0, str(SCRIPTS))
try:
    import fact_source_guard as FG  # noqa: E402
except Exception as exc:  # noqa: BLE001
    print(f"[weekly_v2] 致命:無法載入 fact_source_guard(溯源守門)——{exc}")
    raise SystemExit(2)
try:
    import config as CFG  # ecommerce/config.py（同目錄，sys.path 已含 HERE? 保險加入）
except Exception:  # noqa: BLE001
    sys.path.insert(0, str(HERE))
    import config as CFG  # noqa: E402

# Provenance 定義在 product_factory —— 直接復用同一個類別
sys.path.insert(0, str(HERE))
from product_factory import Provenance  # noqa: E402

TODAY = date.today()
DISCLAIMER = ("本內容為程式化的歷史數據彙整與教學,只做「事實介紹」,不是投資建議、不喊單、"
              "不報明牌;歷史數據非未來保證,投資有風險,據此進出盈虧自負。「介紹」不等於「推薦」。")


# ══════════════════════════════════════════════════════════════════════════════
#  小工具
# ══════════════════════════════════════════════════════════════════════════════
def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


_NUM_RE = re.compile(r"-?\d+\.?\d*")


def _pool_fg(prov: Provenance, s: str) -> None:
    """把 FG 百分比抽取器『會從 s 抽到的形式』也入池。

    FG._RX_PCT_ARABIC 的整數位只吃 \\d{1,4},對 ≥10000% 的台股怪物報酬(如 21051.3%)
    會截成 1051.3 這種幻影數 —— 那是 tokenizer 侷限,不是造假。用 FG 自己的抽取器
    對來源值/來源字串預抽並入池,讓 gate 對『合法大數』不誤殺,同時仍擋得下『憑空手打、
    不在任何來源字串也非任何來源欄位』的績效數(那種數字不會被 _pool 收進池)。
    """
    for m in FG._RX_PCT_ARABIC.finditer(s or ""):
        tok = m.group(1) or m.group(2)
        try:
            v = float(tok)
            prov.pool.add(abs(v)); prov.pool.add(abs(round(v, 1)))
        except (TypeError, ValueError):
            pass


def _pool(prov: Provenance, *items) -> None:
    """把「來源提供的」數字入池(數字直接入,字串抽出其中數字入,並補 FG-tokenized 形式)。

    只該對『真的來自來源欄位/來源字串』的值呼叫 —— 這正是 gate 的鑑別點:
    憑空手打、沒經過 _pool 的績效數字不會在池裡 → gate 擋下。
    """
    for it in items:
        if it is None:
            continue
        if isinstance(it, (int, float)):
            v = float(it)
            prov.pool.add(abs(v)); prov.pool.add(abs(round(v, 1)))
            _pool_fg(prov, f"{v}%"); _pool_fg(prov, f"{v:.2f}%")
        else:
            s = str(it)
            for m in _NUM_RE.findall(s):
                try:
                    v = float(m)
                    prov.pool.add(abs(v)); prov.pool.add(abs(round(v, 1)))
                except ValueError:
                    pass
            _pool_fg(prov, s)


def _bind(prov: Provenance, src: str, **fields) -> None:
    """具名綁定:入池(給 gate 用)+ 留存證(給稽核檔用),每個數字綁「來源檔:欄位」。

    A1 修(VERIFY_REPORT_phase3a):v1 只有 S7 寫 prov.records,其餘 7 段雖然有入池
    (所以 gate 全段有效、憑空造假擋得下),但**持久化的稽核檔只覆蓋 1/8 段** ——
    外部稽核者無法只憑該檔回查 S1–S6/S8。現在所有 section 一律走 _bind,
    存證檔可逐筆回答「這個數字來自哪個檔的哪個欄位」。

    A3 修:數值型直接存 value(不再全 null),稽核可程式化比對而不只靠文字。
    """
    for name, v in fields.items():
        if v is None:
            continue
        _pool(prov, v)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            prov.records.append({"field": name, "value": float(v), "text": None, "source": src})
        else:
            prov.records.append({"field": name, "value": None, "text": str(v), "source": src})


def _pct(v, digits=2, sign=True) -> tuple[str, str]:
    """回傳 (顯示字串, 台股色 class)。正=紅(pos) 負=綠(neg)。"""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—", ""
    s = f"{v:+.{digits}f}%" if sign else f"{v:.{digits}f}%"
    return s, ("pos" if v > 0 else "neg" if v < 0 else "")


def _gate_text_from_units(units: list[str]) -> str:
    joined = "\n".join(units)
    return re.sub(r"<[^>]+>", " ", joined)


def _degrade_unit(sid: str, title: str, reason: str) -> str:
    return (f'<div class="unit"><div class="sec-hd"><span class="sn">{sid}</span>'
            f'<h2>{_esc(title)}</h2></div>'
            f'<div class="card degrade"><div class="dt">本週此段無可用資料</div>'
            f'<div class="db">{_esc(reason)}</div></div></div>')


# ══════════════════════════════════════════════════════════════════════════════
#  資料載入(全部 fail-safe:缺檔回空 dict/list,不炸)
# ══════════════════════════════════════════════════════════════════════════════
def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def load_valuation_latest() -> dict:
    files = sorted(glob.glob(str(TWDATA / "fundamentals" / "valuation_*.json")))
    if not files:
        return {}
    try:
        d = json.loads(Path(files[-1]).read_text(encoding="utf-8"))
        return {"date": d.get("date"), "data": d.get("data", {}), "_file": Path(files[-1]).name}
    except Exception:  # noqa: BLE001
        return {}


def load_chips_week(days: int = 5) -> list[dict]:
    files = sorted(glob.glob(str(TWDATA / "chips" / "*.json")))[-days:]
    out = []
    for f in files:
        try:
            out.append(json.loads(Path(f).read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
    return out


def load_checkup() -> dict:
    try:
        return json.loads(CHECKUP_FACTS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"results": {}, "by_code": {}}


def load_adaptive() -> list[dict]:
    rows = []
    if not ADAPTIVE_CSV.exists():
        return rows
    with open(ADAPTIVE_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                r["a_net"] = float(r["a_net"]); r["a_win"] = float(r["a_win"])
            except Exception:  # noqa: BLE001
                continue
            rows.append(r)
    return rows


def build_name_map(state: dict, checkup: dict) -> dict:
    m = {}
    for r in state.get("wave_top", []) or []:
        if r.get("code"):
            m[str(r["code"])] = r.get("name", r["code"])
    for key in ("strong", "weak", "watch_long"):
        for r in state.get(key, []) or []:
            m.setdefault(str(r.get("code")), r.get("name", r.get("code")))
    for side in ("long", "short"):
        for r in (state.get("signals", {}) or {}).get(side, []) or []:
            m.setdefault(str(r.get("code")), r.get("name", r.get("code")))
    for grp in ("foreign_top", "trust_top", "consec_top", "retail_exit_top"):
        for r in (state.get("chips", {}) or {}).get(grp, []) or []:
            m.setdefault(str(r.get("code")), r.get("name", r.get("code")))
    for code, meta in (checkup.get("by_code", {}) or {}).items():
        m.setdefault(str(code), meta.get("name", code))
    return m


# ══════════════════════════════════════════════════════════════════════════════
#  Section 建造器 —— 每個回傳 dict(id,title,tier,units,prov,degraded)
#  units 為 HTML 片段清單(供分頁);第一個 unit 含 sec-hd。
# ══════════════════════════════════════════════════════════════════════════════
def _sec_head(sid: str, title: str, tier: str) -> str:
    tcls = "b" if tier == "basic" else ""
    tlabel = "基礎版" if tier == "basic" else "完整版"
    return (f'<div class="sec-hd"><span class="sn">{sid}</span><h2>{_esc(title)}</h2>'
            f'<span class="tier {tcls}">{tlabel}</span></div>')


def sec_S1(state: dict) -> dict:
    sid, title, tier = "S1", "市場溫度與體質", CFG.SECTION_TIERS["S1"]
    prov = Provenance()
    g = state.get("gauge", {}) or {}
    idx = state.get("index", {}) or {}
    if not g:
        return {"id": sid, "title": title, "tier": tier, "prov": prov, "degraded": True,
                "units": [_degrade_unit(sid, title, "state.json 無 gauge 溫度資料(可能休市或掃描未跑)。")]}
    temp = g.get("temperature")
    _bind(prov, "state.json:gauge+index",
          temperature=temp, breadth=g.get("breadth"), adr=g.get("adr"), nh=g.get("nh"),
          nl=g.get("nl"), avg_rsi=g.get("avg_rsi"), adv=g.get("adv"), dec=g.get("dec"),
          flat=g.get("flat"), index_chg=idx.get("chg"), index_price=idx.get("price"))
    label = g.get("label", "")
    idx_chg, idx_cls = _pct(idx.get("chg"))
    mkpos = max(0.0, min(100.0, float(temp) if temp is not None else 50.0))
    head = _sec_head(sid, title, tier)
    lead = ('<div class="lead">溫度計是全市場體質的綜合讀數(RSI/廣度/漲跌比/新高低/量能加權),'
            '只陳述體質、不判斷方向。</div>')
    kpis = (
        f'<div class="kpis">'
        f'<div class="kpi"><div class="k">市場溫度</div><div class="v">{_esc(f"{temp:.1f}") if temp is not None else "—"}'
        f'<small> {_esc(label)}</small></div></div>'
        f'<div class="kpi"><div class="k">站上20MA</div><div class="v">{_esc(g.get("breadth","—"))}<small>%</small></div></div>'
        f'<div class="kpi"><div class="k">漲跌比 ADR</div><div class="v">{_esc(g.get("adr","—"))}</div></div>'
        f'<div class="kpi"><div class="k">平均 RSI</div><div class="v">{_esc(g.get("avg_rsi","—"))}</div></div>'
        f'</div>')
    gauge = (f'<div class="gaugebar"><span class="mk" style="left:{mkpos:.0f}%"></span></div>'
             f'<div class="gaugescale"><span>0 冷</span><span>50 中性</span><span>100 熱</span></div>')
    detail = (
        f'<div class="block" style="margin-top:11px"><div class="metricrow">'
        f'漲 <b>{_esc(g.get("adv",0))}</b> ／ 跌 <b>{_esc(g.get("dec",0))}</b> ／ 平 <b>{_esc(g.get("flat",0))}</b>'
        f'　·　60日新高 <b>{_esc(g.get("nh","—"))}</b> ／ 新低 <b>{_esc(g.get("nl","—"))}</b><br>'
        f'大盤 {_esc(idx.get("name","0050"))} 收 <b>{_esc(idx.get("price","—"))}</b>,當日 '
        f'<span class="{idx_cls}">{idx_chg}</span>,趨勢 <b>{_esc(idx.get("trend","—"))}</b>'
        f'{"（站上年線）" if idx.get("above_yearline") else ""}</div></div>')
    html = f'<div class="unit">{head}{lead}{kpis}{gauge}{detail}</div>'
    return {"id": sid, "title": title, "tier": tier, "prov": prov, "degraded": False, "units": [html]}


def sec_S2(state: dict) -> dict:
    sid, title, tier = "S2", "板塊輪動熱力", CFG.SECTION_TIERS["S2"]
    prov = Provenance()
    secs = state.get("sectors", []) or []
    if not secs:
        return {"id": sid, "title": title, "tier": tier, "prov": prov, "degraded": True,
                "units": [_degrade_unit(sid, title, "state.json 無 sectors 板塊資料。")]}
    ranked = sorted(secs, key=lambda s: s.get("score", 0), reverse=True)
    top, bot = ranked[:5], ranked[-5:]

    def rows(items):
        out = []
        for s in items:
            chg, cls = _pct(s.get("avg_chg"))
            _bind(prov, f"state.json:sectors[{s.get('name','?')}]",
                  avg_chg=s.get("avg_chg"), bull_pct=s.get("bull_pct"), score=s.get("score"),
                  count=s.get("count"), inst_count=s.get("inst_count"), leader=s.get("leader"))
            bull = f"{s.get('bull_pct', 0):.0f}"
            score = f"{s.get('score', 0):.1f}"
            out.append(
                f'<tr><td class="l tkr">{_esc(s.get("name","—"))}</td>'
                f'<td class="{cls}">{chg}</td>'
                f'<td>{bull}%</td>'
                f'<td>{score}</td>'
                f'<td>{_esc(s.get("count","—"))}</td>'
                f'<td>{_esc(s.get("inst_count","—"))}</td>'
                f'<td class="l">{_esc(s.get("leader","—"))}</td></tr>')
        return "".join(out)

    head = _sec_head(sid, title, tier)
    lead = (f'<div class="lead">全 {len(secs)} 板塊依強弱分數排序,列最強 5 / 最弱 5;'
            f'完整 {len(secs)} 板塊附 xlsx 可自行排序篩選。</div>')
    thead = ('<thead><tr><th class="l">板塊</th><th>均漲跌</th><th>多方%</th><th>分數</th>'
             '<th>檔數</th><th>法人買</th><th class="l">領漲</th></tr></thead>')
    u_top = (f'<div class="unit">{head}{lead}<table class="grid">{thead}'
             f'<tbody>{rows(top)}</tbody></table></div>')
    u_bot = (f'<div class="unit"><div class="lead" style="color:var(--tx3)">最弱 5 板塊</div>'
             f'<table class="grid">{thead}<tbody>{rows(bot)}</tbody></table></div>')
    return {"id": sid, "title": title, "tier": tier, "prov": prov, "degraded": False, "units": [u_top, u_bot]}


def _strength_table(prov, rows_data, nmap, n, ascending=False, label=""):
    ranked = sorted(rows_data, key=lambda r: r.get("score", 0), reverse=not ascending)[:n]
    body = []
    for r in ranked:
        chg, cls = _pct(r.get("chg"))
        _bind(prov, f"state.json:wave_top[{r.get('code','?')}]",
              chg=r.get("chg"), rsi=r.get("rsi"), score=r.get("score"), price=r.get("price"))
        rsi = f"{r.get('rsi', 0):.1f}"
        score = f"{r.get('score', 0):.1f}"
        body.append(
            f'<tr><td class="l tkr">{_esc(r.get("name","—"))}<span class="code">{_esc(r.get("code",""))}</span></td>'
            f'<td class="l">{_esc(r.get("industry","—"))}</td>'
            f'<td>{_esc(r.get("price","—"))}</td>'
            f'<td class="{cls}">{chg}</td>'
            f'<td>{rsi}</td>'
            f'<td>{score}</td>'
            f'<td>{_esc(r.get("st","—"))}</td></tr>')
    thead = ('<thead><tr><th class="l">個股</th><th class="l">產業</th><th>價</th><th>漲跌</th>'
             '<th>RSI</th><th>強弱分</th><th>趨勢</th></tr></thead>')
    lead = f'<div class="lead" style="color:var(--tx3)">{label}</div>' if label else ""
    return f'<table class="grid">{thead}<tbody>{"".join(body)}</tbody></table>', lead


def sec_S3(state: dict, nmap: dict) -> dict:
    sid, title, tier = "S3", "全市場強弱榜", CFG.SECTION_TIERS["S3"]
    prov = Provenance()
    wave = state.get("wave_top", []) or []
    if not wave:
        return {"id": sid, "title": title, "tier": tier, "prov": prov, "degraded": True,
                "units": [_degrade_unit(sid, title, "state.json 無 wave_top 強弱榜資料。")]}
    head = _sec_head(sid, title, tier)
    lead = (f'<div class="lead">全市場 {len(wave)} 檔依強弱分數排序,報告本體列最強 15 / 最弱 15;'
            f'完整 {len(wave)} 檔附 xlsx 供 Excel/Sheets 排序篩選。</div>')
    t_up, _ = _strength_table(prov, wave, nmap, 15, ascending=False)
    t_dn, l_dn = _strength_table(prov, wave, nmap, 15, ascending=True, label="最弱 15(強弱分數末段)")
    u1 = f'<div class="unit">{head}{lead}{t_up}</div>'
    u2 = f'<div class="unit">{l_dn}{t_dn}</div>'
    return {"id": sid, "title": title, "tier": tier, "prov": prov, "degraded": False, "units": [u1, u2]}


def sec_S4(state: dict, chips_week: list[dict], nmap: dict) -> dict:
    sid, title, tier = "S4", "法人與籌碼週流向", CFG.SECTION_TIERS["S4"]
    prov = Provenance()
    if not chips_week:
        return {"id": sid, "title": title, "tier": tier, "prov": prov, "degraded": True,
                "units": [_degrade_unit(sid, title, "本週 twdata/chips 無日檔可加總。")]}
    # 加總本週各日 foreign_net → 排序
    agg: dict[str, float] = {}
    days = []
    for doc in chips_week:
        days.append(doc.get("date"))
        for code, v in (doc.get("data", {}) or {}).items():
            fn = v.get("foreign_net")
            if isinstance(fn, (int, float)):
                agg[code] = agg.get(code, 0) + fn
    if not agg:
        return {"id": sid, "title": title, "tier": tier, "prov": prov, "degraded": True,
                "units": [_degrade_unit(sid, title, "本週 chips 日檔皆無 foreign_net 欄位。")]}
    top = sorted(agg.items(), key=lambda kv: kv[1], reverse=True)[:12]
    bot = sorted(agg.items(), key=lambda kv: kv[1])[:8]
    maxabs = max(abs(top[0][1]), abs(bot[0][1])) or 1

    def cmp_rows(items):
        out = []
        for code, val in items:
            _bind(prov, f"twdata/chips[{code}]:foreign_net(本週日檔加總)", foreign_net_5d=val)
            w = min(100, abs(val) / maxabs * 100)
            cls = "" if val >= 0 else "red"
            vcls = "pos" if val > 0 else "neg"
            nm = nmap.get(str(code), str(code))
            out.append(
                f'<div class="row"><span class="lb">{_esc(nm)} <span class="code">{_esc(code)}</span></span>'
                f'<div class="track"><div class="fill {cls}" style="width:{w:.0f}%"></div></div>'
                f'<span class="vn {vcls}">{val:+,.0f}</span></div>')
        return "".join(out)

    # 連買榜(consec_top)
    consec = (state.get("chips", {}) or {}).get("consec_top", []) or []
    consec_rows = []
    for r in consec[:6]:
        _bind(prov, f"state.json:chips.consec_top[{r.get('code','?')}]",
              consec=r.get("consec"), net=r.get("net"))
        consec_rows.append(f'<div class="metricrow">{_esc(r.get("name","—"))} '
                           f'<span class="code">{_esc(r.get("code",""))}</span>:連買 '
                           f'<b>{_esc(r.get("consec","—"))}</b> 日({_esc(r.get("side",""))})</div>')
    head = _sec_head(sid, title, tier)
    lead = (f'<div class="lead">加總本週 {len([d for d in days if d])} 個交易日外資買賣超(單位:張),'
            f'排出本週外資淨買/淨賣。日期窗:{_esc(days[0])} ~ {_esc(days[-1])}。</div>')
    u1 = (f'<div class="unit">{head}{lead}'
          f'<div class="two"><div class="block"><div class="bt">本週外資淨買 Top</div>'
          f'<div class="cmp">{cmp_rows(top)}</div></div>'
          f'<div class="block"><div class="bt">本週外資淨賣 Top</div>'
          f'<div class="cmp">{cmp_rows(bot)}</div></div></div>')
    if consec_rows:
        u1 += (f'<div class="block" style="margin-top:11px"><div class="bt">法人連買天數榜</div>'
               f'{"".join(consec_rows)}</div>')
    u1 += "</div>"
    return {"id": sid, "title": title, "tier": tier, "prov": prov, "degraded": False, "units": [u1]}


def sec_S5(valdoc: dict, nmap: dict) -> dict:
    sid, title, tier = "S5", "估值位階雷達", CFG.SECTION_TIERS["S5"]
    prov = Provenance()
    data = (valdoc or {}).get("data", {}) or {}
    if not data:
        return {"id": sid, "title": title, "tier": tier, "prov": prov, "degraded": True,
                "units": [_degrade_unit(sid, title, "無 valuation 估值檔可用。")]}
    yields = [(c, v.get("dividend_yield"), v.get("pe"), v.get("pb")) for c, v in data.items()]
    yld = [(c, y, pe, pb) for c, y, pe, pb in yields if isinstance(y, (int, float)) and y > 0]
    pes = [v.get("pe") for v in data.values() if isinstance(v.get("pe"), (int, float)) and v["pe"] > 0]
    if not yld and not pes:
        return {"id": sid, "title": title, "tier": tier, "prov": prov, "degraded": True,
                "units": [_degrade_unit(sid, title, "valuation 檔內 pe/dividend_yield 全為 null。")]}
    yld.sort(key=lambda t: t[1], reverse=True)
    top_y = yld[:15]
    p25 = statistics.quantiles(pes, n=4)[0] if len(pes) >= 4 else (pes[0] if pes else 0)
    pmed = statistics.median(pes) if pes else 0
    p75 = statistics.quantiles(pes, n=4)[2] if len(pes) >= 4 else (pes[-1] if pes else 0)
    _bind(prov, "valuation:data[*].pe 分布(濾 null 且 pe>0)",
          pe_p25=p25, pe_median=pmed, pe_p75=p75, pe_sample_n=len(pes))

    body = []
    for c, y, pe, pb in top_y:
        _bind(prov, f"valuation:data[{c}]", dividend_yield=y, pe=pe, pb=pb)
        nm = nmap.get(str(c), str(c))
        body.append(
            f'<tr><td class="l tkr">{_esc(nm)}<span class="code">{_esc(c)}</span></td>'
            f'<td>{y:.2f}%</td>'
            f'<td>{_esc(f"{pe:.2f}") if isinstance(pe,(int,float)) else "—"}</td>'
            f'<td>{_esc(f"{pb:.2f}") if isinstance(pb,(int,float)) else "—"}</td></tr>')
    thead = '<thead><tr><th class="l">個股</th><th>殖利率</th><th>本益比</th><th>股價淨值比</th></tr></thead>'
    head = _sec_head(sid, title, tier)
    lead = (f'<div class="lead">濾除 null 後,列全市場現金殖利率 Top 15,並給全市場本益比分布'
            f'(共 {len(pes)} 檔有 PE)。只陳述位置,不判斷貴賤、不構成買賣建議。</div>')
    dist = (f'<div class="block" style="margin-bottom:11px"><div class="bt">全市場本益比分布</div>'
            f'<div class="metricrow">P25 <b>{p25:.1f}</b> 倍　·　中位數 <b>{pmed:.1f}</b> 倍　·　'
            f'P75 <b>{p75:.1f}</b> 倍</div></div>')
    u1 = (f'<div class="unit">{head}{lead}{dist}'
          f'<table class="grid">{thead}<tbody>{"".join(body)}</tbody></table></div>')
    return {"id": sid, "title": title, "tier": tier, "prov": prov, "degraded": False, "units": [u1]}


def sec_S6(state: dict) -> dict:
    sid, title, tier = "S6", "訊號追蹤 · 誠實成績單", CFG.SECTION_TIERS["S6"]
    prov = Provenance()
    tr = state.get("track", {}) or {}
    if not tr or tr.get("n_closed") is None:
        return {"id": sid, "title": title, "tier": tier, "prov": prov, "degraded": True,
                "units": [_degrade_unit(sid, title, "state.json 無 track 訊號追蹤資料。")]}
    n_closed = tr.get("n_closed", 0)
    wr = (tr.get("win_rate") or 0) * 100
    lwr = (tr.get("long_win_rate") or 0) * 100
    swr = (tr.get("short_win_rate") or 0) * 100
    avg_r = tr.get("avg_r")
    avg_ret = tr.get("avg_ret_pct")
    # 招牌數字:全部綁 state.json:track 的原始欄位(勝率/R/報酬皆由 track 聚合直出)
    _bind(prov, "state.json:track",
          n_closed=n_closed, win_rate_pct=wr, long_win_rate_pct=lwr, short_win_rate_pct=swr,
          avg_r=avg_r, avg_ret_pct=avg_ret, n_open=tr.get("n_open"))
    ret_s, ret_cls = _pct(avg_ret)
    head = _sec_head(sid, title, tier)
    lead = ('<div class="lead">這是招牌:程式訊號的<b>真實平倉戰績,含輸單、不挑不藏</b>——'
            '對比只曬贏單的老師,這裡連平均虧損都攤給你看。這不是投資建議,是誠實揭露。</div>')
    kpis = (
        f'<div class="kpis">'
        f'<div class="kpi"><div class="k">已平倉</div><div class="v">{_esc(n_closed)}<small> 筆</small></div></div>'
        f'<div class="kpi"><div class="k">總勝率</div><div class="v">{wr:.1f}<small>%</small></div></div>'
        f'<div class="kpi"><div class="k">平均 R 值</div><div class="v {"pos" if (avg_r or 0)>0 else "neg"}">'
        f'{_esc(f"{avg_r:+.2f}") if avg_r is not None else "—"}</div></div>'
        f'<div class="kpi"><div class="k">平均報酬</div><div class="v {ret_cls}">{ret_s}</div></div>'
        f'</div>')
    detail = (f'<div class="block" style="margin-top:11px"><div class="metricrow">'
              f'多方勝率 <b>{lwr:.1f}%</b>　·　空方勝率 <b>{swr:.1f}%</b>　·　'
              f'目前未平倉 <b>{_esc(tr.get("n_open","—"))}</b> 筆<br>'
              f'<span style="color:var(--tx3)">R 值 = 報酬 ÷ 進場風險;負值代表這批訊號目前是虧的——'
              f'我們照實呈現,不美化。</span></div></div>')
    # 近期逐筆(只列已平倉的真實結果)
    recent = [r for r in (tr.get("recent", []) or []) if r.get("result") not in (None, "open")][:6]
    rec_rows = ""
    if recent:
        body = []
        for r in recent:
            rs, rcls = _pct(r.get("ret_pct"))
            _bind(prov, f"state.json:track.recent[{r.get('code','?')}]",
                  ret_pct=r.get("ret_pct"), r=r.get("r"), entry=r.get("entry"), exit=r.get("exit"))
            body.append(
                f'<tr><td class="l tkr">{_esc(r.get("name","—"))}<span class="code">{_esc(r.get("code",""))}</span></td>'
                f'<td>{_esc(r.get("side","—"))}</td><td>{_esc(r.get("entry","—"))}</td>'
                f'<td>{_esc(r.get("exit","—"))}</td><td class="{rcls}">{rs}</td>'
                f'<td>{_esc(r.get("exit_reason","—"))}</td></tr>')
        thead = ('<thead><tr><th class="l">個股</th><th>方向</th><th>進</th><th>出</th>'
                 '<th>報酬</th><th>出場原因</th></tr></thead>')
        rec_rows = (f'<div class="block" style="margin-top:11px"><div class="bt">近期已平倉逐筆</div>'
                    f'<table class="grid">{thead}<tbody>{"".join(body)}</tbody></table></div>')
    html = f'<div class="unit">{head}{lead}{kpis}{detail}{rec_rows}</div>'
    return {"id": sid, "title": title, "tier": tier, "prov": prov, "degraded": False, "units": [html]}


def sec_S7(checkup: dict, window_days: int = 7) -> dict:
    sid, title, tier = "S7", "本週深度體檢個股", CFG.SECTION_TIERS["S7"]
    prov = Provenance()
    results = checkup.get("results", {}) or {}
    by_code = checkup.get("by_code", {}) or {}

    def _fact_ok(f):
        return (isinstance(f, dict) and f.get("key") and (f.get("claim") or f.get("summary"))
                and f.get("source") and f.get("data") not in (None, "", [], {}))

    def _parse(s):
        try:
            return datetime.strptime((s or "")[:10], "%Y-%m-%d").date()
        except Exception:  # noqa: BLE001
            return None
    since = TODAY - timedelta(days=window_days)
    # 收本週窗內、通過守門的體檢事實,依 code 分組
    by_stock: dict[str, list] = {}
    for key, f in results.items():
        if not _fact_ok(f):
            continue
        d = _parse(f.get("computed_at"))
        if d is not None and d < since:
            continue
        # key 形如 checkup_<type>__<code>[__<window>] —— code 一律在 index 1
        # (crash 為 checkup_crash__<code>__<crisis2008|covid2020|bear2022>,不能用 [-1])
        parts = key.split("__")
        if len(parts) < 2:
            continue
        code = parts[1]
        by_stock.setdefault(code, []).append(f)
    if not by_stock:
        return {"id": sid, "title": title, "tier": tier, "prov": prov, "degraded": True,
                "units": [_degrade_unit(sid, title,
                          f"本週窗({since}~{TODAY})內無新完成、且通過溯源守門的體檢事實。")]}
    units = []
    head = _sec_head(sid, title, tier)
    lead = (f'<div class="lead">本週體檢管線新覆蓋 {len(by_stock)} 檔;以下每則都逐字引用體檢引擎'
            f'算出的既有事實(含息還原/套牢/腰斬/崩盤三段/毛利/股利/估值位階),各附來源。</div>')
    first = True
    order = ["checkup_long_horizon", "checkup_annual_extremes", "checkup_underwater",
             "checkup_valuation_position", "checkup_three_way", "checkup_crash",
             "checkup_gross_margin", "checkup_dividend_history"]
    for code, facts in by_stock.items():
        name = by_code.get(code, {}).get("name", code)
        facts_sorted = sorted(facts, key=lambda f: order.index(f["key"].split("__")[0])
                              if f["key"].split("__")[0] in order else 99)
        rows = []
        for f in facts_sorted[:8]:
            txt = (f.get("claim") or f.get("summary") or "").strip()
            if not txt:
                continue
            # 體檢數字為既有事實 —— 把 fact.data 內數字入池(來源=fact_key),原樣引用 claim
            for val in FG._walk_numbers(f.get("data", {})):
                prov.pool.add(abs(val)); prov.pool.add(abs(round(val, 1)))
            _pool(prov, txt)
            # A2 修:不截斷。v1 存 txt[:60],51/71 筆被切斷、部分斷在數字中間
            #(如「卡瑪比率 0.」),PDF 渲染的是完整文字,但稽核檔的尾巴壞掉 →
            # 稽核者看到的像是壞數字。存證檔要能取信於人就不能自己先失真。
            prov.records.append({"field": f.get("key"), "value": None, "text": txt,
                                 "source": f.get("source", ""),
                                 "note": "體檢引擎既有事實(逐字引用)"})
            rows.append(f'<div class="metricrow">• {_esc(txt)}</div>')
        card = (f'<div class="card"><div class="kpis" style="margin-bottom:8px">'
                f'<div class="kpi" style="flex:none;text-align:left;min-width:0"><div class="k">個股</div>'
                f'<div class="v" style="font-size:17px">{_esc(name)} <span class="code" '
                f'style="font-size:11px;color:var(--tx3)">{_esc(code)}</span></div></div></div>'
                f'{"".join(rows)}</div>')
        if first:
            units.append(f'<div class="unit">{head}{lead}{card}</div>')
            first = False
        else:
            units.append(f'<div class="unit">{card}</div>')
    return {"id": sid, "title": title, "tier": tier, "prov": prov, "degraded": False, "units": units}


def sec_S8(adaptive: list[dict]) -> dict:
    sid, title, tier = "S8", "結構基準(月度輪替)", CFG.SECTION_TIERS["S8"]
    prov = Provenance()
    if not adaptive:
        return {"id": sid, "title": title, "tier": tier, "prov": prov, "degraded": True,
                "units": [_degrade_unit(sid, title, "無 adaptive_per_stock.csv 全市場回測快照。")]}
    n = len(adaptive)
    nets = [r["a_net"] for r in adaptive]
    med = statistics.median(nets)
    n_pos = len([x for x in nets if x > 0])
    pct_pos = n_pos / n * 100
    top = sorted(adaptive, key=lambda r: r["a_net"], reverse=True)[:5]
    _bind(prov, "twdata/adaptive_per_stock.csv(全樣本未濾)",
          sample_n=n, a_net_median=med, n_positive=n_pos, pct_positive=pct_pos)
    head = _sec_head(sid, title, tier)
    lead = ('<div class="lead">月度教育性基準(靜態快照,非即時、非可交易訊號):把趨勢策略無腦套'
            '全市場,真正該看的是<b>中位數</b>,別被最好幾檔騙走。</div>')
    kpis = (
        f'<div class="kpis">'
        f'<div class="kpi"><div class="k">樣本檔數</div><div class="v">{n}</div></div>'
        f'<div class="kpi"><div class="k">淨報酬中位數</div><div class="v {"pos" if med>0 else "neg"}">{med:+.1f}<small>%</small></div></div>'
        f'<div class="kpi"><div class="k">正報酬佔比</div><div class="v">{pct_pos:.1f}<small>%</small></div></div>'
        f'</div>')
    body = []
    for r in top:
        _bind(prov, f"twdata/adaptive_per_stock.csv[{r.get('code','?')}]",
              a_net=r["a_net"], a_win=r["a_win"])
        s, cls = _pct(r["a_net"])
        body.append(f'<tr><td class="l tkr">{_esc(r.get("name","—"))}<span class="code">{_esc(r.get("code",""))}</span></td>'
                    f'<td class="{cls}">{s}</td><td>{r["a_win"]:.1f}%</td></tr>')
    tbl = (f'<div class="block" style="margin-top:11px"><div class="bt">自適應淨報酬前 5(教育示例)</div>'
           f'<table class="grid"><thead><tr><th class="l">個股</th><th>淨報酬</th><th>勝率</th></tr></thead>'
           f'<tbody>{"".join(body)}</tbody></table></div>')
    html = f'<div class="unit">{head}{lead}{kpis}{tbl}</div>'
    return {"id": sid, "title": title, "tier": tier, "prov": prov, "degraded": False, "units": [html]}


# ══════════════════════════════════════════════════════════════════════════════
#  誠信 gate:組完各 section 後嚴容差複驗;查無來源 → 該 section 降級(fail-closed)
# ══════════════════════════════════════════════════════════════════════════════
def gate_or_degrade(section: dict) -> dict:
    """對非降級 section 跑 Provenance.gate;有查無來源的績效數字 → 整段換降級卡。"""
    if section.get("degraded"):
        return section
    text = _gate_text_from_units(section["units"])
    bad = section["prov"].gate(text, section["id"])
    if bad:
        vals = ", ".join(str(c["value"]) for c in bad[:4])
        section["units"] = [_degrade_unit(
            section["id"], section["title"],
            f"溯源守門擋下查無來源的數字({vals}）,為誠信 fail-closed 已隱藏本段(不出未溯源數字)。")]
        section["degraded"] = True
        section["gated_out"] = True
    return section


# ══════════════════════════════════════════════════════════════════════════════
#  HTML 組裝 + 分頁 + 渲染
# ══════════════════════════════════════════════════════════════════════════════
def _cover_html(state: dict, sections: list[dict], week_label: str, tier: str) -> str:
    g = state.get("gauge", {}) or {}
    n_sec = sum(1 for s in sections if not s.get("degraded"))
    wave_n = len(state.get("wave_top", []) or [])
    sect_n = len(state.get("sectors", []) or [])
    tr = state.get("track", {}) or {}
    b = CFG.BRAND
    sub = CFG.SUBSCRIPTION
    tinfo = sub["full"] if tier == "full" else sub["basic"]
    price = (f'訂閱:{sub["basic"]["name_zh"]} NT${sub["basic"]["ntd_month"]}/月　·　'
             f'{sub["full"]["name_zh"]} NT${sub["full"]["ntd_month"]}/月　·　'
             f'{sub["annual"]["name_zh"]} NT${sub["annual"]["ntd_year"]}/年')
    return f'''<section class="page cover">
  <div class="frame"></div>
  <div class="inner">
    <div class="runhead">
      <div class="brand"><span class="logo"></span><b>{_esc(b["name_zh"])}</b>&nbsp;{_esc(b["name_en"])}</div>
      <div class="vol"><div class="eyebrow">訂閱週報 · WEEKLY</div>
        <div style="margin-top:6px">{_esc(week_label)}</div>
        <div>{_esc(tinfo["name_zh"])}</div></div>
    </div>
    <div class="masthead">
      <div class="kick">全市場掃描 · 數據週報</div>
      <h1>台股全市場<br><span class="thin">週報</span></h1>
      <div class="sub">{_esc(b["tagline_zh"])}——主體吃全市場強弱掃描,體檢為深度加值層。
        每個數字都綁真實來源欄位,查無來源該段自動隱藏。</div>
      <div class="cover-stats">
        <div class="cstat"><div class="k">市場溫度</div><div class="v">{_esc(f"{g.get('temperature','—')}")}<small>{_esc(g.get('label',''))}</small></div></div>
        <div class="cstat"><div class="k">強弱榜覆蓋</div><div class="v">{wave_n}<small>檔</small></div></div>
        <div class="cstat"><div class="k">板塊</div><div class="v">{sect_n}<small>類</small></div></div>
        <div class="cstat"><div class="k">訊號追蹤</div><div class="v">{_esc(tr.get('n_closed','—'))}<small>已平倉</small></div></div>
      </div>
      <div class="cover-strip">
        <span class="badge">介紹 ≠ 推薦</span>
        <span class="txt">本報告為<b>歷史/當期數據彙整</b>,中性陳述、不喊買賣、不報明牌。含<b>真實訊號成績單(含輸單)</b>。</span>
      </div>
      <div class="price-line">{_esc(price)}　｜　平台:{_esc(sub["platform_tw"])}</div>
    </div>
    <div class="runfoot"><span>{_esc(b["name_zh"])} {_esc(b["name_en"])} · {_esc(b["product_zh"])}</span>
      <span class="disc">{_esc(week_label)}</span><span>封面 · 共 <span class="pagetotal"></span> 頁</span></div>
  </div>
</section>'''


def _page_template(brand: dict, product: str, week_label: str) -> str:
    return f'''<template id="pagetpl"><section class="page">
  <div class="frame"></div>
  <div class="inner">
    <div class="runhead">
      <div class="brand"><span class="logo"></span><b>{_esc(brand["name_zh"])}</b>&nbsp;{_esc(product)}</div>
      <div class="eyebrow">{_esc(week_label)}</div>
    </div>
    <div class="flow"></div>
    <div class="runfoot"><span>{_esc(brand["name_zh"])} {_esc(brand["name_en"])} · {_esc(product)}</span>
      <span class="disc">介紹 ≠ 推薦</span>
      <span><span class="pageno"></span> / <span class="pagetotal"></span></span></div>
  </div>
</section></template>'''


def _disclaimer_unit(state: dict, sections: list[dict]) -> str:
    srcs = ["data_hunter/state.json(全市場強弱掃描)",
            "twdata/chips/*.json(法人買賣超)",
            "twdata/fundamentals/valuation_*.json(估值:pe/殖利率/pb)",
            "youtube_channel/STUDIO/stock_checkup_facts.json(深度體檢,FinMind + Yahoo 含息還原)",
            "twdata/adaptive_per_stock.csv(全市場回測靜態快照,2026-06-12)"]
    degraded = [s["id"] for s in sections if s.get("degraded")]
    dnote = ("　本期自動降級/隱藏的段落:" + "、".join(degraded)) if degraded else "　本期 8 段全數呈現。"
    return (f'<div class="unit"><div class="disc-title">免責與資料來源</div>'
            f'<div class="disc-body">{_esc(DISCLAIMER)}<br><br>'
            f'本週報主體為<b>當期全市場掃描</b>與<b>歷史數據彙整</b>,不是即時可交易訊號;'
            f'S8 結構基準為 <b>2026-06-12 靜態回測快照</b>,僅供教育,不代表現在或未來。'
            f'S6 訊號追蹤為程式訊號的真實平倉紀錄(含輸單),為誠實揭露、非邀約跟單。'
            f'估值段(S5/S7)只陳述數據位置,<b>不判斷貴賤、不構成買賣建議</b>。</div>'
            f'<div class="disc-src"><b>資料來源</b>:' + "；".join(_esc(s) for s in srcs) + "。" + _esc(dnote) +
            f'　每個績效數字經溯源守門(fail-closed)驗證,查無來源的段落已自動隱藏。</div></div>')


_PAGINATE_JS = '''<script>
(function(){
  var src = document.getElementById('src');
  var host = document.getElementById('pages');
  var tpl = document.getElementById('pagetpl');
  var units = Array.prototype.slice.call(src.children);
  var pageNo = 1; // 封面=第1頁
  var cur=null, flow=null;
  function newPage(){
    var p = tpl.content.firstElementChild.cloneNode(true);
    host.appendChild(p);
    cur=p; flow=p.querySelector('.flow'); pageNo++;
    p.querySelector('.pageno').textContent = pageNo;
    return p;
  }
  newPage();
  for(var i=0;i<units.length;i++){
    var u = units[i];
    flow.appendChild(u);
    if(flow.scrollHeight > flow.clientHeight + 1){
      flow.removeChild(u);
      newPage();
      flow.appendChild(u);
      // 若單一 unit 仍超高(理論上罕見),就留在該頁不再無限開頁
    }
  }
  var total = host.querySelectorAll('.page').length;
  Array.prototype.forEach.call(document.querySelectorAll('.pagetotal'), function(e){ e.textContent = total; });
  src.parentNode.removeChild(src);
  window.__paginated__ = true;
})();
</script>'''


def build_html(state: dict, sections: list[dict], week_label: str, tier: str) -> str:
    css = THEME_CSS.read_text(encoding="utf-8")
    b = CFG.BRAND
    product = b["product_zh"]
    # 依 tier 過濾 section(basic 不含 full-only)
    visible = [s for s in sections
               if tier == "full" or CFG.SECTION_TIERS.get(s["id"]) == "basic"]
    unit_html = []
    for s in visible:
        unit_html.extend(s["units"])
    unit_html.append(_disclaimer_unit(state, visible))
    cover = _cover_html(state, visible, week_label, tier)
    pagetpl = _page_template(b, product, week_label)
    return f'''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<title>{_esc(b["name_zh"])} {_esc(product)} {_esc(week_label)}</title>
<style>{css}</style></head><body>
<div id="pages">{cover}</div>
{pagetpl}
<div id="src" style="position:absolute;left:-99999px;top:0;width:186mm">{"".join(unit_html)}</div>
{_PAGINATE_JS}
</body></html>'''


def render_pdf(html: str, out_pdf: Path) -> Path:
    """用 mockup/render.py 同款 Playwright 參數印 PDF(print_background/A4/繁中),
       並等分頁 JS 跑完(window.__paginated__)。"""
    from playwright.sync_api import sync_playwright
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    html_path = out_pdf.with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page()
        pg.goto(html_path.resolve().as_uri(), wait_until="networkidle")
        pg.wait_for_function("window.__paginated__ === true", timeout=15000)
        pg.emulate_media(media="print")
        # format="A4" 與 report_theme.css 的 @page{size:A4} 是雙保險:prefer_css_page_size
        # 只在 CSS 真的宣告頁面尺寸時才有東西可 prefer,否則**靜默退回 Letter** → 每頁溢
        # 50pt 擠出整頁空白(實測 full 24 頁裡 11 頁空白)。兩者都指 A4,拿掉任一都會復發。
        pg.pdf(path=str(out_pdf), format="A4", prefer_css_page_size=True, print_background=True,
               margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        br.close()
    return out_pdf


# ══════════════════════════════════════════════════════════════════════════════
#  xlsx 附件(§6:全 1001 檔強弱 + 34 板塊,深表頭/凍結/篩選/紅綠條件格式)
# ══════════════════════════════════════════════════════════════════════════════
def build_xlsx(state: dict, out_xlsx: Path) -> Path:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.formatting.rule import ColorScaleRule, DataBarRule
    BG, GOLD, UP, DN, MID = "0B0E14", "E3B93E", "E5484D", "2FB877", "F2F2F2"

    def head(ws, ncol):
        ws.row_dimensions[1].height = 26
        for c in range(1, ncol + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill = PatternFill(start_color=BG, end_color=BG, fill_type="solid")
            cell.font = Font(color=GOLD, bold=True, size=11)
            cell.alignment = Alignment(horizontal="center", vertical="center")

    wb = openpyxl.Workbook()
    ws = wb.active; ws.title = "全市場強弱"
    ws.append(["代號", "名稱", "產業", "價", "漲跌%", "RSI", "強弱分", "趨勢"])
    head(ws, 8)
    wave = sorted(state.get("wave_top", []) or [], key=lambda r: r.get("score", 0), reverse=True)
    for r in wave:
        ws.append([str(r.get("code", "")), r.get("name", ""), r.get("industry", ""),
                   r.get("price"), r.get("chg"), r.get("rsi"), r.get("score"), r.get("st", "")])
    last = len(wave) + 1
    if last >= 2:
        ws.freeze_panes = "C2"; ws.auto_filter.ref = f"A1:H{last}"
        for col, fmt in (("E", '0.00"%"'), ("F", "0.0"), ("G", "0.0")):
            for row in range(2, last + 1):
                ws[f"{col}{row}"].number_format = fmt
        # 漲跌%:台股 低綠→高紅
        ws.conditional_formatting.add(f"E2:E{last}", ColorScaleRule(
            start_type="min", start_color=DN, mid_type="num", mid_value=0, mid_color=MID,
            end_type="max", end_color=UP))
        ws.conditional_formatting.add(f"G2:G{last}", DataBarRule(start_type="min", end_type="max", color=GOLD))
    for i, w in enumerate([9, 16, 16, 8, 9, 8, 9, 8], start=1):
        ws.column_dimensions[chr(64 + i)].width = w

    ws2 = wb.create_sheet("板塊輪動")
    ws2.append(["板塊", "均漲跌%", "多方%", "分數", "檔數", "法人買", "領漲"])
    head(ws2, 7)
    secs = sorted(state.get("sectors", []) or [], key=lambda s: s.get("score", 0), reverse=True)
    for s in secs:
        ws2.append([s.get("name", ""), s.get("avg_chg"), s.get("bull_pct"), s.get("score"),
                    s.get("count"), s.get("inst_count"), s.get("leader", "")])
    l2 = len(secs) + 1
    if l2 >= 2:
        ws2.freeze_panes = "B2"; ws2.auto_filter.ref = f"A1:G{l2}"
        ws2.conditional_formatting.add(f"B2:B{l2}", ColorScaleRule(
            start_type="min", start_color=DN, mid_type="num", mid_value=0, mid_color=MID,
            end_type="max", end_color=UP))
        ws2.conditional_formatting.add(f"D2:D{l2}", DataBarRule(start_type="min", end_type="max", color=GOLD))
    for i, w in enumerate([18, 10, 8, 8, 7, 8, 20], start=1):
        ws2.column_dimensions[chr(64 + i)].width = w

    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_xlsx))
    return out_xlsx


# ══════════════════════════════════════════════════════════════════════════════
#  訂閱名冊介面(不硬依賴 Task #6 產物;不存在回空 + log)
# ══════════════════════════════════════════════════════════════════════════════
_TIER_RANK = {"basic": 1, "full": 2, "full_annual": 3, "unknown": 0}


def load_send_list(tier: str | None = None) -> list[dict]:
    """讀 STUDIO/ecommerce_subscribers.json 的寄送名單,回 [{email,name,tier,platform}]。

    ── 介面契約(名冊 schema 為金流層真相,本端遷就)──────────────────────────
    名冊由 quant-service/webhook/subscribers.py 維護與導出。schema =
    **扁平 dict**  {email_lower: {email,name,tier,platform,status,...}};active 的定義是
    entry["status"] == "active"(不是布林 active 欄位)。tier 分層權重見 webhook 的
    TIER_RANK(basic<full<full_annual);tier="full" 只回完整版及以上。

    實作:優先直接呼叫 webhook.subscribers.export_active(path, tier)(單一事實來源,
    格式永遠對得上);import 不到(webhook 套件缺依賴等)才走等價的本地讀取——刻意**不硬依賴**
    webhook 套件,名冊檔不存在/壞一律回空 + log,絕不炸。交付端據此 dry_run,不在此寄信。
    """
    if not SUBSCRIBERS.exists():
        print(f"[weekly_v2] 訂閱名冊尚未產生({SUBSCRIBERS.name}),回空清單(交付端會 no-op)。")
        return []
    # 首選:直接用金流層的 export_active(單一事實來源)
    try:
        if str(QUANT) not in sys.path:
            sys.path.insert(0, str(QUANT))
        from webhook.subscribers import export_active  # noqa: E402
        return export_active(SUBSCRIBERS, tier=tier)
    except Exception as exc:  # noqa: BLE001
        print(f"[weekly_v2] 直呼 export_active 失敗({type(exc).__name__}),改用本地等價讀取。")
    # 後備:本地實作同一契約(扁平 dict + status==active + tier 權重)
    try:
        book = json.loads(SUBSCRIBERS.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"[weekly_v2] 訂閱名冊解析失敗:{exc};回空清單。")
        return []
    if not isinstance(book, dict):
        return []
    want = _TIER_RANK.get(tier, 0) if tier else 0
    out = []
    for e in book.values():
        if not isinstance(e, dict) or e.get("status") != "active":
            continue
        if tier and _TIER_RANK.get(e.get("tier", "unknown"), 0) < want:
            continue
        out.append({"email": e.get("email", ""), "name": e.get("name", ""),
                    "tier": e.get("tier", "unknown"), "platform": e.get("platform", "")})
    out.sort(key=lambda r: (-_TIER_RANK.get(r["tier"], 0), r["email"].lower()))
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  主流程
# ══════════════════════════════════════════════════════════════════════════════
def generate_weekly(tier: str = "full", out_dir: Path | None = None) -> dict:
    out_dir = out_dir or OUT_DEFAULT
    state = load_state()
    valdoc = load_valuation_latest()
    chips_week = load_chips_week(5)
    checkup = load_checkup()
    adaptive = load_adaptive()
    nmap = build_name_map(state, checkup)

    sections = [
        sec_S1(state), sec_S2(state), sec_S3(state, nmap),
        sec_S4(state, chips_week, nmap), sec_S5(valdoc, nmap),
        sec_S6(state), sec_S7(checkup), sec_S8(adaptive),
    ]
    sections = [gate_or_degrade(s) for s in sections]

    d = state.get("date") or TODAY.isoformat()
    week_label = f"{d}(本週)"
    html = build_html(state, sections, week_label, tier)

    stamp = TODAY.isoformat()
    base = out_dir / f"weekly_{stamp}_{tier}"
    pdf = render_pdf(html, base.with_suffix(".pdf"))
    xlsx = build_xlsx(state, base.parent / f"weekly_{stamp}_全市場數據.xlsx")

    # provenance 存證(每個綁定數字 → 來源)
    # A3 修:只存「本 tier 真的有交付」的段落 —— 對齊 build_html 的可見性過濾。
    # v1 的 basic 存證檔含 71 筆 S7,但 basic 買家根本收不到 S7 → 稽核檔描述了未交付的內容。
    visible = [s for s in sections
               if tier == "full" or CFG.SECTION_TIERS.get(s["id"]) == "basic"]
    prov_records = []
    for s in visible:
        for rec in s["prov"].records:
            rec = dict(rec); rec["section"] = s["id"]; prov_records.append(rec)
    cover = sorted({r["section"] for r in prov_records})
    (base.parent / f"weekly_{stamp}_{tier}_provenance.json").write_text(
        json.dumps({"generated_at": stamp, "tier": tier,
                    "gate": "product_factory.Provenance.gate (reused, strict, fail-closed)",
                    "sections_covered": cover, "n_records": len(prov_records),
                    "records": prov_records}, ensure_ascii=False, indent=2), encoding="utf-8")

    status = [{"id": s["id"], "title": s["title"], "tier": CFG.SECTION_TIERS[s["id"]],
               "state": ("GATED" if s.get("gated_out") else "DEGRADED" if s.get("degraded") else "OK"),
               "units": len(s["units"])} for s in sections]
    return {"pdf": pdf, "xlsx": xlsx, "html": base.with_suffix(".html"),
            "tier": tier, "sections": status,
            "n_ok": sum(1 for x in status if x["state"] == "OK"),
            "send_list_n": len(load_send_list())}


def main() -> int:
    ap = argparse.ArgumentParser(description="台股全市場週報引擎 v2(旗艦)")
    ap.add_argument("--tier", choices=["basic", "full"], default="full")
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    args = ap.parse_args()
    res = generate_weekly(tier=args.tier, out_dir=Path(args.out))
    print(f"\n[weekly_v2] tier={res['tier']}  →  {res['pdf']}")
    print(f"[weekly_v2] xlsx 附件 → {res['xlsx']}")
    print(f"[weekly_v2] 8 sections 狀態:")
    for s in res["sections"]:
        print(f"    {s['id']} [{s['tier']:5}] {s['state']:8} · {s['units']} unit · {s['title']}")
    print(f"[weekly_v2] OK {res['n_ok']}/8　訂閱名冊 {res['send_list_n']} 人(dry-run,不寄)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
