# -*- coding: utf-8 -*-
"""ecommerce_weekly.py — 每週電商營運迴圈(給 local_cron 每週一跑)。

做四件事,全部只讀真實檔案、不動錢、不刪任何 SKU、不對客戶發任何東西:

  1) 回收本週銷售:讀 STUDIO/ecommerce_sales.json(webhook /sale-ping 寫的成交簿),
     以 received_at 篩出最近 window_days 天的成交。
  2) SKU 排名:掃 output/ecommerce_ready/<平台>/<sku>/{_provenance.json,listing.json},
     把每筆成交的 product 字串比對到 SKU(sku_id / listing 標題),算每 SKU 本週銷量+金額並排名。
  3) 淘汰建議:連續 N 週(預設 4)零銷量的 SKU 標「待淘汰」寫進報告——只建議、不刪檔,
     決策留給 Carson。連續週數存 STUDIO/ecommerce_ops_state.json,同一 ISO 週重跑不重複累加。
  4) 週報範例:呼叫 subscription_report.generate_weekly_report() + send_report(dry_run=True),
     把訂閱週報管線接上並附摘要(預設不真寄)。

推播:這是「給 Carson 本人看」的內部營運摘要,復用 notify.push(ntfy 單向推播到 Carson 手機,
低風險唯讀通知管道)。預設 print,只有明確傳 --notify 才真的推。

用法:
  python youtube_channel/scripts/ecommerce_weekly.py            # 空跑:算摘要並印出,不推播
  python youtube_channel/scripts/ecommerce_weekly.py --notify   # 算完 ntfy 推 Carson(cron 用這個)
  python youtube_channel/scripts/ecommerce_weekly.py --window 7 --drop-weeks 4
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent                 # youtube_channel/scripts/
YT = HERE.parent                                       # youtube_channel/
ROOT = YT.parent                                       # carson-agent/
STUDIO = YT / "STUDIO"
QS = ROOT / "quant-service"
ECOM_READY = QS / "output" / "ecommerce_ready"
ECOM_DIR = QS / "ecommerce"
OUT_DIR = QS / "output" / "ecommerce_ops"

SALES_LEDGER = STUDIO / "ecommerce_sales.json"
OPS_STATE = STUDIO / "ecommerce_ops_state.json"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ── 小工具 ────────────────────────────────────────────────────────────────
def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _norm(s: str) -> str:
    """正規化成純小寫英數(去底線/空白/標點),供 SKU ↔ 成交 product 字串比對。"""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _parse_dt(s: str):
    try:
        return datetime.fromisoformat((s or "").replace("Z", ""))
    except Exception:
        return None


def _iso_week(d: datetime) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


# ── SKU 註冊表:掃成品目錄 ─────────────────────────────────────────────────
def load_skus() -> list[dict]:
    """回傳 [{sku, platform, title, dir, norm_keys}]。只認含 listing.json 的目錄=真 SKU。"""
    skus = []
    if not ECOM_READY.exists():
        return skus
    for listing in sorted(ECOM_READY.glob("*/*/listing.json")):
        d = listing.parent
        listing_doc = _load_json(listing, {})
        prov = _load_json(d / "_provenance.json", {})
        sku_id = prov.get("sku") or d.name
        title = listing_doc.get("title") or ""
        norm_keys = {_norm(sku_id), _norm(d.name), _norm(title)}
        norm_keys.discard("")
        skus.append({
            "sku": sku_id,
            "platform": d.parent.name,
            "title": title,
            "dir": str(d),
            "norm_keys": norm_keys,
        })
    return skus


def _match_sku(product: str, skus: list[dict]) -> dict | None:
    """把一筆成交的 product 字串比對到某 SKU。無把握就回 None(誠實計未匹配)。"""
    p = _norm(product)
    if not p:
        return None
    for sku in skus:
        for key in sku["norm_keys"]:
            if len(key) >= 4 and (key in p or p in key):
                return sku
    return None


# ── 主流程 ────────────────────────────────────────────────────────────────
def build_summary(window_days: int, drop_weeks: int) -> dict:
    now = datetime.now()
    since = now - timedelta(days=window_days)
    week_key = _iso_week(now)

    skus = load_skus()
    ledger = _load_json(SALES_LEDGER, [])
    if not isinstance(ledger, list):
        ledger = []

    # 本週成交(退款 amount<0 一併計入,金額自然抵銷,但不算「一筆銷量」)
    per_sku: dict[str, dict] = {s["sku"]: {"count": 0, "amount": 0.0, "sku": s} for s in skus}
    week_sales = 0
    week_amount = 0.0
    unmatched: list[str] = []
    for rec in ledger:
        if not isinstance(rec, dict):
            continue
        dt = _parse_dt(rec.get("received_at", ""))
        if dt is None or dt < since:
            continue
        amt = float(rec.get("amount", 0) or 0)
        week_amount += amt
        if amt > 0:
            week_sales += 1
        m = _match_sku(rec.get("product", ""), skus)
        if m is None:
            unmatched.append(rec.get("product", "") or "(空白商品名)")
            continue
        b = per_sku[m["sku"]]
        b["amount"] += amt
        if amt > 0:
            b["count"] += 1

    ranking = sorted(per_sku.values(), key=lambda b: (b["count"], b["amount"]), reverse=True)

    # ── 連續零銷量追蹤(同一 ISO 週只累加一次)──
    state = _load_json(OPS_STATE, {})
    if not isinstance(state, dict):
        state = {}
    zero_state = state.get("skus", {})
    advanced_week = state.get("last_week") != week_key
    retire_candidates = []
    for b in ranking:
        sku_id = b["sku"]["sku"]
        rec = zero_state.get(sku_id, {"zero_weeks": 0})
        if advanced_week:
            if b["count"] == 0:
                rec["zero_weeks"] = rec.get("zero_weeks", 0) + 1
            else:
                rec["zero_weeks"] = 0
        zero_state[sku_id] = rec
        b["zero_weeks"] = rec["zero_weeks"]
        if rec["zero_weeks"] >= drop_weeks:
            retire_candidates.append((sku_id, b["sku"]["platform"], rec["zero_weeks"]))

    state["skus"] = zero_state
    state["last_week"] = week_key
    state["updated_at"] = now.isoformat()

    # ── 週報範例(接上訂閱管線;dry_run 不真寄)──
    weekly_meta, weekly_delivery = _weekly_report_preview()

    summary = {
        "as_of": now.strftime("%Y-%m-%d %H:%M"),
        "week_key": week_key,
        "window_days": window_days,
        "drop_weeks": drop_weeks,
        "n_skus": len(skus),
        "week_sales": week_sales,
        "week_amount": round(week_amount, 2),
        "ranking": ranking,
        "unmatched": unmatched,
        "retire_candidates": retire_candidates,
        "weekly_report_meta": weekly_meta,
        "weekly_report_delivery": weekly_delivery,
        "advanced_week": advanced_week,
        "_state": state,
    }
    return summary


def _weekly_report_preview():
    """呼叫旗艦週報引擎 v2 產 basic+full 兩版 PDF+xlsx,並以 dry_run 摘要交付(不真寄)。

    v2(weekly_report_v2)取代 v1(subscription_report):主體吃全市場掃描、暗色數據卡 HTML→PDF、
    數字全綁來源(誠信 gate fail-closed)。寄送名單走 load_send_list(tier)——與金流層
    webhook.subscribers.export_active 同一契約(見該檔 docstring)。dry_run 預設,本函式不寄任何東西。

    回退:若要暫時回 v1,把下方 v2 段註解、改用——
        import subscription_report as sr
        report = sr.generate_weekly_report()
        delivery = sr.send_report("carson@internal", report, channel="telegram", dry_run=True)
        return report.get("meta", {}), delivery
    """
    if str(ECOM_DIR) not in sys.path:
        sys.path.insert(0, str(ECOM_DIR))
    try:
        import weekly_report_v2 as wr
        tiers = {}
        for tier in ("basic", "full"):
            res = wr.generate_weekly(tier=tier)
            send_list = wr.load_send_list(tier=tier)   # 分層寄送名單(dry_run,不真寄)
            tiers[tier] = {
                "pdf": str(res["pdf"]), "xlsx": str(res["xlsx"]),
                "n_ok": res["n_ok"], "recipients": len(send_list),
                "sections": res["sections"],
            }
        meta = {"engine": "weekly_report_v2", "tiers": tiers}
        delivery = {"sent": False, "dry_run": True,
                    "basic_recipients": tiers["basic"]["recipients"],
                    "full_recipients": tiers["full"]["recipients"]}
        return meta, delivery
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}, {"sent": False, "reason": "週報引擎 v2 載入失敗"}


def render_text(summary: dict) -> str:
    L = []
    L.append(f"本週電商營運摘要（{summary['as_of']}｜{summary['week_key']}）")
    L.append(f"視窗 {summary['window_days']} 天｜上架 SKU {summary['n_skus']} 個")
    L.append(f"本週成交 {summary['week_sales']} 筆｜金額合計 {summary['week_amount']}")
    L.append("")
    L.append("SKU 排名（銷量／金額｜連零週）：")
    for i, b in enumerate(summary["ranking"], 1):
        s = b["sku"]
        L.append(f" {i:>2}. [{s['platform']}] {s['sku']}"
                 f" — {b['count']} 筆 / {round(b['amount'], 2)}"
                 f"｜連零 {b.get('zero_weeks', 0)} 週")
    if summary["unmatched"]:
        L.append("")
        L.append(f"未匹配到 SKU 的成交 {len(summary['unmatched'])} 筆："
                 + "；".join(summary["unmatched"][:5]))
    L.append("")
    if summary["retire_candidates"]:
        L.append(f"待淘汰建議（連續零銷量 ≥ {summary['drop_weeks']} 週，僅建議不刪檔）：")
        for sku_id, plat, wk in summary["retire_candidates"]:
            L.append(f" - [{plat}] {sku_id}（連零 {wk} 週）→ 建議下架或改版,決策由 Carson 定")
    else:
        L.append(f"待淘汰建議：無（尚無 SKU 連續零銷量達 {summary['drop_weeks']} 週）")
    L.append("")
    wm = summary["weekly_report_meta"]
    if "error" in wm:
        L.append(f"旗艦週報 v2:產製失敗（{wm['error']}）")
    else:
        tiers = wm.get("tiers", {})
        b = tiers.get("basic", {})
        f = tiers.get("full", {})
        L.append(f"旗艦週報 v2（{wm.get('engine', 'weekly_report_v2')}｜交付 dry_run,未真寄）:")
        L.append(f" - 基礎版 PDF:{b.get('n_ok', 0)}/8 sections OK｜寄送名單 {b.get('recipients', 0)} 人")
        L.append(f" - 完整版 PDF:{f.get('n_ok', 0)}/8 sections OK｜寄送名單 {f.get('recipients', 0)} 人")
        if f.get("pdf"):
            L.append(f" - 產物:{Path(f['pdf']).name} + {Path(f['xlsx']).name}(+基礎版)")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="每週電商營運迴圈(內部摘要給 Carson)")
    ap.add_argument("--window", type=int, default=7, help="本週視窗天數")
    ap.add_argument("--drop-weeks", type=int, default=4, help="連續零銷量幾週標待淘汰")
    ap.add_argument("--notify", action="store_true", help="真的用 ntfy 推 Carson(預設只 print)")
    ap.add_argument("--no-state", action="store_true", help="不寫 ops state(純預覽)")
    args = ap.parse_args()

    summary = build_summary(args.window, args.drop_weeks)
    text = render_text(summary)
    print(text)

    # 存摘要存檔(供留痕,可逆,純本機)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    (OUT_DIR / f"summary_{stamp}.md").write_text(text, encoding="utf-8")

    # 持久化連續零銷量狀態(除非 --no-state)
    if not args.no_state:
        OPS_STATE.write_text(json.dumps(summary["_state"], ensure_ascii=False, indent=2),
                             encoding="utf-8")

    if args.notify:
        try:
            from notify import push
            ok = push("🛒 電商週報｜本週營運摘要", text, tag="shopping_cart")
            print(f"[notify] pushed={ok}")
        except Exception as exc:  # noqa: BLE001
            print(f"[notify] 推播失敗:{exc}")
    else:
        print("[notify] 未推播(未帶 --notify,僅印出/存檔)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
