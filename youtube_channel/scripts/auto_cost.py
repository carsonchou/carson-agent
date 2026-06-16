#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""auto_cost.py — 【自動記帳·固定成本】每月把固定支出自動記進財務帳，冪等不重複。

讀 STUDIO/recurring_costs.json 的固定成本清單，每個項目每月只會自動記一筆
（用 finance 的 note 標記 [auto:項目:YYYY-MM] 判重）。排程每天跑也安全（同月不重記）。
不需任何帳密。收入端(Pionex返佣/YouTube廣告)因無 API 仍需手動或另做爬蟲。

用法：
  python scripts/auto_cost.py                      # 把本月還沒記的固定成本補記
  python scripts/auto_cost.py --list               # 看目前固定成本設定
  python scripts/auto_cost.py --set "主機" 756     # 設定/更新一個固定成本月費(NT$)
  python scripts/auto_cost.py --remove "主機"      # 移除一個固定成本項目
"""
from __future__ import annotations

import argparse
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
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
CONFIG = STUDIO / "recurring_costs.json"
TW = timezone(timedelta(hours=8))

import finance_dept as fin

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg): pass

# 預設固定成本（依雲端主機 2vCPU/4GB ≈ DigitalOcean $24/mo 推估；金額請用 --set 校正）
DEFAULT = {"items": [
    {"name": "DigitalOcean 主機(2vCPU/4GB)", "amount": 756, "note": "≈US$24/mo，請以實際帳單校正"},
]}


def this_month():
    return datetime.now(TW).strftime("%Y-%m")


def load_cfg():
    if CONFIG.exists():
        try:
            return json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception:
            pass
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(DEFAULT, ensure_ascii=False, indent=2), encoding="utf-8")
    return json.loads(json.dumps(DEFAULT))


def save_cfg(c):
    CONFIG.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")


def marker(name, month):
    return f"[auto:{name}:{month}]"


def run_auto():
    cfg = load_cfg()
    month = this_month()
    d = fin.load_finance()
    existing = {e.get("note", "") for e in d.get("entries", [])}
    added, total = 0, 0.0
    for it in cfg.get("items", []):
        name = it.get("name", "").strip()
        amt = float(it.get("amount", 0) or 0)
        if not name or amt <= 0:
            continue
        mk = marker(name, month)
        if any(mk in n for n in existing):
            continue  # 本月已記過
        fin.add_entry("cost", amt, f"{mk} {name}（自動記帳·固定成本）")
        added += 1
        total += amt
        print(f"[ok] 自動記一筆固定成本：{name} NT$ {amt:.0f}")
    if added:
        d = fin.load_finance()
        s = fin.summarize(d)
        d["summary"] = s
        fin.save_finance(d)
        log_ops("自動記帳", f"固定成本自動記 {added} 筆、共 NT$ {total:.0f}（{month}）")
        print(f"[ok] 本月固定成本自動記帳完成：{added} 筆，共 NT$ {total:.0f}")
    else:
        print(f"[info] {month} 固定成本都記過了，無需補記。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--set", nargs=2, metavar=("NAME", "AMOUNT"))
    ap.add_argument("--remove", metavar="NAME")
    args = ap.parse_args()

    if args.list:
        cfg = load_cfg()
        print("固定成本設定：")
        for it in cfg.get("items", []):
            print(f"  - {it['name']}：NT$ {it.get('amount',0):.0f}　{it.get('note','')}")
        return 0
    if args.set:
        name, amount = args.set[0].strip(), float(args.set[1])
        cfg = load_cfg()
        for it in cfg["items"]:
            if it["name"] == name:
                it["amount"] = amount
                break
        else:
            cfg["items"].append({"name": name, "amount": amount, "note": "手動設定"})
        save_cfg(cfg)
        print(f"[ok] 固定成本「{name}」設為 NT$ {amount:.0f}/月")
        return 0
    if args.remove:
        cfg = load_cfg()
        cfg["items"] = [it for it in cfg["items"] if it["name"] != args.remove]
        save_cfg(cfg)
        print(f"[ok] 已移除固定成本「{args.remove}」")
        return 0
    return run_auto()


if __name__ == "__main__":
    raise SystemExit(main())
