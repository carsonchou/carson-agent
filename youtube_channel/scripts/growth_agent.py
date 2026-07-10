#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""growth_agent.py — 24/7 智慧成長守衛(本機排程器跑·OpenRouter當腦·關 Claude 也活)。

Carson 要「agent 24/7 盯著觀看,一下降就找方法解決」。真正做得到的解:
把「腦」從 Claude(session-only+燒錢+踩ToS)換成 OpenRouter(產線已在用的 DeepSeek,月~$1.6),
讓有推理能力的守衛跑在本機 local_cron 上——**關 Claude 也活、真 24/7、有腦、便宜、不踩 Anthropic ToS**。

流程:蒐集頻道即時脈絡 → LLM 判斷(真下滑 vs 正常爆發退潮 + 根因 + 該不該出手) → 執行『安全動作』 → ntfy。
LLM 只當『腦』(診斷+從安全選單挑動作);動作限:偏產贏家題 / 只記錄 / 只告警。
**紅線(對外發布/動錢/寫 YT 帳號如 set private)一律不自動做**——那些只告警給 Carson 人工處理。
LLM 掛掉時退回確定性門檻(同 growth_watchdog),絕不因 LLM 失敗就停擺。

排程:cron 每 2 小時。手動:python scripts/growth_agent.py [--dry]
"""
from __future__ import annotations
import json
import os
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

WINNER_KW = ["複利", "剩多少", "差多少", "停損", "vs", "ETF", "回測", "樣本外", "過擬合", "實測", "定投", "0050"]
DECLINE_7D_PCT = -10.0
QUEUE_FLOOR = 3


def _load(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d


def _load_env():
    envf = ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text(encoding="utf-8", errors="replace").splitlines():
            s = ln.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()


def _context() -> dict:
    """蒐集頻道即時脈絡(全部讀現成檔,不打 YouTube API 省配額)。"""
    ns = _load(STUDIO / "northstar.json", {}) or {}
    tr = ns.get("trend", {}) or {}
    ri = _load(STUDIO / "retention_insights.json", {}) or {}
    md = _load(STUDIO / "metrics_daily.json", {}) or {}
    if isinstance(md, list):  # metrics_daily 是逐日 list,取最後一筆(今日)
        md = md[-1] if md else {}
    if not isinstance(md, dict):
        md = {}
    ctx = {
        "views_7d_pct": tr.get("trend_7d_pct"),
        "views_28d_pct": tr.get("trend_28d_pct"),
        "views_direction": tr.get("trend_direction"),
        "retention_verdict": (ri.get("verdict") or "")[:200],
        "shorts_today": md.get("shorts_today"),
        "longs_today": md.get("longs_today"),
        "audit_fail_today": md.get("audit_fail"),
    }
    try:
        import produce_batch as pb
        ctx["queue_size"] = pb.queue_size()
    except Exception:  # noqa: BLE001
        ctx["queue_size"] = None
    # 跨平台近況(ledger 筆數,無時戳只看有無在累積)
    ctx["tiktok_posts"] = len(_load(STUDIO / "tiktok_ledger.json", {}) or {})
    ctx["ig_posts"] = len(_load(STUDIO / "ig_ledger.json", {}) or {})
    return ctx


def _llm_decide(ctx: dict):
    """LLM 當腦:回 {problem, diagnosis, root_cause, action}。action∈{seed_winners,alert_only,none}。失敗回 None。"""
    try:
        import llm
        prompt = (
            "你是台股/加密量化教育頻道「量化阿森」的成長守衛。以下是頻道即時脈絡(JSON):\n"
            + json.dumps(ctx, ensure_ascii=False) + "\n\n"
            "判斷並只回 JSON:{\"problem\":bool,\"diagnosis\":\"一句話\",\"root_cause\":\"完播|發布卡|跨平台停|題材單一|正常退潮|無\",\"action\":\"seed_winners|alert_only|none\"}\n"
            "規則:①觀看 7 日%為正、或 7 日負但 28 日仍大漲=爆發退潮(正常)→problem=false,action=none。"
            "②7 日<=-10% 且 28 日不再大漲=真下滑→problem=true。③待發庫存<=3 或今日 audit_fail 異常高=產線出包→problem=true。"
            "④真下滑且根因偏題材/內容→action=seed_winners(偏產贏家題);根因偏發布卡/跨平台/需人工→action=alert_only。健康→none。"
        )
        raw = llm.complete(prompt, 300, json_mode=True, temperature=0.1)
        d = json.loads(raw)
        if isinstance(d, dict) and "action" in d:
            return d
    except Exception as e:  # noqa: BLE001
        print(f"[growth_agent] LLM 判斷失敗,退回確定性門檻:{e}", file=sys.stderr)
    return None


def _fallback_decide(ctx: dict):
    """LLM 掛掉時的確定性判斷(同 growth_watchdog 邏輯)。"""
    t7, t28, q = ctx.get("views_7d_pct"), ctx.get("views_28d_pct"), ctx.get("queue_size")
    problem, action, rc = False, "none", "無"
    if isinstance(t7, (int, float)) and t7 <= DECLINE_7D_PCT and not (isinstance(t28, (int, float)) and t28 > 5):
        problem, action, rc = True, "seed_winners", "題材單一"
    if isinstance(q, int) and q <= QUEUE_FLOOR:
        problem, action, rc = True, "alert_only", "發布卡"
    return {"problem": problem, "diagnosis": f"7日{t7}% 28日{t28}% 庫存{q}", "root_cause": rc, "action": action}


def _seed_winners(dry: bool) -> int:
    if dry:
        return 0
    try:
        import topic_bank as tb
        avoid = [t.get("title", "") for t in (tb.load_bank() or [])]
        items = tb.gen_topics(6, avoid, bias_keywords=WINNER_KW)
        return tb.add_topics(items, source="growth_agent", front=True)
    except Exception as e:  # noqa: BLE001
        print(f"[growth_agent] 偏產贏家題失敗:{e}", file=sys.stderr)
        return 0


def _notify(msg: str, dry: bool):
    if dry:
        return
    try:
        from notify import push
        push("量化阿森·成長守衛", msg[:190], tag="warning")
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    dry = "--dry" in sys.argv
    ctx = _context()
    print(f"[growth_agent] 脈絡:{json.dumps(ctx, ensure_ascii=False)}")
    dec = _llm_decide(ctx) or _fallback_decide(ctx)
    problem = bool(dec.get("problem"))
    action = dec.get("action", "none")
    diag = dec.get("diagnosis", "")
    rc = dec.get("root_cause", "")
    print(f"[growth_agent] 判定:problem={problem} action={action} 根因={rc} 診斷={diag}")

    if not problem or action == "none":
        note = f"守衛巡檢:健康/正常退潮({diag})"
        print(f"[growth_agent] {note}")
        log_ops("成長守衛", note)
        return 0

    done = ""
    if action == "seed_winners":
        n = _seed_winners(dry)
        done = f"已偏產{n}支贏家題(front優先)"
    else:  # alert_only
        done = "此根因需人工處理(對外/發布/跨平台)"
    msg = f"觀看示警[{rc}]:{diag}。{done}。"
    print(f"[growth_agent][ALERT] {msg}")
    log_ops("成長守衛", msg)
    _notify(msg, dry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
