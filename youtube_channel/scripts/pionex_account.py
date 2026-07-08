#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pionex_account.py — 抓 Pionex 帳戶真實餘額/報酬，寫進 STUDIO/ep_data.json（EP 全自動真數字源）。

簽章呼叫 Pionex 私有 API（需 PIONEX_API_KEY / PIONEX_API_SECRET，唯讀權限即可）。
計總資產(USDT 計價)；首次記錄為基準(baseline)，之後算報酬率。帳戶實質為空(<門檻)時 return_pct=None(EP 走懸念版)。
用法：python scripts/pionex_account.py
"""
from __future__ import annotations
import hashlib, hmac, json, os, sys, time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from studio_common import save_json_atomic
EP_DATA = ROOT / "STUDIO" / "ep_data.json"
BASE = "https://api.pionex.com"
KEY = os.environ.get("PIONEX_API_KEY", "").strip()
SECRET = os.environ.get("PIONEX_API_SECRET", "").strip()
MIN_REAL = 10.0  # 帳戶總值低於此(USDT)＝視為無實測，EP 走懸念版


def _signed_get(path, params=None):
    params = dict(params or {})
    params["timestamp"] = str(int(time.time() * 1000))
    q = "&".join(f"{k}={params[k]}" for k in sorted(params))
    purl = f"{path}?{q}"
    sig = hmac.new(SECRET.encode(), ("GET" + purl).encode(), hashlib.sha256).hexdigest()
    r = requests.get(BASE + purl, headers={"PIONEX-KEY": KEY, "PIONEX-SIGNATURE": sig}, timeout=20)
    return r.json()


def _f(x):
    try:
        return float(x)
    except Exception:
        return 0.0


def bot_summary():
    """抓執行中的交易機器人：回 (投入, 現值, 損益, 最早建立時間ms)。本金鎖在 bot,不在現貨餘額。"""
    d = _signed_get("/api/v1/bot/orders")
    if not d.get("result"):
        raise RuntimeError(f"API 失敗：{str(d)[:120]}")
    bots = (d.get("data", {}) or {}).get("results") or []
    invest = current = profit = 0.0
    earliest = None
    n = 0
    for b in bots:
        if b.get("closeTime") is not None:      # 已結束的不算
            continue
        bd = b.get("buOrderData", {}) or {}
        inv = _f(bd.get("quoteOriginalInvestment") or bd.get("quoteBaseAmount"))
        cur = _f(bd.get("currentQuoteAmount")) or inv
        pf = _f(bd.get("profit"))
        if inv <= 0:
            continue
        invest += inv; current += cur; profit += pf; n += 1
        ct = b.get("createTime")
        if ct:
            earliest = ct if earliest is None else min(earliest, ct)
    return round(invest, 2), round(current, 2), round(profit, 4), earliest, n


def main():
    if not (KEY and SECRET):
        print("[skip] 無 PIONEX_API_KEY/SECRET，EP 維持懸念版。", file=sys.stderr); return 0
    try:
        invest, current, profit, earliest, n = bot_summary()
    except Exception as e:
        print(f"[err] 抓 Pionex 失敗：{str(e)[:120]}", file=sys.stderr); return 1
    ep = {}
    if EP_DATA.exists():
        try:
            ep = json.loads(EP_DATA.read_text(encoding="utf-8"))
        except Exception:
            ep = {}
    if n > 0 and invest > 0:
        ep["investment"] = invest
        ep["account_value"] = current
        ep["profit"] = profit
        ep["return_pct"] = round(profit / invest * 100, 2)
        ep["bots"] = n
        if earliest:
            ep["day"] = max(0, int((time.time() * 1000 - earliest) / 86400000))
        print(f"[ok] Pionex 真實機器人 {n} 個：投入 {invest}，現值 {current}，損益 {profit}，"
              f"報酬 {ep['return_pct']}%，第 {ep.get('day','?')} 天")
    else:
        ep["return_pct"] = None  # 無執行中機器人 → EP 走懸念版
        print("[info] 無執行中機器人，EP 維持懸念版。")

    # === EP franchise 引擎：寫檔前注入累計戰績/里程碑/角色狀態（純函式、零外呼）===
    new_ms = []
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import ep_engine
        pct = ep.get("return_pct")
        dd = ep.get("max_drawdown")
        ep_engine.update_cumulative(ep, ep.get("account_value"), pct)
        already = list(ep.get("milestones_hit") or [])
        new_ms = ep_engine.check_milestones(pct, already)
        if new_ms:
            ep["milestones_hit"] = already + new_ms
        ep["character_state"] = ep_engine.advance_character(
            ep.get("character_state", "cautious"), pct, dd)
    except Exception as _e:  # noqa: BLE001
        new_ms = []
        print(f"[warn] EP 引擎注入略過：{str(_e)[:80]}", file=sys.stderr)

    save_json_atomic(EP_DATA, ep)

    # 有新里程碑 → 題庫插隊爆點題（下批優先製作）+ log
    if new_ms:
        try:
            from topic_bank import add_topics
            from ops import log_ops
            cur_ep = ep.get("current_ep", 0)
            topics = [ep_engine.milestone_topic(m, cur_ep) for m in new_ms]
            n = add_topics(topics, source="ep_milestone", front=True)
            log_ops("EP里程碑", f"觸發 {('、'.join(new_ms))} → 題庫插隊 {n} 支爆點題")
            print(f"[ok] EP 里程碑觸發：{'、'.join(new_ms)}，題庫插隊 {n} 支")
        except Exception as _e:  # noqa: BLE001
            print(f"[warn] 里程碑題注入略過：{str(_e)[:80]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
