#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""growth_watchdog.py — 成長哨兵(盯觀看趨勢·真下滑才出手)。

Carson 要「永遠盯 48h 觀看,一下降就解決讓它一直上升」。誠實版:
- 48h 單日數字天生鋸齒(爆一支就衝、退潮就降),對每個下降出手=系統亂抖。故盯『滾動趨勢』非單日。
- 沒人能讓觀看「一直上升」——會紅的片讓它跳、基準線慢慢長。哨兵能做的是:catch『真.持續下滑』
  或『產線出包』並自動出手(偏產已驗證會紅的贏家題+通知 Carson),把持續成長的機率拉滿。

判定(避免誤報):讀 northstar.trend 的 7 日滾動%。
- 真下滑 = 7 日 <= -10% 且 28 日不再明顯為正(排除爆發退潮:28 日仍大漲時 7 日負是正常)。
- 產線出包 = 待發庫存見底(<=3)。
出手 = 用贏家關鍵字偏產 6 支題插隊(front)進 topic_bank,下個產片循環多做會紅的;ntfy 通知。
排程:cron 每日兩次(早晚各一)。手動:python scripts/growth_watchdog.py [--dry]
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass
try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(stage, msg):  # noqa: ARG001
        pass

DECLINE_7D_PCT = -10.0  # 7 日滾動觀看跌超過此% = 真下滑訊號(非單日噪音)
QUEUE_FLOOR = 3         # 待發庫存 <= 此數 = 產線見底
# 已驗證會紅的贏家家族(來源:weekly_winners 數據;traffic_signals 有就用它的、沒有退回這串)
WINNER_KW_FALLBACK = ["複利", "剩多少", "差多少", "停損", "vs", "ETF", "回測",
                      "樣本外", "過擬合", "實測", "定投", "0050"]


def _load(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d


def _winner_kw():
    ts = _load(STUDIO / "traffic_signals.json", {}) or {}
    for k in ("winner_keywords", "win_kw", "winners"):
        v = ts.get(k)
        if isinstance(v, list) and v and isinstance(v[0], str):
            return v[:12]
    return WINNER_KW_FALLBACK


def _queue_size():
    try:
        import produce_batch as pb
        return pb.queue_size()
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    dry = "--dry" in sys.argv
    ns = _load(STUDIO / "northstar.json", {}) or {}
    tr = ns.get("trend", {}) or {}
    t7 = tr.get("trend_7d_pct")
    t28 = tr.get("trend_28d_pct")
    direction = tr.get("trend_direction")
    q = _queue_size()
    print(f"[watchdog] 7日={t7} 28日={t28} 方向={direction} 待發庫存={q}")

    reasons = []
    # 真下滑:7 日明顯負,且 28 日不再明顯為正(排除爆發退潮)
    if isinstance(t7, (int, float)) and t7 <= DECLINE_7D_PCT:
        if not (isinstance(t28, (int, float)) and t28 > 5):
            reasons.append(f"7日滾動觀看 {t7:+.1f}%(真.持續下滑)")
        else:
            print(f"[watchdog] 7日{t7:+.1f}%但28日{t28:+.1f}%仍大漲=爆發退潮(正常),不出手")
    if isinstance(q, int) and q <= QUEUE_FLOOR:
        reasons.append(f"待發庫存見底({q}支)")

    if not reasons:
        note = "趨勢健康/正常退潮,不出手(避免對噪音亂抖)"
        print(f"[watchdog] {note}")
        log_ops("成長哨兵", note)
        return 0

    # 真問題 → 出手:偏產贏家題
    diag = "；".join(reasons)
    seeded = 0
    if not dry:
        try:
            import topic_bank as tb
            avoid = [t.get("title", "") for t in (tb.load_bank() or [])]
            items = tb.gen_topics(6, avoid, bias_keywords=_winner_kw())
            seeded = tb.add_topics(items, source="watchdog", front=True)
        except Exception as e:  # noqa: BLE001
            print(f"[watchdog] 偏產贏家題失敗:{e}", file=sys.stderr)
    msg = f"觀看示警:{diag}。已偏產{seeded}支贏家題(front優先),下個產片循環多做會紅的。建議也看看是否要人工加碼。"
    print(f"[watchdog][ALERT] {msg}")
    log_ops("成長哨兵", msg)
    if not dry:
        try:
            from notify import push
            push("量化阿森·成長哨兵", msg, tag="warning")
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
