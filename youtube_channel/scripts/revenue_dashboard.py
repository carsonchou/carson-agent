#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""revenue_dashboard.py — 【C2 收入儀表板】各平台 × 各收入線進帳、名單來源、名單→付費轉換率彙整。

唯讀聚合(零動錢、零自動送出，只是把現成資料算成一份可看的摘要)：
  - STUDIO/finance.json 的 entries(finance_dept.py 寫入；type/platform/stream，
    舊資料沒有 platform/stream 欄位時分別補預設 youtube／同 type)。
  - STUDIO/tg_leads.json(tg_magnet.py 寫入；含 src/stage)。

輸出：STUDIO/revenue.json；若 STUDIO/northstar.json 已存在，額外把摘要併進去的
      "revenue_by_platform" 欄(只新增這個 key，不動 northstar.py 既有其他欄位)。
用法：python scripts/revenue_dashboard.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"

import studio_common as sc  # noqa: E402  (save_json_atomic / load_json_safe：併發安全讀寫)

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(dept, msg): pass

# 已知平台/收入線(供矩陣固定欄位、前端好排版；未知值仍會被收進去，不會丟資料)。
_PLATFORMS = ("youtube", "tiktok", "instagram")
_STREAMS = ("affiliate", "product", "newsletter", "vip", "tips", "sponsor", "adsense")
_STAGE_LABEL = {0: "新名單", 1: "已收檢核表", 2: "已買worksheet", 3: "已推電子報", 4: "VIP"}


def _load_finance_entries() -> list:
    d = sc.load_json_safe(STUDIO / "finance.json", {}) or {}
    entries = d.get("entries") if isinstance(d, dict) else None
    return entries if isinstance(entries, list) else []


def _load_leads() -> dict:
    d = sc.load_json_safe(STUDIO / "tg_leads.json", {}) or {}
    return d if isinstance(d, dict) else {}


def _entry_currency(e) -> str:
    # 舊資料無 currency 欄 → 一律視為 TWD(報表原生幣別 NT$)，維持向下相容。
    return (e.get("currency") or "TWD").upper()


def _matrix_for(entries: list) -> dict:
    """對『單一幣別』的 entries 算 {platform:{stream:累計金額}} + 各加總；cost 另計不進矩陣(那是支出，不是收入線)。"""
    matrix: dict[str, dict[str, float]] = {}
    total_cost = 0.0
    for e in entries:
        if not isinstance(e, dict):
            continue
        etype = e.get("type", "")
        try:
            amt = float(e.get("amount", 0) or 0)
        except Exception:  # noqa: BLE001
            amt = 0.0
        if etype == "cost":
            total_cost += amt
            continue
        platform = e.get("platform") or "youtube"   # 舊資料無 platform 欄 → 預設 youtube(現行唯一有量的平台)
        stream = e.get("stream") or etype or "other"  # 舊資料無 stream 欄 → 退回 type 本身
        row = matrix.setdefault(platform, {})
        row[stream] = row.get(stream, 0.0) + amt

    # 補齊已知平台 × 已知收入線的 0 值，讓前端能畫固定表格(未知平台/收入線仍保留在各自 key 下，不補零、不丟資料)。
    for p in _PLATFORMS:
        row = matrix.setdefault(p, {})
        for s in _STREAMS:
            row.setdefault(s, 0.0)

    by_platform_total = {p: round(sum(row.values()), 2) for p, row in matrix.items()}
    by_stream_total: dict[str, float] = {}
    for row in matrix.values():
        for s, amt in row.items():
            by_stream_total[s] = round(by_stream_total.get(s, 0.0) + amt, 2)

    return {
        "matrix": {p: {s: round(v, 2) for s, v in row.items()} for p, row in matrix.items()},
        "by_platform_total": by_platform_total,
        "by_stream_total": by_stream_total,
        "total_cost": round(total_cost, 2),
        "total_revenue": round(sum(by_platform_total.values()), 2),
    }


def _revenue_matrix(entries: list) -> dict:
    """分幣別加總：不同幣別絕不混加(990 TWD 不再被當 990 USD 直接相加，修 total_revenue 高估)。
    頂層 legacy 鍵(matrix/by_platform_total/by_stream_total/total_cost/total_revenue)鏡射 TWD 桶(報表原生幣別)
    → 全 TWD 舊資料輸出與舊版逐位相同、既有讀取端(_merge_northstar/print/revenue.json)不受影響；
    另新增 by_currency(各幣別完整矩陣)與 currencies。"""
    valid = [e for e in entries if isinstance(e, dict)]
    currencies = sorted({_entry_currency(e) for e in valid}) or ["TWD"]
    by_currency = {c: _matrix_for([e for e in valid if _entry_currency(e) == c]) for c in currencies}
    primary = "TWD" if "TWD" in by_currency else currencies[0]
    result = dict(by_currency[primary])  # 鏡射原生幣別那一桶，頂層 5 鍵語意與舊版一致
    result["primary_currency"] = primary
    result["currencies"] = currencies
    result["by_currency"] = by_currency
    return result


# 誠信/防灌水(獨立複查抓到的真實 bug 修正)：stage=3 是 tg_magnet.py run_newsletter_pitch 在「推播成功送達」
# 當下就自動打上的(見該函式 docstring)，代表訊息已送達、不代表對方已完成訂閱付款——名單可能單靠「建立滿7天」
# 這條時間路徑就被自動推到 stage=3，從沒有真的付過錢。若把 stage>=2 整個當「已付費」，stage=3 這批純推播對象
# 會把轉換率灌水。stage=2(買worksheet)/stage=4(VIP)目前全 repo 沒有任何自動路徑會設，只有 Carson 人工對帳後
# 手動改 tg_leads.json 才會出現，才是真正「已確認付費」的訊號；stage=3 另外算一欄「已推播未確認」，不計入轉換率。
_CONFIRMED_PAID_STAGES = (2, 4)


def _lead_stats(leads: dict) -> dict:
    """名單來源分布 + stage 分布 + 名單→付費轉換率。
    轉換率只計「已人工確認付費」的 stage(2=買worksheet／4=VIP，皆僅由 Carson 人工設定)；
    stage=3(電子報已推播)因會被自動化路徑打上、不代表已完成付款，另算 pitched_unconfirmed，不計入轉換率。"""
    by_src: dict[str, int] = {}
    by_stage: dict[str, int] = {}
    total = paid = pitched_unconfirmed = 0
    for info in leads.values():
        if not isinstance(info, dict):
            continue
        total += 1
        src = info.get("src") or "unknown"
        by_src[src] = by_src.get(src, 0) + 1
        try:
            stage = int(info.get("stage", 0) or 0)
        except Exception:  # noqa: BLE001
            stage = 0
        by_stage[str(stage)] = by_stage.get(str(stage), 0) + 1
        if stage in _CONFIRMED_PAID_STAGES:
            paid += 1
        elif stage == 3:
            pitched_unconfirmed += 1

    conv_by_src: dict[str, float] = {}
    for src, cnt in by_src.items():
        paid_in_src = sum(
            1 for info in leads.values()
            if isinstance(info, dict) and (info.get("src") or "unknown") == src
            and int(info.get("stage", 0) or 0) in _CONFIRMED_PAID_STAGES
        )
        conv_by_src[src] = round(paid_in_src / cnt * 100, 1) if cnt else 0.0

    return {
        "total": total,
        "by_src": by_src,
        "by_stage": by_stage,
        "by_stage_label": {str(k): v for k, v in _STAGE_LABEL.items()},
        "paid_total": paid,
        "newsletter_pitched_unconfirmed": pitched_unconfirmed,
        "conversion_pct": round(paid / total * 100, 1) if total else 0.0,
        "conversion_pct_by_src": conv_by_src,
        "note": "conversion_pct 只計人工確認付費(stage=2/4)；stage=3 是電子報自動推播送達即打上，"
                "不代表已完成訂閱付款，見 newsletter_pitched_unconfirmed，不算進轉換率避免灌水。",
    }


def _merge_northstar(data: dict) -> bool:
    """northstar.json 已存在才併入摘要；只新增 revenue_by_platform 這個 key，不動其餘既有欄位。"""
    ns_path = STUDIO / "northstar.json"
    ns = sc.load_json_safe(ns_path, None)
    if not isinstance(ns, dict):
        return False
    ns["revenue_by_platform"] = {
        "by_platform_total": data["revenue"]["by_platform_total"],
        "by_stream_total": data["revenue"]["by_stream_total"],
        "leads_by_src": data["leads"]["by_src"],
        "conversion_pct_by_src": data["leads"]["conversion_pct_by_src"],
        "updated": data["updated"],
    }
    sc.save_json_atomic(ns_path, ns)
    return True


def main() -> int:
    entries = _load_finance_entries()
    leads = _load_leads()
    rev = _revenue_matrix(entries)
    lead_stats = _lead_stats(leads)
    data = {
        "updated": time.strftime("%Y-%m-%d %H:%M"),
        "revenue": rev,
        "leads": lead_stats,
    }
    sc.save_json_atomic(STUDIO / "revenue.json", data)
    merged = _merge_northstar(data)

    print(f"[ok] 收入矩陣：總收入 NT${rev['total_revenue']:.0f}｜成本 NT${rev['total_cost']:.0f}")
    for p, amt in rev["by_platform_total"].items():
        print(f"  - {p}: NT${amt:.0f}")
    print(f"[ok] 名單：{lead_stats['total']} 人｜已轉換付費(stage>=2) {lead_stats['paid_total']} 人｜"
          f"轉換率 {lead_stats['conversion_pct']}%")
    print(f"[ok] 已寫入 {STUDIO / 'revenue.json'}"
          + ("，並併入 northstar.json 的 revenue_by_platform" if merged else "(northstar.json 尚未產生，略過併入)"))
    log_ops("收入儀表板", f"總收入 NT${rev['total_revenue']:.0f} 名單{lead_stats['total']}人 轉換率{lead_stats['conversion_pct']}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
