#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""traffic_dept.py — 流量分析部門。
每日 05:35 CST 執行，拉 YouTube Analytics 資料，
輸出 STUDIO/REPORTS/{today}_流量洞察.md，
並更新 STUDIO/production_orders.json 給補產部門參考。
"""
from __future__ import annotations
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPORTS = ROOT / "STUDIO" / "REPORTS"
ORDERS_PATH = ROOT / "STUDIO" / "production_orders.json"
LEDGER_PATH = ROOT / "STUDIO" / "uploaded_ledger.json"


def load_ledger() -> dict:
    if LEDGER_PATH.exists():
        try:
            return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def load_orders() -> dict:
    if ORDERS_PATH.exists():
        try:
            return json.loads(ORDERS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _fmt(n) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


def generate_report() -> None:
    today = date.today().isoformat()
    REPORTS.mkdir(parents=True, exist_ok=True)
    lines: list = []

    lines += [f"# {today} 流量洞察", "", f"> 自動生成時間：{today} 05:35 CST", ""]

    svc = None
    yta = None
    try:
        import yt_analytics as _yta
        svc = _yta.get_service()
        yta = _yta
    except Exception as exc:
        lines += [
            "## ⚠️ Analytics API 連線失敗",
            "",
            f"錯誤：{exc}",
            "",
            "請確認 `/root/yt/token_analytics.json` 是否有效（需重新 OAuth 授權）。",
            "",
        ]
        out = REPORTS / f"{today}_流量洞察.md"
        out.write_text("\n".join(lines), encoding="utf-8")
        print(f"[WARN] 無法連接 Analytics API，已輸出錯誤報告：{out}")
        return

    # ─── 頻道總覽（近 28 天）───
    try:
        summary = yta.channel_summary(svc)
        views = summary.get("views", 0)
        minutes = summary.get("estimatedMinutesWatched", 0)
        avg_pct = summary.get("averageViewPercentage", 0)
        subs_gained = summary.get("subscribersGained", 0)
        subs_lost = summary.get("subscribersLost", 0)
        lines += [
            "## 頻道總覽（近 28 天）",
            "",
            "| 指標 | 數值 |",
            "|------|------|",
            f"| 觀看次數 | {_fmt(views)} |",
            f"| 觀看時間 | {_fmt(minutes)} 分鐘 |",
            f"| 平均完播率 | {float(avg_pct):.1f}% |",
            f"| 新增訂閱 | +{_fmt(subs_gained)} |",
            f"| 取消訂閱 | -{_fmt(subs_lost)} |",
            "",
            "> ℹ️ **曝光次數與點閱率（CTR）不在此報告中。**",
            "> YouTube Analytics API 不提供這兩項數據（僅 YouTube Studio 網頁可見）。",
            "> 報告裡看到「曝光 0」是 API 限制，不是真實數據，請勿以此判斷頻道健康度。",
            "",
        ]
    except Exception as exc:
        lines += [f"⚠️ 無法取得頻道總覽：{exc}", ""]

    # ─── 高表現影片（依觀看排名）───
    try:
        top = yta.top_by_ctr(svc, limit=10)
        if top:
            lines += ["## 近期影片表現（依觀看排名）", ""]
            lines += ["| # | 標題 | 觀看 | 完播率 |"]
            lines += ["|---|------|------|--------|"]
            for i, v in enumerate(top[:10], 1):
                title = v.get("title", "？")[:30]
                vw = _fmt(v.get("views", 0))
                pct = v.get("avgPct", 0)
                lines.append(f"| {i} | {title} | {vw} | {float(pct):.1f}% |")
            lines.append("")
    except Exception as exc:
        lines += [f"⚠️ 無法取得影片排行：{exc}", ""]

    # ─── 頻道現況 ───
    ledger = load_ledger()
    uploaded_count = len(ledger)
    recent_slugs = list(ledger.keys())[-10:]
    lines += [
        "## 頻道現況",
        "",
        f"- 已上架影片總數：**{uploaded_count} 支**",
        "",
        "最近上架：",
    ]
    for s in reversed(recent_slugs):
        vid_id = ledger.get(s, "")
        title_part = s[2:] if len(s) > 2 and s[1] == "_" else s
        if vid_id:
            lines.append(f"- [{title_part}](https://youtu.be/{vid_id})")
        else:
            lines.append(f"- {title_part}")
    lines.append("")

    # ─── 洞察與決策建議 ───
    orders = load_orders()
    produce_more = orders.get("produce_more", [])
    lines += [
        "## 流量洞察與決策建議",
        "",
        "### 持續投入（高完播率題材）",
        "- 定投、回測、夏普比率、馬丁格爾、勝率/盈虧比",
        "- 標題框架：**數學拆穿直覺錯誤**（反直覺揭錯類型效果最佳）",
        "",
        "### 暫緩投入（效果偏弱）",
        "- 複利基礎介紹、回撤介紹（可與其他主題結合再做）",
        "",
        "### 格式建議",
        "- 優先 Shorts（演算法推薦效率較高）",
        "- 標題長度控制在 20 字以內，前半段放最強鉤子",
        "",
    ]
    if produce_more:
        lines += ["### 補產部門指令（來自 production_orders.json）", ""]
        for item in produce_more:
            lines.append(f"- {item}")
        lines.append("")

    # ─── 輸出報告 ───
    out = REPORTS / f"{today}_流量洞察.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] 流量洞察已輸出：{out}")

    # ─── 更新 production_orders.json ───
    new_orders = {
        "preferred_keywords": [
            "定投", "回測", "夏普", "網格", "勝率", "馬丁格爾",
            "量化", "風控", "期望值", "派網",
        ],
        "produce_more": [
            "數學拆穿直覺：定投/回測/勝率類反直覺揭錯",
            "夏普比率實戰應用",
            "網格策略風控設定",
        ],
        "avoid_topics": ["複利基礎（單獨製作）", "回撤介紹（單獨製作）"],
        "last_updated": today,
    }
    ORDERS_PATH.write_text(
        json.dumps(new_orders, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[OK] 製作指令已更新：{ORDERS_PATH}")


if __name__ == "__main__":
    generate_report()
