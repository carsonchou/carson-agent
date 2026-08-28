#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""brain_search.py — WorldQuant BRAIN alpha 自動搜尋器。

## 目標
把「找出通過門檻的 alpha」變成可重複執行的搜尋，而不是手動一條一條貼。
目標是 Consultant 資格（10,000 分）→ Grandmaster。

官方門檻（2026-08-26 從平台繁中頁實抓）：
  · 至少 10,000 分
  · 經驗法則：**5 個以上不同天數**提交 5~10 個 Alphas 可能達 10,000 分
  · **一天最多 2,000 分** ← 所以這是「跨天」的馬拉松，不是一天衝完

## 通過標準（2026-08-26 從 API 實抓的 checks，不是猜的）
    LOW_SHARPE               sharpe   >= 1.25
    LOW_FITNESS              fitness  >= 1.00
    LOW_TURNOVER             turnover >= 0.01
    HIGH_TURNOVER            turnover <= 0.70
    LOW_SUB_UNIVERSE_SHARPE  subSharpe>= 0.63
    CONCENTRATED_WEIGHT      (無數值門檻)
    SELF_CORRELATION         ← **真正的守門員**，與既有 alpha 太像就會被擋
    MATCHES_COMPETITION

## 🔴 三條硬規則（都是踩過的坑）

1. **絕不自動 submit。** 本檔只呼叫 `/simulations`（回測），永遠不碰提交端點。
   提交是把 alpha 送進 WorldQuant 的池子，那是 Carson 本人的決定。
2. **fail-closed。** 任何一步拿不到資料就標記失敗並記錄原因，
   **絕不寫一個看起來正常的數字**（memory `yt-quota-partial-failure-silent-bad-data`：
   同型壞值曾重複三次沒人發現）。
3. **去重。** 每條表達式+設定算 hash 進帳本，跑過的不再跑
   （memory `yt-make-video-duplicate-deadlock`：無防重鎖同 slug 派兩次工）。

## 命名規則
使用者自訂變數一律 `v_` 前綴。實測：`frac` 是保留字，會回
`Attempted to use reserved variable name`。`alpha` 幾乎必定同理。

## 認證
**密碼不寫在檔案裡。** 依序找：
  1. 環境變數 `BRAIN_EMAIL` / `BRAIN_PASSWORD`
  2. `quant-service/brain_alpha/.env`（已在 .gitignore）

## 用法
    python brain_search.py --list              # 只列候選,不打 API
    python brain_search.py --run 20            # 跑 20 條(跳過帳本裡有的)
    python brain_search.py --report            # 讀帳本出報表,不打 API
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("需要 requests：pip install requests", file=sys.stderr)
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parent
LEDGER = ROOT / "search_ledger.jsonl"
API = "https://api.worldquantbrain.com"

# 實抓的門檻（2026-08-26）。改這裡之前先重新從 API 的 checks 確認。
THRESHOLDS = {
    "sharpe": 1.25,
    "fitness": 1.00,
    "turnover_min": 0.01,
    "turnover_max": 0.70,
    "sub_sharpe": 0.63,
}

BASE_SETTINGS = {
    "instrumentType": "EQUITY", "region": "USA", "universe": "TOP3000",
    "delay": 1, "decay": 4, "neutralization": "SUBINDUSTRY", "truncation": 0.05,
    "pasteurization": "ON", "unitHandling": "VERIFY", "nanHandling": "OFF",
    "language": "FASTEXPR", "visualization": False,
}


# ────────────────────── 表達式產生器 ──────────────────────
# 骨架來自 data_hunter/scan.py 的真實因子邏輯，不是教科書因子。
# 每條都產正/反兩個方向 —— A2 實測 Fitness -0.10（方向反了），
# 證明「台股有效的方向」搬到美股不一定成立，所以方向必須當參數搜。

def _templates():
    """回傳 (名稱, 表達式樣板, 參數網格) 清單。樣板用 {p1}/{p2}/{sign} 填空。"""
    return [
        # 趨勢持續度：過去 N 天有多少比例待在 M 日均線之上（scan.py `_trend_frac`）
        ("trend_frac",
         "v_ab = close > ts_mean(close, {p2}) ? 1 : 0; "
         "v_tf = ts_mean(v_ab, {p1}); rank({sign}v_tf)",
         {"p1": [30, 60, 120], "p2": [10, 20, 60]}),

        # 雙框共振：短週期與長週期動能同向才留（scan.py `dual_frame`）
        ("dual_frame",
         "v_s = ts_delta(close, {p2}) / close; v_l = ts_delta(close, {p1}) / close; "
         "rank({sign}(sign(v_s) * sign(v_l) * v_l))",
         {"p1": [20, 25, 60], "p2": [3, 5, 10]}),

        # 波動歸一化動能（scan.py `adr_pct = atr22/price`）
        ("vol_norm_mom",
         "v_m = ts_delta(close, {p1}) / close; v_v = ts_std_dev(returns, {p2}); "
         "rank({sign}(v_m / (v_v + 0.0001)))",
         {"p1": [10, 20, 60], "p2": [22, 60]}),

        # 上升趨勢中的回檔（scan.py `drawdown_60`）
        ("pullback_in_trend",
         "v_hi = ts_max(close, {p1}); v_dd = (close - v_hi) / v_hi; "
         "v_up = ts_mean(close, {p2}) > ts_mean(close, {p1}); "
         "trade_when(v_up, rank({sign}v_dd), -1)",
         {"p1": [60, 120], "p2": [10, 20]}),

        # 流動性閘門 + 動能（scan.py `_turnover_60d` + POOL_TURNOVER_MIN）
        ("liquidity_gated_mom",
         "v_to = adv20 / cap; v_liq = ts_rank(v_to, {p2}) > 0.3; "
         "trade_when(v_liq, rank({sign}(ts_delta(close, {p1}) / close)), -1)",
         {"p1": [10, 20, 60], "p2": [60, 120]}),

        # 不追極端（scan.py `no_chase`：漲跌停排除 → 美股用 N 倍標準差表達）
        ("no_chase_reversal",
         "v_calm = abs(returns) < {p2} * ts_std_dev(returns, 20); "
         "trade_when(v_calm, rank({sign}(-ts_delta(close, {p1}))), -1)",
         {"p1": [3, 5, 10], "p2": [2, 3]}),

        # 量能異常（scan.py `relvol`）
        ("relvol_event",
         "v_rv = volume / ts_mean(volume, {p1}); v_ev = v_rv > {p2}; "
         "trade_when(v_ev, rank({sign}(ts_delta(close, 1) / close)), -1)",
         {"p1": [20, 60], "p2": [2, 3]}),
    ]


def generate():
    """展開所有候選。回傳 [(name, expr)]。"""
    out = []
    for name, tmpl, grid in _templates():
        keys = sorted(grid)
        for combo in itertools.product(*[grid[k] for k in keys]):
            params = dict(zip(keys, combo))
            for sign, tag in (("", "pos"), ("-", "neg")):
                expr = tmpl.format(sign=sign, **params)
                label = f"{name}|{'_'.join(f'{k}{v}' for k, v in params.items())}|{tag}"
                out.append((label, expr))
    return out


# ────────────────────── 帳本 ──────────────────────

def _key(expr: str, settings: dict) -> str:
    raw = expr + "|" + json.dumps(settings, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def load_ledger() -> dict:
    if not LEDGER.exists():
        return {}
    out = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            out[r["key"]] = r
        except Exception:  # noqa: BLE001
            continue          # 壞行跳過但不吞掉整個檔
    return out


def append_ledger(rec: dict) -> None:
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ────────────────────── API ──────────────────────

def _creds():
    email = os.environ.get("BRAIN_EMAIL")
    pw = os.environ.get("BRAIN_PASSWORD")
    if email and pw:
        return email, pw
    envf = ROOT / ".env"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k == "BRAIN_EMAIL":
                email = v
            elif k == "BRAIN_PASSWORD":
                pw = v
    if not (email and pw):
        raise SystemExit(
            "找不到憑證。設 BRAIN_EMAIL / BRAIN_PASSWORD 環境變數，"
            f"或建 {envf}（已在 .gitignore）。密碼不要寫進任何會進版控的檔。")
    return email, pw


def auth():
    email, pw = _creds()
    s = requests.Session()
    s.auth = (email, pw)
    r = s.post(f"{API}/authentication", timeout=30)
    if r.status_code not in (200, 201):
        raise SystemExit(f"認證失敗 HTTP {r.status_code}: {r.text[:300]}")
    s.auth = None          # 之後靠 cookie，不再每次送帳密
    return s


def simulate(s: requests.Session, expr: str, settings: dict, timeout_s: int = 420):
    """跑一條回測。回傳 (result_dict, error_str)。任何失敗 → (None, 原因)。"""
    body = {"type": "REGULAR", "settings": settings, "regular": expr}
    r = s.post(f"{API}/simulations", json=body, timeout=30)
    if r.status_code not in (200, 201):
        return None, f"POST {r.status_code}: {r.text[:200]}"
    loc = r.headers.get("Location")
    if not loc or "walkthrough" in loc:
        return None, f"沒拿到有效 Location（{loc}）— 帳號可能還卡在新手教學"

    t0 = time.time()
    sim = None
    while time.time() - t0 < timeout_s:
        p = s.get(loc, timeout=30)
        if p.status_code != 200:
            return None, f"poll {p.status_code}"
        sim = p.json()
        if sim.get("status") and sim["status"] != "RUNNING":
            break
        time.sleep(5)
    if not sim or sim.get("status") != "COMPLETE":
        return None, f"未完成（status={sim.get('status') if sim else 'None'}）"

    aid = sim.get("alpha")
    if not aid:
        return None, "COMPLETE 但沒有 alpha id（表達式可能有語法錯，看 message）: " \
                     + str(sim.get("message"))[:200]
    a = s.get(f"{API}/alphas/{aid}", timeout=30)
    if a.status_code != 200:
        return None, f"取 alpha {a.status_code}"
    return {"alpha_id": aid, "detail": a.json()}, None


def evaluate(detail: dict) -> dict:
    """把 API 的 checks 攤平成好判讀的結果。"""
    is_ = detail.get("is") or {}
    checks = {c.get("name"): c for c in (is_.get("checks") or [])}
    failed = [n for n, c in checks.items() if c.get("result") == "FAIL"]
    pending = [n for n, c in checks.items() if c.get("result") == "PENDING"]
    return {
        "sharpe": is_.get("sharpe"), "fitness": is_.get("fitness"),
        "turnover": is_.get("turnover"), "returns": is_.get("returns"),
        "drawdown": is_.get("drawdown"),
        "sub_sharpe": (checks.get("LOW_SUB_UNIVERSE_SHARPE") or {}).get("value"),
        "failed_checks": failed, "pending_checks": pending,
        "all_pass": (not failed),
    }


# ────────────────────── 主流程 ──────────────────────

def cmd_list():
    c = generate()
    print(f"候選總數：{len(c)}")
    for label, expr in c[:25]:
        print(f"\n[{label}]\n  {expr}")
    if len(c) > 25:
        print(f"\n... 另外 {len(c)-25} 條")


def cmd_report():
    led = load_ledger()
    if not led:
        print("帳本是空的，還沒跑過。")
        return
    rows = [r for r in led.values() if r.get("ok")]
    bad = [r for r in led.values() if not r.get("ok")]
    rows.sort(key=lambda r: (r["result"].get("fitness") or -99), reverse=True)
    print(f"已跑 {len(led)} 條：成功 {len(rows)}、失敗 {len(bad)}")
    print(f"\n{'label':<44}{'fitness':>9}{'sharpe':>9}{'turnover':>10}  未過項目")
    print("-" * 110)
    for r in rows[:30]:
        v = r["result"]
        f = v.get("fitness"); sh = v.get("sharpe"); to = v.get("turnover")
        mark = "✅" if v.get("all_pass") else "  "
        print(f"{mark}{r['label']:<42}{(f if f is not None else 0):>9.2f}"
              f"{(sh if sh is not None else 0):>9.2f}{(to if to is not None else 0):>10.2%}"
              f"  {','.join(v.get('failed_checks') or []) or '-'}")
    winners = [r for r in rows if r["result"].get("all_pass")]
    print(f"\n全數通過：{len(winners)} 條")
    for r in winners:
        print(f"  ✅ {r['label']}\n     {r['expr']}")
    if bad:
        print(f"\n失敗 {len(bad)} 條（前 5）：")
        for r in bad[:5]:
            print(f"  ✗ {r['label']}: {r.get('error')}")


def cmd_run(n: int):
    led = load_ledger()
    cands = [(l, e) for l, e in generate() if _key(e, BASE_SETTINGS) not in led]
    if not cands:
        print("所有候選都跑過了。用 --report 看結果。")
        return
    todo = cands[:n]
    print(f"待跑 {len(cands)} 條，本次跑 {len(todo)} 條。"
          f"（一次一條，每條數分鐘 — 多重模擬是顧問專屬功能）\n")
    s = auth()
    print("認證成功\n")
    for i, (label, expr) in enumerate(todo, 1):
        k = _key(expr, BASE_SETTINGS)
        print(f"[{i}/{len(todo)}] {label}")
        t0 = time.time()
        res, err = simulate(s, expr, BASE_SETTINGS)
        dt = time.time() - t0
        rec = {"key": k, "label": label, "expr": expr, "elapsed_s": round(dt, 1)}
        if err:
            rec.update(ok=False, error=err)
            print(f"      ✗ {err}  ({dt:.0f}s)")
        else:
            ev = evaluate(res["detail"])
            rec.update(ok=True, alpha_id=res["alpha_id"], result=ev)
            flag = "✅ 全過" if ev["all_pass"] else "未過:" + ",".join(ev["failed_checks"])
            print(f"      fitness={ev['fitness']} sharpe={ev['sharpe']} "
                  f"turnover={ev['turnover']}  {flag}  ({dt:.0f}s)")
        append_ledger(rec)      # 每條跑完立刻落檔，中途掛掉不會全丟
    print("\n完成。用 --report 看彙總。")
    print("⚠️ 本工具只做回測，**不會提交任何 alpha**。提交請你自己在平台上按。")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    a = sys.argv[1:]
    if "--list" in a:
        cmd_list()
    elif "--report" in a:
        cmd_report()
    elif "--run" in a:
        i = a.index("--run")
        n = int(a[i + 1]) if len(a) > i + 1 else 10
        cmd_run(n)
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
