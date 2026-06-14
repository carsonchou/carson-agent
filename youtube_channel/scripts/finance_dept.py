#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""finance_dept.py — 【⑭ 財務／變現部】損益與 ROI。

誠實前提：
  - Pionex 聯盟返佣、YouTube 廣告收入「沒有可自動抓的 API」→ 收入由老闆在決策中心『記一筆』手動輸入。
  - 成本面可估：目前產線是全免費棧（edge-tts 配音、Pexels 素材、YouTube 免費配額）→ 基線成本≈NT$0。
    唯一潛在成本＝Anthropic API（決策/補產/檢討用），無逐筆帳單故以「次數×粗估」標示，不假裝精準。

資料：STUDIO/finance.json（entries: [{date,type,amount,note}]；type=affiliate/adsense/cost）
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

TYPE_LABEL = {"affiliate": "Pionex 返佣", "adsense": "YouTube 廣告", "cost": "支出"}


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


def add_entry(etype, amount, note=""):
    """記一筆帳；etype in {affiliate, adsense, cost}。amount 正數。"""
    d = load_finance()
    d["entries"].append({"date": tw_today(), "type": etype, "amount": round(float(amount), 2), "note": note})
    save_finance(d)
    return d


def summarize(d):
    rev = sum(e["amount"] for e in d["entries"] if e["type"] in ("affiliate", "adsense"))
    cost = sum(e["amount"] for e in d["entries"] if e["type"] == "cost")
    aff = sum(e["amount"] for e in d["entries"] if e["type"] == "affiliate")
    ads = sum(e["amount"] for e in d["entries"] if e["type"] == "adsense")
    month = tw_today()[:7]
    m_rev = sum(e["amount"] for e in d["entries"] if e["type"] in ("affiliate", "adsense") and e["date"].startswith(month))
    m_cost = sum(e["amount"] for e in d["entries"] if e["type"] == "cost" and e["date"].startswith(month))
    return {"revenue": rev, "cost": cost, "net": rev - cost, "affiliate": aff, "adsense": ads,
            "month": month, "m_revenue": m_rev, "m_cost": m_cost, "m_net": m_rev - m_cost,
            "roi": (None if cost == 0 else round((rev - cost) / cost * 100, 1))}


def write_report(d, s):
    REPORTS.mkdir(parents=True, exist_ok=True)
    date = tw_today()
    pub = 0
    try:
        led = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
        pub = len(led) if isinstance(led, (dict, list)) else 0
    except Exception:
        pass
    L = [f"# ⑭ 財務／變現報告｜{date}", "",
         "> 誠實：返佣/廣告收入無 API，需手動『記一筆』；成本目前為全免費棧（≈NT$0），唯 Anthropic API 為潛在成本。", "",
         "## 一、總損益（累計）",
         f"- 收入合計：NT$ {s['revenue']:.0f}（Pionex 返佣 {s['affiliate']:.0f}／YouTube 廣告 {s['adsense']:.0f}）",
         f"- 支出合計：NT$ {s['cost']:.0f}",
         f"- **淨利：NT$ {s['net']:.0f}**" + (f"　ROI {s['roi']}%" if s["roi"] is not None else "　（尚無支出，ROI 不適用）"),
         "",
         f"## 二、本月（{s['month']}）",
         f"- 收入 NT$ {s['m_revenue']:.0f}　支出 NT$ {s['m_cost']:.0f}　淨 NT$ {s['m_net']:.0f}",
         "",
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
        L.append(f"- {e['date']}　{TYPE_LABEL.get(e['type'], e['type'])}　NT$ {e['amount']:.0f}　{e.get('note', '')}")
    if not d["entries"]:
        L.append("-（尚無記錄。到決策中心『💰 記一筆帳』輸入返佣/廣告收入或支出）")
    (REPORTS / f"{date}_財務.md").write_text("\n".join(L), encoding="utf-8")
    d["summary"] = s
    save_finance(d)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--add", choices=["affiliate", "adsense", "cost"], help="記一筆")
    ap.add_argument("--amount", type=float, default=0)
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    if args.add:
        add_entry(args.add, args.amount, args.note)
        print(f"[ok] 已記一筆 {TYPE_LABEL.get(args.add)} NT$ {args.amount:.0f}")

    d = load_finance()
    s = summarize(d)
    write_report(d, s)
    log_ops("財務部", f"損益：收入 {s['revenue']:.0f} 支出 {s['cost']:.0f} 淨 {s['net']:.0f}")
    print(f"[ok] 財務報告完成：累計淨利 NT$ {s['net']:.0f}（收入 {s['revenue']:.0f}／支出 {s['cost']:.0f}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
