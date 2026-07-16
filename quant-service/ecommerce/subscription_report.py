# -*- coding: utf-8 -*-
"""
subscription_report.py — 訂閱報告引擎(S1 台灣訂閱主柱)

把工作室既有的兩條數據管線，組成訂閱者拿得到的兩種內容：

  1) 週報 generate_weekly_report()
     來源：youtube_channel/STUDIO/stock_checkup_facts.json(個股體檢事實庫)
     內容：彙整本週覆蓋個股的體檢事實(長期報酬/年度極值/估值位階/毛利率/
           股利/營收EPS趨勢/崩盤韌性…)。每一項都直接引用事實庫既有的 claim
           字串與 source，程式本身「不產生任何新數字」。

  2) 每日掃描 generate_daily_scan()
     來源：quant-service/data_hunter/state.json(全市場強弱掃描)
     內容：市場溫度、板塊輪動、做多/做空訊號、三大法人動向。復用 data_hunter
           /daily_post.py 已驗證的排版 helper，不重造格式。

交付 send_report()：復用 webhook_server._send_report_email 的 smtplib 寫法寄信，
或用 tg_magnet 同款 sendMessage 私訊；預設 dry_run=True，不會真的寄給任何人。

誠信紅線(對齊產線):
  * 「介紹≠推薦」— 只陳述事實與數據，不含任何買賣建議字樣。
  * 溯源守門(fail-closed)— 缺 source / claim / data 的事實一律丟掉(_fact_ok)。
  * 本引擎不捏造統計、不寫「回測顯示…」推論；週報數字全部逐字取自事實庫。

用法：
  python subscription_report.py --weekly        # 產一份範例週報到 output/
  python subscription_report.py --daily         # 產一份範例每日掃描到 output/
  python subscription_report.py --both          # 兩份都產
  # 交付一律走函式(send_report)，預設 dry_run，不在 CLI 直接觸發真實發送。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import smtplib
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

HERE = Path(__file__).resolve().parent            # quant-service/ecommerce/
QS = HERE.parent                                  # quant-service/
ROOT = QS.parent                                  # carson-agent/
DATA_HUNTER = QS / "data_hunter"
STUDIO = ROOT / "youtube_channel" / "STUDIO"

CHECKUP_FACTS = STUDIO / "stock_checkup_facts.json"
CHECKUP_STATE = STUDIO / "stock_checkup_daily_state.json"
SCAN_STATE = DATA_HUNTER / "state.json"
OUTPUT_DIR = QS / "output" / "subscription"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 統一免責(對外文案結尾)。與事實庫 disclaimer 同調。
DISCLAIMER = ("本內容為程式化的歷史數據彙整與教學，只做「事實介紹」，"
              "不是投資建議、不喊單、不報明牌；歷史數據非未來保證，"
              "投資有風險，據此進出盈虧自負。")

# 週報想呈現的體檢維度 → 顯示標題(有就列，沒有就跳過；不硬湊)。
_CHECKUP_SECTIONS = [
    ("checkup_long_horizon", "長期含息還原總報酬"),
    ("checkup_annual_extremes", "最猛一年 vs 最慘一年"),
    ("checkup_underwater", "套牢/回本體檢"),
    ("checkup_valuation_position", "目前估值位階"),
    ("checkup_gross_margin", "毛利率趨勢"),
    ("checkup_revenue_trend", "營收趨勢"),
    ("checkup_eps_trend", "EPS 趨勢"),
    ("checkup_dividend_history", "股利發放"),
    ("checkup_three_way", "三種買法對照"),
    ("checkup_crash", "崩盤時的韌性"),
]


# ── 溯源守門(fail-closed) ─────────────────────────────────────────────────
def _fact_ok(fact: dict) -> bool:
    """一則體檢事實要能出現在對外報告，必須同時有：
       key、可讀的 claim/summary、非空 data、明確 source。任一缺 → 丟掉。
       這是「查無憑據就拿掉」的結構性守門，讓報告不可能夾帶捏造數字。"""
    if not isinstance(fact, dict):
        return False
    if not fact.get("key"):
        return False
    if not (fact.get("claim") or fact.get("summary")):
        return False
    if not fact.get("source"):
        return False
    data = fact.get("data")
    if data in (None, "", [], {}):
        return False
    return True


def _fact_text(fact: dict) -> str:
    """對外只吐事實庫既有字串，本引擎不改寫、不加工任何數字。"""
    return (fact.get("claim") or fact.get("summary") or "").strip()


# ── 資料載入 ───────────────────────────────────────────────────────────────
def _load_facts() -> dict:
    if not CHECKUP_FACTS.exists():
        return {}
    return json.loads(CHECKUP_FACTS.read_text(encoding="utf-8"))


def _load_checkup_history() -> list:
    if not CHECKUP_STATE.exists():
        return []
    st = json.loads(CHECKUP_STATE.read_text(encoding="utf-8"))
    return st.get("history", [])


def _parse_day(s: str):
    try:
        return datetime.strptime((s or "")[:10], "%Y-%m-%d").date()
    except Exception:
        return None


# ── 週報 ───────────────────────────────────────────────────────────────────
def generate_weekly_report(as_of: str | None = None, window_days: int = 7) -> dict:
    """彙整本週(as_of 起回推 window_days)覆蓋到的個股體檢事實，組成訂閱週報。

    回傳 dict：
      { "kind": "weekly", "title", "as_of", "content"(純文字/markdown 相容),
        "meta": { "symbols", "n_facts", "n_dropped", "sources" } }

    內容全部逐字引用事實庫 claim + source；缺憑據的事實由 _fact_ok 濾除。
    """
    facts_doc = _load_facts()
    results = facts_doc.get("results", {}) or {}
    as_of_day = _parse_day(as_of) or _parse_day(facts_doc.get("as_of")) or date.today()
    since = as_of_day - timedelta(days=window_days)

    # 依個股彙整；只收本週窗內、且通過溯源守門的事實。
    by_symbol: dict[str, dict] = {}
    n_facts = 0
    n_dropped = 0
    sources: set[str] = set()
    for key, fact in results.items():
        if not _fact_ok(fact):
            n_dropped += 1
            continue
        cday = _parse_day(fact.get("computed_at"))
        if cday is not None and cday < since:
            continue                                  # 不在本週窗內
        sym = fact.get("symbol") or "?"
        prefix = key.split("__")[0]
        by_symbol.setdefault(sym, {}).setdefault(prefix, []).append(fact)
        sources.add(fact.get("source", ""))
        n_facts += 1

    lines: list[str] = []
    title = f"量化阿森｜個股體檢週報（{as_of_day.isoformat()}）"
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"本週體檢管線共覆蓋 {len(by_symbol)} 檔個股、{n_facts} 組數據事實。"
                 "以下每一項都是程式從公開財報/還原股價算出的「歷史事實」，"
                 "只做數據介紹、不含任何買賣建議。")
    lines.append("")

    if not by_symbol:
        lines.append("（本週窗內沒有通過溯源守門的體檢事實，無可彙整內容。）")
    for sym in sorted(by_symbol.keys()):
        buckets = by_symbol[sym]
        lines.append(f"## {sym}")
        for prefix, heading in _CHECKUP_SECTIONS:
            for fact in buckets.get(prefix, []):
                txt = _fact_text(fact)
                if not txt:
                    continue
                lines.append(f"- 【{heading}】{txt}")
        lines.append("")

    # 本週新進體檢個股(來自每日排程 state，非數字類，純排程紀錄)
    hist = [h for h in _load_checkup_history()
            if (_parse_day(h.get("date")) or date.min) >= since]
    if hist:
        lines.append("## 本週新完成體檢的個股")
        for h in hist:
            lines.append(f"- {h.get('date')}｜{h.get('code')} {h.get('name')}"
                         f"（{h.get('reason','')}）")
        lines.append("")

    lines.append("---")
    lines.append(f"資料來源：{'；'.join(sorted(s for s in sources if s)) or '事實庫'}")
    lines.append(DISCLAIMER)

    return {
        "kind": "weekly",
        "title": title,
        "as_of": as_of_day.isoformat(),
        "content": "\n".join(lines),
        "meta": {
            "symbols": sorted(by_symbol.keys()),
            "n_facts": n_facts,
            "n_dropped": n_dropped,
            "sources": sorted(s for s in sources if s),
        },
    }


# ── 每日掃描 ───────────────────────────────────────────────────────────────
def _import_daily_post():
    """把 data_hunter 掛上 sys.path 後 import daily_post，復用其排版 helper。
       daily_post 對 scan/snapshot 都是延遲 import，故此 import 無副作用。"""
    if str(DATA_HUNTER) not in sys.path:
        sys.path.insert(0, str(DATA_HUNTER))
    import daily_post  # noqa: E402
    return daily_post


def generate_daily_scan(as_of: str | None = None) -> dict:
    """把 data_hunter/state.json 組成訂閱者版「當日全市場掃描」。

    復用 daily_post 已驗證的 helper(build_hook / 板塊 / 訊號 / 籌碼 / 追蹤)，
    只換掉頻道 CTA 段，改成訂閱者語氣。內容全來自 state.json，程式不新增數字。
    """
    if not SCAN_STATE.exists():
        return {"kind": "daily", "title": "每日掃描", "as_of": as_of or "",
                "content": "（找不到 data_hunter/state.json，請先跑一次 scan.py。）",
                "meta": {"ok": False}}

    s = json.loads(SCAN_STATE.read_text(encoding="utf-8"))
    dp = _import_daily_post()
    g = s.get("gauge", {})
    idx = s.get("index", {})
    d = s.get("date", as_of or str(date.today()))

    L: list[str] = []
    title = f"量化阿森｜台股每日掃描（{d}）"
    L.append(f"# {title}")
    L.append("")
    L.append(dp.build_hook(s))
    L.append("")
    L.append("## 市場溫度計")
    L.append(f"- 溫度 {g.get('temperature','?')} 度（{g.get('label','')}）"
             f"｜平均RSI {g.get('avg_rsi','?')}｜站上20MA {g.get('breadth','?')}%")
    L.append(f"- 漲 {g.get('adv',0)}／跌 {g.get('dec',0)}／平 {g.get('flat',0)}"
             f"｜漲跌比(ADR) {g.get('adr','?')}"
             f"｜60日新高{g.get('nh','?')}/新低{g.get('nl','?')}")
    L.append(f"- 大盤 0050 {dp._arrow(idx.get('chg'))}，趨勢 {idx.get('trend','?')}"
             f"{'（站上年線）' if idx.get('above_yearline') else ''}")
    L.append("")

    top_line, bot_line = dp._sector_lines(s)
    if top_line:
        L.append("## 板塊輪動")
        L.append(f"- {top_line}")
        L.append(f"- {bot_line}")
        L.append("")

    L.append("## 今日訊號清單（程式量化，非投資建議）")
    L += dp._signal_lines(s, per_side=5)
    L.append("")

    chips = dp._chip_lines(s)
    if chips:
        L.append("## 三大法人動向")
        L += chips
        L += dp._margin_lines(s)
        L.append("")

    tl = dp._track_line(s)
    if tl:
        L.append(tl)
        L.append("")

    L.append("---")
    L.append(f"資料來源：{s.get('source','data_hunter 全市場掃描')}"
             f"（{s.get('mode','')}）")
    L.append(DISCLAIMER)

    sig = s.get("signals", {})
    return {
        "kind": "daily",
        "title": title,
        "as_of": d,
        "content": "\n".join(L),
        "meta": {
            "ok": bool(s.get("ok")),
            "temperature": g.get("temperature"),
            "n_long": len(sig.get("long", [])),
            "n_short": len(sig.get("short", [])),
            "source": s.get("source"),
        },
    }


# ── 交付：email / telegram(預設 dry_run，不真的送) ──────────────────────────
def _send_email(to_email: str, subject: str, body: str) -> dict:
    """復用 webhook_server._send_report_email 同款 smtplib 寫法。
       缺 SMTP 憑證 → 不送，回報 skipped(不視為錯誤)。"""
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    if not smtp_user or not smtp_pass:
        return {"channel": "email", "sent": False, "reason": "SMTP 未設定(SMTP_USER/SMTP_PASS)"}

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_email
    footer = ("\n\n祝投資順利！\n量化阿森 Carson Quant\n"
              "YouTube: https://www.youtube.com/@carsonquant")
    msg.attach(MIMEText(body + footer, "plain", "utf-8"))
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, to_email, msg.as_string())
    return {"channel": "email", "sent": True, "to": to_email}


def _send_telegram(chat_id: str, text: str) -> dict:
    """與 tg_magnet 同款：POST api.telegram.org/bot{TOKEN}/sendMessage。
       token 取 TG_MAGNET_TOKEN(退回 TELEGRAM_BOT_TOKEN)。缺 token → 不送。"""
    token = (os.getenv("TG_MAGNET_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        return {"channel": "telegram", "sent": False,
                "reason": "缺 TG_MAGNET_TOKEN / TELEGRAM_BOT_TOKEN"}
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text[:3900]}).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=25) as resp:
        ok = resp.status == 200
    return {"channel": "telegram", "sent": bool(ok), "to": chat_id}


def send_report(recipient: str, report: dict, channel: str = "email",
                subject: str | None = None, dry_run: bool = True) -> dict:
    """把 generate_* 產出的 report 交付給一位訂閱者。

    recipient : email 位址(channel="email")或 Telegram chat_id(channel="telegram")
    report    : generate_weekly_report / generate_daily_scan 的回傳 dict
    dry_run   : 預設 True — 只組裝內容、不觸發任何真實發送(回傳 preview)。
                真正要寄時由呼叫端(webhook/cron)明確傳 dry_run=False。
    """
    content = report.get("content", "")
    subj = subject or report.get("title", "量化阿森 訂閱報告")
    if dry_run:
        return {"channel": channel, "sent": False, "dry_run": True,
                "to": recipient, "subject": subj, "preview": content[:200]}

    if channel == "email":
        return _send_email(recipient, subj, content)
    if channel == "telegram":
        return _send_telegram(recipient, f"{subj}\n\n{content}")
    return {"channel": channel, "sent": False, "reason": f"未知 channel: {channel}"}


# ── CLI：只產範例，不做真實發送 ─────────────────────────────────────────────
def _write_sample(report: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.get("as_of") or date.today().isoformat()
    path = out_dir / f"sample_{report['kind']}_{stamp}.md"
    path.write_text(report["content"], encoding="utf-8")
    return path


def main():
    ap = argparse.ArgumentParser(description="訂閱報告引擎(只產內容，不真寄)")
    ap.add_argument("--weekly", action="store_true", help="產週報範例")
    ap.add_argument("--daily", action="store_true", help="產每日掃描範例")
    ap.add_argument("--both", action="store_true", help="兩者都產")
    ap.add_argument("--out", default=str(OUTPUT_DIR), help="範例輸出目錄")
    args = ap.parse_args()
    if not (args.weekly or args.daily or args.both):
        args.both = True
    out_dir = Path(args.out)

    if args.weekly or args.both:
        r = generate_weekly_report()
        p = _write_sample(r, out_dir)
        print(f"[週報] {p}  覆蓋 {len(r['meta']['symbols'])} 檔 / "
              f"{r['meta']['n_facts']} 事實 / 丟棄 {r['meta']['n_dropped']}")
    if args.daily or args.both:
        r = generate_daily_scan()
        p = _write_sample(r, out_dir)
        print(f"[每日] {p}  溫度 {r['meta'].get('temperature')} / "
              f"多{r['meta'].get('n_long')} 空{r['meta'].get('n_short')}")


if __name__ == "__main__":
    main()
