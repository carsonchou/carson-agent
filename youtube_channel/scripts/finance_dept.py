#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""finance_dept.py — 【⑭ 財務／變現部】損益與 ROI。

誠實前提：
  - Pionex 聯盟返佣、YouTube 廣告收入「沒有可自動抓的 API」→ 收入由老闆在決策中心『記一筆』手動輸入。
  - 成本面可估：目前產線是全免費棧（edge-tts 配音、Pexels 素材、YouTube 免費配額）→ 基線成本≈NT$0。
    唯一潛在成本＝Anthropic API（決策/補產/檢討用），無逐筆帳單故以「次數×粗估」標示，不假裝精準。

資料：STUDIO/finance.json（entries: [{date,type,amount,note,platform,stream}]；
  type=affiliate/adsense/product/newsletter/vip/tips/sponsor/cost（cost 以外皆計入收入）；
  platform=youtube/tiktok/instagram/general（預設 youtube，供 C2 revenue_dashboard.py 按平台拆帳）；
  stream=收入線識別（預設等於 type，供 revenue_dashboard.py 讀取，向下相容舊資料無此欄位）。
輸出：STUDIO/REPORTS/{date}_財務.md ＋ 回寫 finance.json 的 summary
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"
REPORTS = STUDIO / "REPORTS"
FINANCE = STUDIO / "finance.json"
LEDGER = STUDIO / "uploaded_ledger.json"

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(dept, msg):
        try:
            (STUDIO / "ops_log.txt").parent.mkdir(parents=True, exist_ok=True)
            with (STUDIO / "ops_log.txt").open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now().strftime('%H:%M')} [{dept}] {msg}\n")
        except Exception:
            pass

TYPE_LABEL = {
    "affiliate": "Pionex 返佣", "adsense": "YouTube 廣告", "cost": "支出",
    "product": "數位產品(worksheet)", "newsletter": "電子報訂閱", "vip": "VIP會員",
    "tips": "贊助抖內", "sponsor": "業配贊助",
}


def tw_today():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def load_finance():
    if FINANCE.exists():
        try:
            d = json.loads(FINANCE.read_text(encoding="utf-8"))
            d.setdefault("entries", [])
            return d
        except Exception:
            pass
    return {"entries": []}


def save_finance(d):
    FINANCE.parent.mkdir(parents=True, exist_ok=True)
    FINANCE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def add_entry(etype, amount, note="", platform="youtube", stream=None, currency="TWD"):
    """記一筆帳；etype in TYPE_LABEL(affiliate/adsense/product/newsletter/vip/tips/sponsor/cost)。
    amount 可正可負(退款沖銷走負值)。
    platform：所屬平台(youtube/tiktok/instagram/general，預設 youtube，向下相容舊呼叫)。
    stream：收入線識別，預設同 etype(供 C2 revenue_dashboard.py 用；cost 不算收入線但仍記錄方便追蹤)。
    currency：幣別(預設 TWD，向下相容——舊 entry 無此欄位一律當 TWD)。summarize() 依此分幣別加總，不同幣別絕不混加。"""
    d = load_finance()
    d["entries"].append({
        "date": tw_today(), "type": etype, "amount": round(float(amount), 2), "note": note,
        "platform": platform or "youtube", "stream": stream or etype,
        "currency": (currency or "TWD").upper(),
    })
    save_finance(d)
    return d


def _entry_currency(e):
    # 舊 entry 無 currency 欄位 → 一律視為 TWD(報表原生幣別 NT$)，維持向下相容。
    return (e.get("currency") or "TWD").upper()


def summarize(d):
    # 分幣別加總：不同幣別絕不混加(990 TWD 不會被當 990 USD 相加，修正約 30x 高估)。
    # 每個幣別內：收入＝所有非 cost 的類型(向下相容:舊資料僅 affiliate/adsense，同幣別加總結果與舊版完全相同；
    # 新類型 product/newsletter/vip/tips/sponsor 自動計入，免每加一種收入線就回來改這裡)。
    entries = d.get("entries", [])
    month = tw_today()[:7]
    currencies = sorted({_entry_currency(e) for e in entries}) or ["TWD"]
    by_currency = {}
    for c in currencies:
        ce = [e for e in entries if _entry_currency(e) == c]
        rev = sum(e["amount"] for e in ce if e["type"] != "cost")
        cost = sum(e["amount"] for e in ce if e["type"] == "cost")
        aff = sum(e["amount"] for e in ce if e["type"] == "affiliate")
        ads = sum(e["amount"] for e in ce if e["type"] == "adsense")
        m_rev = sum(e["amount"] for e in ce if e["type"] != "cost" and e["date"].startswith(month))
        m_cost = sum(e["amount"] for e in ce if e["type"] == "cost" and e["date"].startswith(month))
        by_currency[c] = {
            "revenue": rev, "cost": cost, "net": rev - cost, "affiliate": aff, "adsense": ads,
            "m_revenue": m_rev, "m_cost": m_cost, "m_net": m_rev - m_cost,
            "roi": (None if cost == 0 else round((rev - cost) / cost * 100, 1)),
        }
    # legacy 頂層鍵維持不變：鏡射報表原生幣別(TWD)那一桶，舊呼叫端(auto_cost.py 存 d['summary']、
    # write_report 舊欄位)完全不受影響；全 TWD 的舊資料 → 頂層數字與舊版逐位相同。
    primary = "TWD" if "TWD" in by_currency else currencies[0]
    s = dict(by_currency[primary])
    s["month"] = month
    s["primary_currency"] = primary
    s["currencies"] = currencies
    s["by_currency"] = by_currency
    return s


def write_report(d, s):
    REPORTS.mkdir(parents=True, exist_ok=True)
    date = tw_today()
    pub = 0
    try:
        led = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
        pub = len(led) if isinstance(led, (dict, list)) else 0
    except Exception:
        pass
    def _sym(code):
        return "NT$" if code == "TWD" else code + " "
    L = [f"# ⑭ 財務／變現報告｜{date}", "",
         "> 誠實：返佣/廣告收入無 API，需手動『記一筆』；成本目前為全免費棧（≈NT$0），唯 Anthropic API 為潛在成本。", "",
         "## 一、總損益（累計・分幣別，不同幣別不混加）"]
    for code in s["currencies"]:
        b = s["by_currency"][code]
        sym = _sym(code)
        L.append(f"### {code}")
        L.append(f"- 收入合計：{sym}{b['revenue']:.0f}（Pionex 返佣 {b['affiliate']:.0f}／YouTube 廣告 {b['adsense']:.0f}）")
        L.append(f"- 支出合計：{sym}{b['cost']:.0f}")
        L.append(f"- **淨利：{sym}{b['net']:.0f}**" + (f"　ROI {b['roi']}%" if b["roi"] is not None else "　（尚無支出，ROI 不適用）"))
    L += ["",
          f"## 二、本月（{s['month']}）"]
    for code in s["currencies"]:
        b = s["by_currency"][code]
        sym = _sym(code)
        L.append(f"- [{code}] 收入 {sym}{b['m_revenue']:.0f}　支出 {sym}{b['m_cost']:.0f}　淨 {sym}{b['m_net']:.0f}")
    L += ["",
         "## 三、成本結構（誠實估算）",
         "- 配音 edge-tts：免費　｜　素材 Pexels：免費　｜　YouTube 上傳：免費配額內",
         "- Anthropic API（決策/補產/檢討/財務分析）：有用量但無逐筆帳單，屬唯一潛在成本，金額小。",
         "- → 現階段實質燒錢趨近 0；變現主力＝Pionex 返佣，衝觀看與註冊轉換即可。",
         "",
         "## 四、變現提醒",
         f"- 已上架 {pub} 支；YPP 廣告需先達標（訂閱/Shorts 觀看），在那之前收入主力是聯盟返佣。",
         "- 每支影片描述都帶 Pionex 邀請連結（邀請碼 08NAcfvcWna）；返佣數字請定期到 Pionex 後台查，回來『記一筆 affiliate』。",
         "",
         "## 五、近期記錄（最新 10 筆）"]
    for e in d["entries"][-10:][::-1]:
        _c = _entry_currency(e)
        _s = "NT$ " if _c == "TWD" else _c + " "
        L.append(f"- {e['date']}　{TYPE_LABEL.get(e['type'], e['type'])}　{_s}{e['amount']:.0f}　{e.get('note', '')}")
    if not d["entries"]:
        L.append("-（尚無記錄。到決策中心『💰 記一筆帳』輸入返佣/廣告收入或支出）")
    (REPORTS / f"{date}_財務.md").write_text("\n".join(L), encoding="utf-8")
    d["summary"] = s
    save_finance(d)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--add", choices=list(TYPE_LABEL.keys()), help="記一筆")
    ap.add_argument("--amount", type=float, default=0)
    ap.add_argument("--note", default="")
    ap.add_argument("--platform", default="youtube", choices=["youtube", "tiktok", "instagram", "general"],
                     help="所屬平台(預設 youtube，供 C2 revenue_dashboard.py 按平台拆帳)")
    ap.add_argument("--currency", default="TWD", help="幣別(預設 TWD；分幣別加總不混加)")
    args = ap.parse_args()

    if args.add:
        add_entry(args.add, args.amount, args.note, platform=args.platform, currency=args.currency)
        print(f"[ok] 已記一筆 {TYPE_LABEL.get(args.add)} NT$ {args.amount:.0f}")

    d = load_finance()
    s = summarize(d)
    write_report(d, s)
    log_ops("財務部", f"損益：收入 {s['revenue']:.0f} 支出 {s['cost']:.0f} 淨 {s['net']:.0f}")
    print(f"[ok] 財務報告完成：累計淨利 NT$ {s['net']:.0f}（收入 {s['revenue']:.0f}／支出 {s['cost']:.0f}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
