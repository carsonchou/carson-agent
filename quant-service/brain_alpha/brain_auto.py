#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""brain_auto.py — WorldQuant BRAIN alpha 全自動搜尋（常駐版）。

Carson 的指示（2026-08-26）：全自動化，他只負責按提交，
有東西可提交時用 ntfy 通知他。

## 它做什麼
1. 持續搜尋 alpha（爬山式優化，不是亂槍網格）
2. 每條跑完存進帳本，可中斷可續跑
3. **任何一條通過全部檢查 → 立刻 ntfy 推播通知 Carson**
4. **永遠不提交。** 提交是 Carson 本人的動作

## 🔴 為什麼不自動提交
WorldQuant 競賽條款原文：偵測到「gaming、共享、作弊或其他不道德或不誠實行為」
→ **終止帳號、恕不另行通知、並可能通報**。
把參數網格掃出來的東西大量自動提交正中這條，而帳號沒了＝季付獎金歸零。
所以：搜尋全自動，提交人工把關。這條規則不要改。

## 搜尋策略
- **Phase 1 探索**：各因子家族 × 正反方向，找出哪個家族在美股有訊號
- **Phase 2 優化**：對目前最佳解做「降週轉但守住 Sharpe」的變換
  依據實測公式 `fitness ≈ sharpe × sqrt(|returns| / max(turnover, 0.125))`
  → Sharpe 已達標時，唯一槓桿就是把 turnover 壓下來
- 降週轉的正解是 `hump()`（BRAIN 專門用來限制部位變動的運算子），
  不是拉高平台 decay —— 實測 decay 15 會把 dual_frame 的 Sharpe 從 1.31 砍到 0.70

## 已知門檻（2026-08-26 從 API checks 實抓）
    LOW_SHARPE  >=1.25 | LOW_FITNESS >=1.00 | HIGH_TURNOVER <=0.70
    LOW_SUB_UNIVERSE_SHARPE >=0.57~0.63 | CONCENTRATED_WEIGHT | SELF_CORRELATION

## 已知地雷
- 保留字：`frac` 會被拒 → 自訂變數一律 `v_` 前綴
- 單位系統：`ts_std_dev(returns,22) + 0.0001` 不合法
  （`Incompatible unit ... expected Unit[TSPrice:1], found Unit[]`）→ 不要加裸常數
- 併發上限 2，第 3 條回 429

## 用法（由 local_cron 排程呼叫，不需人工）
    python brain_auto.py --run 30      # 跑 30 條
    python brain_auto.py --report      # 只看帳本
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("需要 requests：pip install requests", file=sys.stderr)
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
LEDGER = ROOT / "auto_ledger.jsonl"
STATE = ROOT / "auto_state.json"
API = "https://api.worldquantbrain.com"

BASE = {
    "instrumentType": "EQUITY", "region": "USA", "universe": "TOP3000",
    "delay": 1, "decay": 4, "neutralization": "SUBINDUSTRY", "truncation": 0.05,
    "pasteurization": "ON", "unitHandling": "VERIFY", "nanHandling": "OFF",
    "language": "FASTEXPR", "visualization": False,
}

# delay 用環境變數覆寫，**預設維持 1**（不改變既有行為）。
# 為什麼不直接改上面那行：2026-09-03 實測 delay=1 的搜尋空間已挖穿 ——
# 平台 /data-sets 對 USA/delay=1 只開 14 個資料集，而帳本 142 個標籤涵蓋全部 14 個，
# 從沒碰過的是 0 個。要換 delay=0（11 個資料集 / 2,121 欄位）試獨立性。
# 但把寫死的 1 改成寫死的 0 只是換一個坑 —— 兩邊都要能跑，所以做成參數。
# 下游全部走 dict(BASE) 複製，所以在這裡覆寫一次就會傳到每一組 settings。
_d = os.environ.get("BRAIN_DELAY")
if _d is not None:
    BASE["delay"] = int(_d)

# Phase 1 找到的最佳骨架：dual_frame 反向、短窗（Sharpe 1.31 已過門檻）
LEADER = ("v_s = ts_delta(close, {w2}) / close; v_l = ts_delta(close, {w1}) / close; "
          "{inner}")


# ────────────────────── 通知 ──────────────────────

TG_CONFIG = Path(os.path.expanduser("~")) / ".stock_monitor" / "config.json"


def _tg_creds():
    """優先用 BRAIN 專屬 bot（.env 的 TG_BOT_TOKEN / TG_CHAT_ID）。

    Carson 2026-08-27 專門為 BRAIN 通知開了 @carson_brain_bot，
    因為跟 009816 盯盤訊號混在同一個對話會看不到。
    找不到專屬設定才退回 ~/.stock_monitor/config.json 那組。
    """
    tok = os.environ.get("TG_BOT_TOKEN"); chat = os.environ.get("TG_CHAT_ID")
    if not (tok and chat):
        f = ROOT / ".env"
        if f.exists():
            for ln in f.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln or ln.startswith("#") or "=" not in ln:
                    continue
                k, v = ln.split("=", 1); k = k.strip(); v = v.strip().strip('"').strip("'")
                if k == "TG_BOT_TOKEN": tok = tok or v
                elif k == "TG_CHAT_ID": chat = chat or v
    if tok and chat:
        return tok, chat, "brain_bot"
    try:                                    # 後備：009816 盯盤那組
        cfg = json.loads(TG_CONFIG.read_text(encoding="utf-8"))
        return cfg.get("token"), cfg.get("chat_id"), "stock_monitor_bot"
    except Exception:  # noqa: BLE001
        return None, None, "none"


def _telegram(text: str) -> bool:
    try:
        tok, chat, src = _tg_creds()
        if not (tok and chat):
            print("[tg] 找不到 token/chat_id", file=sys.stderr); return False
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          data={"chat_id": chat, "text": text}, timeout=20)
        if r.status_code != 200:
            print(f"[tg] HTTP {r.status_code}: {r.text[:200]}", file=sys.stderr)
            return False
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[tg] 例外：{e}", file=sys.stderr)
        return False


def _ntfy(title: str, body: str) -> bool:
    try:
        sys.path.insert(0, str(REPO / "youtube_channel" / "scripts"))
        import notify as _n
        return bool(_n.push(title, body, "moneybag"))
    except Exception as e:  # noqa: BLE001
        print(f"[ntfy 失敗] {e}", file=sys.stderr)
        return False


def notify(title: str, body: str) -> bool:
    """主管道 Telegram，ntfy 當備援。兩個都失敗才算失敗（並印出來，不靜默）。"""
    ok_tg = _telegram(f"{title}\n\n{body}")
    if ok_tg:
        return True
    print("[notify] Telegram 失敗,改試 ntfy", file=sys.stderr)
    return _ntfy(title, body)


# ────────────────────── 候選產生 ──────────────────────

def candidates():
    """Phase 2：對目前最佳骨架做「降週轉但守住 Sharpe」的變換。

    🔴 2026-08-27 換靶：原本主打 dual_frame（Sharpe 1.31），但掃描跑出 **no_chase 短窗更強**：
        no_chase|w3|decay4   sharpe 1.68  fitness 0.84  turnover 54.2%
        no_chase|w3|decay15  sharpe 1.42  fitness 0.93  turnover 29.7%  ← 只差 0.07
        (對照)dual_frame|20_3 sharpe 1.31  fitness 0.63  turnover 57.5%
    所以火力集中在 no_chase。dual_frame 那組留在後段當備援。

    另一個實測參考點：中性化關掉(NONE)可讓 fitness 衝到 1.31、turnover 掉到 15.8%，
    但 Sharpe 被打到 0.82 —— 證明 fitness 破 1.0 不難，難的是**同時**守住 Sharpe≥1.25。
    """
    out = []

    # ══════════════════════════════════════════════════════════════════
    # Phase 8 — 沒用過的運算子（2026-08-27，讀完 /learn/operators 全文後）
    #
    # 前面 300+ 條只用了 66 個運算子裡的 22 個。以下五個直接打在卡關點上：
    #
    #   ts_regression(y,x,d,lag,rettype) —— 取**殘差**＝把訊號對另一因子正交化。
    #        這是攻擊 SELF_CORRELATION 的正統做法（官方 checks 唯一沒解法的那項）。
    #   ts_quantile —— 用反累積分布轉換 ts_rank,分布更均勻 → 壓 CONCENTRATED_WEIGHT。
    #   days_from_last_change —— 「距離上次數值變動幾天」。套在財報欄位＝
    #        「距離上次財報更新多久」。**維度全新**（別人算幅度,這個算時間）,
    #        天生低週轉,對 SELF_CORRELATION 極有利。
    #   group_backfill —— 用同產業的值補缺漏,對稀疏財報比 ts_backfill 更合理。
    #   signed_power(x, 0.5) —— 保留正負號的開根號,馴服極端值而不翻轉方向。
    # ══════════════════════════════════════════════════════════════════
    NEWOP = dict(BASE); NEWOP.update(decay=0, truncation=0.1, nanHandling="ON")
    RATIOS = {"esteps": "est_eps/close",
              "opinc": "operating_income/equity",
              "fcf": "free_cash_flow_reported_value/equity"}
    for nm, ratio in RATIOS.items():
        bf = f"winsorize(ts_backfill({ratio}, 120), std=4)"
        gbf = f"group_backfill({ratio}, subindustry, 120)"
        # (1) ts_quantile 取代 ts_rank：分布更均勻
        out.append((f"N8|{nm}|tsquant", f"group_rank(ts_quantile({bf}, 126), subindustry)", dict(NEWOP)))
        # (2) 殘差正交化：把因子對「市場整體」迴歸,只留獨有的部分
        out.append((f"N8|{nm}|resid",
                    f"group_rank(ts_regression({bf}, ts_mean(close, 20), 250, rettype=0), subindustry)", dict(NEWOP)))
        # (3) group_backfill：用同業補值而非自己的歷史
        out.append((f"N8|{nm}|gbf", f"group_rank(ts_rank({gbf}, 126), subindustry)", dict(NEWOP)))
        # (4) signed_power 馴服極端值
        out.append((f"N8|{nm}|spow", f"group_rank(signed_power(ts_zscore({bf}, 63), 0.5), subindustry)", dict(NEWOP)))
        # (5) 距離上次變動幾天 —— 全新維度
        for d in (250, 500):
            out.append((f"N8|{nm}|dflc{d}",
                        f"group_rank(days_from_last_change({bf}), subindustry)", dict(NEWOP)))
            break
        out.append((f"N8|{nm}|dflc_neg",
                    f"group_rank(-days_from_last_change({bf}), subindustry)", dict(NEWOP)))
    # (6) 純 days_from_last_change 因子（不綁比率，看時間維度本身有沒有訊號）
    for f in ("operating_income", "est_eps", "sales", "assets"):
        out.append((f"N8|raw|dflc|{f}",
                    f"group_rank(days_from_last_change(ts_backfill({f}, 250)), subindustry)", dict(NEWOP)))

    # ══════════════════════════════════════════════════════════════════
    # Phase 7 — 縮小 universe（2026-08-27，依官方 Challenge 計分規則）
    #
    # 官方 FAQ 原文（support.worldquantbrain.com/hc/en-us/articles/21210168520855）：
    #   Quality factor 由四項決定 —— **Universe（smaller universes get more score）**、
    #   SelfCorrelation（越低越好）、Fitness（越高越好）、Delay（D1 > D0）。
    #
    # 我先前 95% 的模擬都跑 TOP3000 —— **那是最大的池，直接在計分上扣分**。
    # 這一批把已知有效的表達式全部搬到小池重跑。
    #
    # 另外兩條官方規則影響策略：
    #   · 「Quality factor is calculated as an **average** of the quality factor of all
    #     Alphas submitted **during the day**」→ 當天交一條爛的會拉低整天平均，
    #     所以**寧可少交也不要交爛的**。
    #   · 「Scores ... can go up ... based on **out-of-sample performance** ... on a
    #     **weekly basis**」→ 已提交的 alpha 會持續加分，
    #     所以 year_quality（近年撐不撐得住）比原本想的更重要。
    # ══════════════════════════════════════════════════════════════════
    SMALL = dict(BASE); SMALL.update(decay=0, truncation=0.1, nanHandling="ON")
    PROVEN = {   # 已實測雙門檻達標的表達式（在 TOP3000 上）
        "esteps": "group_rank(ts_rank(winsorize(ts_backfill(est_eps/close, 120), std=4), 126), subindustry)",
        "opinc":  "group_rank(ts_rank(winsorize(ts_backfill(operating_income/equity, 120), std=4), 126), subindustry)",
        "fcf":    "group_rank(ts_rank(winsorize(ts_backfill(free_cash_flow_reported_value/equity, 120), std=4), 126), subindustry)",
        "estz":   "ts_zscore(winsorize(ts_backfill(est_eps/close, 120), std=4), 63)",
        "buzz":   "-ts_std_dev(ts_backfill(scl12_buzz, 120), 10)",
    }
    for name, ex in PROVEN.items():
        for u in ("TOP500", "TOP1000", "TOP2000"):
            s = dict(SMALL); s["universe"] = u
            out.append((f"U|{name}|{u}", ex, s))
            # 小池子波動大,配 truncation 0.05 再試一組
            s2 = dict(s); s2["truncation"] = 0.05
            out.append((f"U|{name}|{u}|tr05", ex, s2))

    # ══════════════════════════════════════════════════════════════════
    # Phase 6 — 三條原創設計（2026-08-27）
    #
    # ⚠️ 先修一個我自己的錯：`ts_target_tvr_decay` **不存在**（免費帳號只有 66 個
    #    運算子，見 OPERATORS.txt）。Phase 5 用到它的 6 條會全部語法失敗，
    #    留著當紀錄不刪 —— 那是「別人 repo 寫的不等於我這個帳號能用」的證據。
    #    同理 Carson 給的規格裡 `correlation` / `decay_linear` / `ts_returns` 也都不存在。
    #
    # 這三條的設計依據是**今晚的實測**，不是理論：
    #   · socialmedia 資料能同時給出 Sharpe 1.52 + fitness 1.26（pv1 做不到）
    #   · 卡關的是 CONCENTRATED_WEIGHT 與 LOW_SUB_UNIVERSE_SHARPE
    #   · 官方對 weight test 的三修法 = rank + truncation 0.1 + ts_backfill
    #   · sub-universe 門檻是**相對值**，會隨自己的 Sharpe 一起漲 → 要靠產業內
    #     正規化把訊號攤平到各產業，而不是靠拉高總 Sharpe
    # ══════════════════════════════════════════════════════════════════
    D = dict(BASE); D.update(decay=0, truncation=0.1, nanHandling="ON")
    BZW = "winsorize(ts_backfill(scl12_buzz, 120), std=4)"

    # A1 情緒波動衰竭：買「安靜下來」的股票。group_zscore 在產業內部標準化,
    #    直接壓 CONCENTRATED_WEIGHT 與 sub-universe 的產業集中。
    for w in (10, 20, 40):
        out.append((f"D1|calm|w{w}",
                    f"group_zscore(rank(-ts_std_dev({BZW}, {w})), subindustry)", dict(D)))
        out.append((f"D1|calm_gs|w{w}",
                    f"group_scale(rank(-ts_std_dev({BZW}, {w})), subindustry)", dict(D)))

    # A2 價量關係破裂：ts_corr(close,volume) 的**變化**——關係斷裂代表知情交易進場。
    #    這是 Carson 規格裡模板 B 的想法,但用對的運算子名(ts_corr 非 correlation)。
    for cw in (10, 20):
        for dw in (5, 10):
            sig = f"-ts_delta(ts_corr(close, volume, {cw}), {dw})"
            out.append((f"D2|pvbreak|c{cw}d{dw}",
                        f"rank(ts_decay_linear(group_neutralize({sig}, subindustry), 5))", dict(D)))

    # A3 動能年齡：ts_arg_max = 距離高點幾天。行為錨定,天生低換手,
    #    且與價格「幅度」類因子低相關(它只看時間不看幅度)→ 對 SELF_CORRELATION 有利。
    for lb in (60, 120, 250):
        out.append((f"D3|peakage|{lb}",
                    f"rank(ts_decay_linear(group_neutralize(ts_arg_max(close, {lb}), subindustry), 10))", dict(D)))
        out.append((f"D3|peakage_n|{lb}",
                    f"rank(ts_decay_linear(group_neutralize(-ts_arg_max(close, {lb}), subindustry), 10))", dict(D)))

    # ══════════════════════════════════════════════════════════════════
    # Phase 5 — 抄實戰者（2026-08-27，來自 MINING_TECHNIQUES.md / COMMUNITY_TIPS.md）
    #
    # 兩份研究挖到三條**別人實測雙過**的表達式與兩個我不知道存在的運算子。
    # 先逐字驗證別人的成果，再改造 —— 不要再從零猜。
    #
    # 關鍵新知：
    #   · `ts_target_tvr_decay(x, lambda_min, lambda_max, target_tvr)`
    #     ——**直接指定目標換手率**。我整晚在用 decay/hump 間接壓 turnover，
    #       原來平台有專門的運算子。
    #   · `winsorize(ts_backfill(f, 120), std=4)`
    #     ——一次解 coverage + CONCENTRATED_WEIGHT + 稀疏欄位（我目前正卡 CW）。
    #   · 社群通過率：基本面 40% / 混合 12.7% / 純技術 5.3%。
    #     我 200 條全在 5.3% 桶。基本面要用**比率**不是原始值（除掉規模）。
    # ══════════════════════════════════════════════════════════════════
    R = dict(BASE); R.update(decay=0, truncation=0.1, nanHandling="ON")

    # (A) 別人實測雙過的三條，逐字先驗（欄位可能在 USA/delay1 不存在，失敗會如實記錄）
    for lbl, ex, nz in (
        ("ref|ev_ebitda", "-ts_zscore(enterprise_value/ebitda, 63)", "INDUSTRY"),
        ("ref|buzzvec", "ts_av_diff(ts_backfill(-vec_sum(scl12_alltype_buzzvec), 20), 60)", "SUBINDUSTRY"),
    ):
        s = dict(R); s["neutralization"] = nz
        out.append((f"REF|{lbl}", ex, s))

    # (B) 把新運算子套在**我今天突破的那條**上（Sharpe 1.52 / fitness 1.26，卡 CW + subUnivSharpe）
    BZ = "ts_backfill(scl12_buzz, 120)"
    for w in (10, 20):
        raw = f"-ts_std_dev({BZ}, {w})"
        # winsorize：官方與社群都指向它解 CONCENTRATED_WEIGHT
        out.append((f"NEW|wins|w{w}",
                    f"rank(-ts_std_dev(winsorize({BZ}, std=4), {w}))", dict(R)))
        out.append((f"NEW|wins_nornk|w{w}",
                    f"-ts_std_dev(winsorize({BZ}, std=4), {w})", dict(R)))
        # ts_target_tvr_decay：直接指定換手率，取代我瞎轉的 decay/hump
        for tvr in (0.05, 0.10, 0.20):
            out.append((f"NEW|tvr{tvr}|w{w}",
                        f"ts_target_tvr_decay(rank({raw}), lambda_min=0.5, lambda_max=1, target_tvr={tvr})",
                        dict(R)))
        # group_neutralize + winsorize 疊加
        out.append((f"NEW|wins_grp|w{w}",
                    f"group_neutralize(rank(-ts_std_dev(winsorize({BZ}, std=4), {w})), subindustry)",
                    dict(R)))

    # (C) 基本面**比率** + 社群「黃金組合」模板 group_rank(ts_rank(x,126), subindustry)
    for lbl, ratio in (
        ("opinc_eq", "operating_income/equity"),
        ("esteps_close", "est_eps/close"),
        ("fcf_eq", "free_cash_flow_reported_value/equity"),
        ("ev_ebitda", "enterprise_value/ebitda"),
    ):
        bf = f"winsorize(ts_backfill({ratio}, 120), std=4)"
        out.append((f"RAT|{lbl}|golden", f"group_rank(ts_rank({bf}, 126), subindustry)", dict(R)))
        out.append((f"RAT|{lbl}|zs63", f"-ts_zscore({bf}, 63)", dict(R)))
        out.append((f"RAT|{lbl}|zs63n", f"ts_zscore({bf}, 63)", dict(R)))
        s = dict(R); s["neutralization"] = "INDUSTRY"
        out.append((f"RAT|{lbl}|zs63|IND", f"-ts_zscore({bf}, 63)", s))

    # ══════════════════════════════════════════════════════════════════
    # Phase 4 — 攻頂（2026-08-27）。**第一條同時通過 Sharpe 與 fitness 的 alpha。**
    #
    #   OFF|scl12_buzz|std10n   Sharpe 1.52 ✅  fitness 1.26 ✅  turnover 22.3%
    #   表達式：-ts_std_dev(ts_backfill(scl12_buzz, 120), 10)
    #   設定：decay=0, truncation=0.1, SUBINDUSTRY
    #   仍未過：CONCENTRATED_WEIGHT、LOW_SUB_UNIVERSE_SHARPE
    #
    # 這推翻了「Sharpe 與 fitness 必然蹺蹺板」的假設 —— 蹺蹺板只存在於**同一個訊號
    # 調參數**時。換到夠冷門、性質不同的資料（socialmedia12 只有 5.7 萬條 alpha，
    # 對比 pv1 的 206 萬條），兩個指標可以一起上。
    #
    # 剩下兩項官方教材都有明確解法：
    #   · CONCENTRATED_WEIGHT → "Adding range-normalized functions such as **rank**,
    #     setting truncation at 0.1, and using ts_backfill"
    #     ← 我已有 truncation 0.1 與 ts_backfill，**獨缺 rank**。這是最可能的一擊。
    #   · LOW_SUB_UNIVERSE_SHARPE → 門檻是相對值
    #     `0.75 * sqrt(subuniverse_size/alpha_universe_size) * alpha_sharpe`，
    #     且教材點名 size 乘數是殺手；官方液性分段 decay 是唯一同時處理它與 turnover 的配方。
    # ══════════════════════════════════════════════════════════════════
    WIN = dict(BASE); WIN.update(decay=0, truncation=0.1, nanHandling="ON")
    BUZZ = "ts_backfill(scl12_buzz, 120)"
    for w in (5, 10, 20, 40):
        core = f"-ts_std_dev({BUZZ}, {w})"
        # (1) 主修：加 rank 做 range normalization（官方對 weight test 的第一修法）
        out.append((f"TOP|rank|w{w}", f"rank({core})", dict(WIN)))
        # (2) rank + 不同 truncation
        for tr in (0.05, 0.15, 0.2):
            s = dict(WIN); s["truncation"] = tr
            out.append((f"TOP|rank|w{w}|tr{tr}", f"rank({core})", s))
        # (3) rank + 產業中性化層級（影響 sub-universe sharpe）
        for nz in ("INDUSTRY", "MARKET", "SECTOR"):
            s = dict(WIN); s["neutralization"] = nz
            out.append((f"TOP|rank|w{w}|{nz}", f"rank({core})", s))
        # (4) group_neutralize：把訊號在產業內部正規化，直接壓集中度
        out.append((f"TOP|grpneut|w{w}",
                    f"group_neutralize(rank({core}), subindustry)", dict(WIN)))
        # (5) 官方液性分段 decay（唯一同時處理 turnover 與 sub-universe 的配方）
        out.append((f"TOP|liq|w{w}",
                    f"ts_decay_linear(rank({core}), 5) * rank(volume*close) + "
                    f"ts_decay_linear(rank({core}), 10) * (1 - rank(volume*close))",
                    dict(WIN)))
        # (6) 縮小 universe：sub-universe 門檻與 universe 大小相關
        for u in ("TOP1000", "TOP500"):
            s = dict(WIN); s["universe"] = u
            out.append((f"TOP|rank|w{w}|{u}", f"rank({core})", s))
    # (7) 同資料集的其他欄位，看訊號是欄位特有還是資料集共通
    for f in ("scl12_buzz", "scl12_sentiment", "scl12_total_buzz"):
        bf = f"ts_backfill({f}, 120)"
        out.append((f"TOP|alt|{f}", f"rank(-ts_std_dev({bf}, 10))", dict(WIN)))

    # ══════════════════════════════════════════════════════════════════
    # Phase 3 — 訊號組合（2026-08-27）。**這是跳出蹺蹺板的唯一數學出路。**
    #
    # 前 208 條全是單一因子，結果全部落在同一條權衡曲線上：
    #     Sharpe 1.46 × fitness 0.90   (價量快訊號:Sharpe 夠、週轉 36% 拖垮 fitness)
    #     Sharpe 0.77 × fitness 1.33   (基本面慢訊號:週轉 6.6%、但 Sharpe 死)
    # 官方也承認 "Improving one factor normally has an adverse impact on the other"。
    #
    # 但那句話講的是**同一個訊號**的參數調整。兩個**弱相關**訊號線性組合時：
    #   · Sharpe 約按 sqrt(N) 上升（分散效果）
    #   · turnover **不會**等比上升（兩訊號的換手部分互相抵銷）
    #   → fitness = Sharpe × sqrt(returns/turnover) 的分子分母同時改善,曲線整條外推。
    #
    # 這不是調參數,是換問題。原料我已經有了:快訊號有 Sharpe、慢訊號有低週轉。
    # ══════════════════════════════════════════════════════════════════
    FAST = "rank(-ts_delta(close, 3))"                     # 實測 Sharpe 1.46
    SLOW = {                                               # 實測週轉 6~10%
        "fs_total": "rank(ts_backfill(fscore_total, 120))",
        "fs_value": "rank(ts_backfill(fscore_value, 120))",
        "fs_qual":  "rank(ts_backfill(fscore_quality, 120))",
        "opinc":    "rank(ts_rank(ts_backfill(operating_income, 120), 252))",
    }
    CMB = dict(BASE); CMB.update(decay=4, truncation=0.1, nanHandling="ON")
    for sk, sexpr in SLOW.items():
        # (a) 線性混合:快訊號扛 Sharpe、慢訊號稀釋週轉並補報酬
        for w in (0.3, 0.5, 0.7):
            out.append((f"CMB|lin{w}|{sk}",
                        f"{w} * {FAST} + {1 - w:.1f} * {sexpr}", dict(CMB)))
        # (b) 條件式交互:只在基本面好的一半股票上做價量反轉
        #     （這是 Carson `scan.py` 的 no_chase 紀律往上抽象一層——
        #       原本是「不追極端價格」,這裡變成「不碰基本面差的」）
        out.append((f"CMB|cond|{sk}",
                    f"trade_when({sexpr} > 0.5, {FAST}, -1)", dict(CMB)))
        # (c) 乘法交互:讓基本面分數當價量訊號的權重,而不是另一個獨立部位
        out.append((f"CMB|mul|{sk}",
                    f"{FAST} * {sexpr}", dict(CMB)))
    # (d) 三訊號合成:快 + 兩個弱相關的慢訊號
    out.append(("CMB|tri|fast_value_qual",
                f"0.5 * {FAST} + 0.25 * {SLOW['fs_value']} + 0.25 * {SLOW['fs_qual']}",
                dict(CMB)))

    # ══════════════════════════════════════════════════════════════════
    # 官方教材寫法（2026-08-27 讀完 9 篇官方 tutorial 後改寫，`OFFICIAL_RULES.md`）
    # 這批優先，因為教材直接推翻了我原本的三個做法：
    #   1. "We recommend exploring the price volume dataset, **model dataset and
    #      fundamental dataset**" —— 我 106 條全掛在最擁擠的 pv1(已被建 206 萬條)
    #   2. "It is generally better to try out **new ideas with low correlation** than
    #      to improve performance of Alphas with high correlation" —— 我做的正是後者
    #   3. fitness 分母是 max(turnover, **0.125**) —— 壓到 12.5% 以下零增益,
    #      我後期把 turnover 從 29.7% 壓到 6.6% 全是白工,該拉的是分子 returns
    # 官方範例的形狀:**單運算子包基本面欄位**、decay=0、truncation=0.1、
    # neutralization=INDUSTRY/SUBINDUSTRY,比我在堆的巢狀式簡單得多。
    # `ts_backfill` 是官方對 weight test / 覆蓋率不足的指定解法。
    # ══════════════════════════════════════════════════════════════════
    OFF = dict(BASE); OFF.update(decay=0, truncation=0.1, nanHandling="ON")
    for f in ("operating_income", "est_eps", "scl12_buzz", "fscore_total",
              "fscore_value", "fscore_quality", "fscore_momentum",
              "cashflow_efficiency_rank_derivative", "earnings_certainty_rank_derivative"):
        bf = f"ts_backfill({f}, 120)"
        for lbl, ex in ((f"tsrank252", f"ts_rank({bf}, 252)"),
                        (f"tsrank252n", f"-ts_rank({bf}, 252)"),
                        (f"rank", f"rank({bf})"),
                        (f"d20", f"rank(ts_delta({bf}, 20))"),
                        (f"std10n", f"-ts_std_dev({bf}, 10)")):
            out.append((f"OFF|{f}|{lbl}", ex, dict(OFF)))
        s = dict(OFF); s["neutralization"] = "INDUSTRY"
        out.append((f"OFF|{f}|tsrank252|IND", f"ts_rank({bf}, 252)", s))

    # 官方「液性分段 decay」配方（教材裡唯一同時處理 turnover 與 sub-universe 的表達式）
    for sig in ("rank(-ts_delta(close, 3))", "rank(-ts_delta(close, 5))"):
        ex = (f"ts_decay_linear({sig}, 5) * rank(volume*close) + "
              f"ts_decay_linear({sig}, 10) * (1 - rank(volume*close))")
        for tr in (0.05, 0.1):
            s = dict(BASE); s.update(decay=4, truncation=tr)
            out.append((f"OFF|liqdecay|{sig[-3:-1]}|tr{tr}", ex, s))

    # ── 備援：no_chase 短窗（原本的主力，留著但降優先度）──
    def nc(w, inner):
        return (f"v_calm = abs(returns) < 3 * ts_std_dev(returns, 20); "
                f"trade_when(v_calm, {inner}, -1)").replace("SIG", f"rank(-ts_delta(close, {w}))")

    for w in (2, 3, 4):
        for d in (15, 20, 25, 30):          # 純 decay 掃(基準線在 d15)
            s = dict(BASE); s["decay"] = d
            out.append((f"NC|w{w}|d{d}", nc(w, "SIG"), s))
        for h in (0.003, 0.01, 0.02, 0.04):  # hump 壓週轉,保留低 decay 的高 Sharpe
            for d in (4, 10, 15):
                s = dict(BASE); s["decay"] = d
                out.append((f"NC|w{w}|hump{h}|d{d}",
                            nc(w, f"hump(rank(-ts_delta(close, {w})), hump={h})"), s))
        for nz in ("INDUSTRY", "NONE"):      # 中性化層級是 Sharpe/fitness 的權衡旋鈕
            for d in (15, 20):
                s = dict(BASE); s["neutralization"] = nz; s["decay"] = d
                out.append((f"NC|w{w}|nz{nz}|d{d}", nc(w, "SIG"), s))

    # ── 備援：dual_frame 反向（Sharpe 1.31，次強骨架）──
    core = "-(sign(v_s) * sign(v_l) * v_l)"
    for w1, w2 in ((20, 3), (15, 3)):
        # hump：限制部位變動幅度 → 直接壓週轉，這是 BRAIN 的正解運算子
        for h in (0.001, 0.003, 0.01, 0.03, 0.05):
            out.append((f"hump{h}|w{w1}_{w2}",
                        LEADER.format(w1=w1, w2=w2, inner=f"hump(rank({core}), hump={h})"), dict(BASE)))
        # ts_decay_linear：表達式內平滑（與平台 decay 不同層）
        for n in (3, 5, 10, 20):
            out.append((f"declin{n}|w{w1}_{w2}",
                        LEADER.format(w1=w1, w2=w2, inner=f"ts_decay_linear(rank({core}), {n})"), dict(BASE)))
        # hump + 內部平滑 疊加
        for h in (0.003, 0.01):
            for n in (5, 10):
                out.append((f"hump{h}_declin{n}|w{w1}_{w2}",
                            LEADER.format(w1=w1, w2=w2,
                                          inner=f"hump(ts_decay_linear(rank({core}), {n}), hump={h})"), dict(BASE)))
    # 中性化層級也影響報酬結構
    for nz in ("INDUSTRY", "MARKET"):
        s = dict(BASE); s["neutralization"] = nz
        out.append((f"hump0.01|nz{nz}",
                    LEADER.format(w1=20, w2=3, inner=f"hump(rank({core}), 0.01)"), s))
    return out


# ────────────────────── 帳本 ──────────────────────

def _key(expr, settings):
    return hashlib.sha1((expr + json.dumps(settings, sort_keys=True)).encode()).hexdigest()[:16]


def _is_infra(rec) -> bool:
    """這筆是「基礎設施沒讓它跑」，不是「跑了、結果不行」。

    🔴 2026-09-01：帳本 26,261 條裡有 **17,401 條（66.3%）**是
    `無有效 Location` —— 那是 15 次 429 退避後放棄，模擬**從來沒送出去過**。
    而它們照樣被寫進帳本，於是 `unscanned_fields()` 把那 1,808 個欄位算成
    「掃過了」，永遠不會重試。憑空丟掉 1,808 個欄位的搜尋結果。

    同型事故第二次：memory `yt-quota-partial-failure-silent-bad-data`
    記的是「配額耗盡 → 靜默壞資料落檔」，這次是「併發滿 → 沒跑過的當跑過」。
    共同點都是**失敗被當成有效結果存起來**。
    """
    e = str((rec or {}).get("error") or "")
    return e.startswith("INFRA:") or "無有效 Location" in e


def load_ledger():
    if not LEDGER.exists():
        return {}
    out = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        # 舊檔裡已經寫進去的 INFRA 失敗直接忽略 → 那些欄位自動變回「未掃」。
        # 不改寫 10MB 的歷史檔（append-only 是這個檔的價值），只是讀的時候不採信。
        if _is_infra(r):
            continue
        out[r["key"]] = r
    return out


def append(rec):
    # 唯一的寫入口。基礎設施失敗**不落檔** —— 落了就等於把那個欄位標記成掃過。
    if _is_infra(rec):
        return
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_state():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"notified": []}


def save_state(s):
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


# ────────────────────── API ──────────────────────

def _creds():
    e = os.environ.get("BRAIN_EMAIL"); p = os.environ.get("BRAIN_PASSWORD")
    if not (e and p):
        f = ROOT / ".env"
        if f.exists():
            for ln in f.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln or ln.startswith("#") or "=" not in ln:
                    continue
                k, v = ln.split("=", 1); k = k.strip(); v = v.strip().strip('"').strip("'")
                if k == "BRAIN_EMAIL": e = v
                elif k == "BRAIN_PASSWORD": p = v
    if not (e and p):
        raise SystemExit("找不到憑證（BRAIN_EMAIL / BRAIN_PASSWORD 或 .env）")
    return e, p


def auth():
    e, p = _creds()
    s = requests.Session(); s.auth = (e, p)
    r = s.post(f"{API}/authentication", timeout=30)
    if r.status_code not in (200, 201):
        raise SystemExit(f"認證失敗 {r.status_code}: {r.text[:200]}")
    s.auth = None
    return s


def simulate(s, expr, settings, timeout_s=600):
    """跑一條回測。

    🔴 2026-08-28 修：session token 會過期，原本碰到 **401 直接當失敗記進帳本**。
    結果一次長跑裡 **2,349 條**全是 401 —— 那些欄位被標記成「跑過了」寫進帳本，
    去重機制讓它們**永遠不會被重試**，等於憑空丟掉 2,349 個欄位的搜尋結果。
    （同型坑：memory `yt-quota-partial-failure-silent-bad-data` 的「靜默壞資料」，
      失敗被當成有效結果落檔。）
    → 現在 401 會就地重新認證並重試，重試失敗才算真失敗。
    """
    loc = None
    for _ in range(15):                       # 429 退避 / 401 重新認證
        r = s.post(f"{API}/simulations", json={"type": "REGULAR", "settings": settings,
                                               "regular": expr}, timeout=30)
        if r.status_code in (200, 201):
            loc = r.headers.get("Location"); break
        if r.status_code == 429:
            time.sleep(20); continue
        if r.status_code == 401:              # token 過期 → 換一張再試
            try:
                fresh = auth()
                s.cookies.update(fresh.cookies)
                time.sleep(2); continue
            except Exception as e:            # noqa: BLE001
                return None, f"401 且重新認證失敗: {e}"
        return None, f"POST {r.status_code}: {r.text[:150]}"
    if not loc or "walkthrough" in loc:
        return None, f"無有效 Location({loc})"
    # 輪詢節奏：實測一條模擬約 60 秒。固定 5 秒輪詢平均浪費 2.5 秒/條，
    # 兩個 worker 就是 ~8% 吞吐。改成**先密後疏**：
    # 前 20 秒不問（一定還在跑）、之後每 2 秒、超過 90 秒才退回 5 秒。
    # 併發只有 2（平台硬限），所以吞吐只能從「減少空轉」這裡榨。
    t0 = time.time(); sim = None
    time.sleep(18)
    while time.time() - t0 < timeout_s:
        p = s.get(loc, timeout=30)
        if p.status_code != 200:
            return None, f"poll {p.status_code}"
        sim = p.json()
        if sim.get("status") and sim["status"] != "RUNNING":
            break
        time.sleep(2 if time.time() - t0 < 90 else 5)
    if not sim or sim.get("status") != "COMPLETE":
        return None, f"status={sim.get('status') if sim else None} msg={str(sim.get('message'))[:150] if sim else ''}"
    aid = sim.get("alpha")
    if not aid:
        return None, f"無 alpha id（語法錯？）msg={str(sim.get('message'))[:150]}"
    a = s.get(f"{API}/alphas/{aid}", timeout=30)
    if a.status_code != 200:
        return None, f"取 alpha {a.status_code}"
    return {"id": aid, "detail": a.json()}, None


SCORE_LOG = ROOT / "score_history.jsonl"


def _iter_history():
    """逐行讀 score_history。壞行跳過(半截檔不能讓哨兵整個炸掉)。"""
    if not SCORE_LOG.exists():
        return
    with SCORE_LOG.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:  # noqa: BLE001
                continue


def _score_of(rec):
    c = (rec or {}).get("competitions") or [{}]
    c0 = c[0] or {}
    return c0.get("score"), c0.get("rank")


def _sentinel(rec, errs):
    """D3+D4 哨兵。就地在 rec 上蓋 notified / consultant_notified 標記。"""
    last_clean = None
    last_notified = None
    latched = False
    for r in _iter_history():
        if not r.get("notify_failed"):
            last_clean = r
        if r.get("notified"):
            last_notified = r
        if r.get("consultant_notified"):
            latched = True

    # ---- D4:顧問單向閂 ----
    if rec.get("consultant_http") == 200 and not latched:
        ok = notify(
            "🎉 BRAIN 顧問權限已開",
            "/users/self/consultant 回 200 —— onboarding 完成、顧問權限已開。\n"
            f"等級 {rec.get('level')}　已提交 {rec.get('submitted_total')}\n\n"
            "注意:這**不是**邀請訊號。2026-09-03 實證:Carson 已收到 Workday 顧問\n"
            "申請任務(邀請確實已發生)而此端點仍回 403。所以它量的是 onboarding\n"
            "完成後的權限,不是邀請有沒有發出。",
        )
        if ok:
            rec["consultant_notified"] = True   # 只有推成功才扣閂
        else:
            errs.append("consultant latch notify failed")

    # ---- D3:score / level / submitted_total 的 edge 偵測 ----
    # base 不能取「帶著新值但沒宣告成功」的記錄,否則變動會被靜默吃掉。
    # 優先取最後一筆宣告成功的;沒有的話取最後一筆**沒有失敗標記**的(靜默 seed)。
    base = last_notified if last_notified is not None else last_clean
    ps, pr = _score_of(base)
    cs, cr = _score_of(rec)
    changed = (cs != ps) \
        or (rec.get("level") != (base or {}).get("level")) \
        or (rec.get("submitted_total") != (base or {}).get("submitted_total"))
    if base is None or not changed:
        return

    def _n(v):
        return f"{v:,}" if isinstance(v, (int, float)) else str(v)

    delta = ""
    if isinstance(ps, (int, float)) and isinstance(cs, (int, float)):
        delta = f"（+{cs - ps:,.0f}）"
    ok = notify(
        "📊 BRAIN 分數更新",
        f"分數 {_n(ps)} → {_n(cs)} {delta}\n"
        f"排名 {_n(pr)} → {_n(cr)}\n"
        f"等級 {(base or {}).get('level')} → {rec.get('level')}\n"
        f"已提交 {rec.get('submitted_records')}\n"
        f"顧問端點 {rec.get('consultant_http')}\n\n"
        f"門檻：Bronze>1,000　Silver>5,000　Gold>10,000（Gold=顧問資格）\n"
        f"每日上限 2,000 分。",
    )
    if ok:
        rec["notified"] = True
    else:
        # 只由 score 分支設。顧問分支有 latched 當自己的狀態,共用會讓
        # 「顧問那則推失敗」連帶把 score 的 base 停住 ⇒ score 每輪重推,方向安全但很吵。
        rec["notify_failed"] = True
        errs.append("score notify failed")


def track_score(s, src="unknown", sentinel=True):
    """每次跑都記一筆積分快照 → `score_history.jsonl`。

    為什麼要自己記：平台不顯示「這條 alpha 給了幾分」，只給一個累計 score，
    而且是批次結算不是即時。社群說一條值 1,500~2,000 分，但那是**別人的數字**。
    自己每天落檔，才能從斜率反推「我這個帳號一條實際值幾分、還要幾天到 10,000」。
    （同 ypp_meter 的思路：最重要的進度數字要有自己的來源，不是轉述。）

    fail-closed：拿不到就記 null + 錯誤原因，不寫看起來正常的數字。
    """
    from datetime import datetime, timezone, timedelta
    rec = {"ts": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")}
    errs = []
    try:
        u = s.get(f"{API}/users/self", timeout=30)
        if u.ok:
            j = u.json()
            rec["level"] = j.get("level")
            rec["geniusLevel"] = j.get("geniusLevel")
        else:
            errs.append(f"users/self {u.status_code}")
    except Exception as e:  # noqa: BLE001
        errs.append(f"users/self {e}")
    try:
        c = s.get(f"{API}/users/self/competitions", timeout=30)
        if c.ok:
            for row in (c.json().get("results") or []):
                lb = row.get("leaderboard") or {}
                # `alphas`（已進榜的條數）2026-09-02 補記：判斷「分數是否在 10,000 封頂」
                # 唯一的區分變數就是它 —— alphas 11→13 而 score 不動 = 封頂；
                # alphas 沒變 = 結算根本還沒發生，兩者處置完全不同。
                # 沒有這一欄的話，score 不動會同時符合兩種解釋。
                rec.setdefault("competitions", []).append(
                    {"id": row.get("id"), "rank": lb.get("rank"), "score": lb.get("score"),
                     "alphas": lb.get("alphas"), "level": lb.get("level")})
        else:
            errs.append(f"competitions {c.status_code}")
    except Exception as e:  # noqa: BLE001
        errs.append(f"competitions {e}")
    try:
        a = s.get(f"{API}/users/self/activities/submissions", timeout=30)
        if a.ok:
            j = a.json()
            rec["submitted_total"] = (j.get("total") or {}).get("value")
            rec["submitted_records"] = (j.get("records") or {}).get("records")
        else:
            errs.append(f"submissions {a.status_code}")
    except Exception as e:  # noqa: BLE001
        errs.append(f"submissions {e}")
    # 顧問資格端點。403 = 尚未開通;200 = onboarding 完成、顧問權限已開。
    # 🔴 這**不是邀請訊號**——2026-09-03 實證推翻:Carson 當天已收到 Workday 顧問
    #    申請任務(邀請確實已發生),而這支端點仍然回 403。所以它量的是
    #    **onboarding 完成後的權限**,不是邀請有沒有發出。把它當邀請哨的話,
    #    那個警報永遠不會叫(memory verification-that-cannot-fail 的「不會叫」型)。
    # fail-closed:拿不到就寫 None + 錯誤原因,不要折成任何一個看起來正常的碼
    #    ——403 和「連不上」意義完全不同,前者是狀態後者是沒觀測到。
    try:
        cs_ = s.get(f"{API}/users/self/consultant", timeout=30)
        rec["consultant_http"] = cs_.status_code
    except Exception as e:  # noqa: BLE001
        rec["consultant_http"] = None
        errs.append(f"consultant {e}")
    rec["errors"] = errs
    rec["partial"] = bool(errs)
    rec["src"] = src
    # 🔴 D3+D4（2026-09-05）。獨立驗證員實測:舊做法 15 次真實變動裡盯哨只第一個
    #    看到 4 次(submitted_total 六次全滅),因為 `prev` 取的是**檔案最後一行**,
    #    而這個檔有三個寫入者(本函式被 brain_alpha_cron / miner_watchdog /
    #    daily_pick / score_watch 四路呼叫),誰先落盤誰就把變動吃掉,且吃掉的那兩支
    #    完全不會叫。漏報的形狀是「回報無變動」——一切看起來正常。
    #
    #    D3:偵測下放到這裡,所以**每個寫入者都是哨兵**,採樣從 3 次/天變成每次寫入。
    #    D4:顧問旗標改**單向閂**。它是一次性、單向、黏著的狀態,拿 edge-triggered
    #        (比對前後差異)去偵測 level 性質的事件,本來就是錯的工具——正確性
    #        依賴「沒漏掉任何觀測」且「沒弄丟前一個值」,而這兩件在本線上各自都壞過。
    #        閂只能 0→1:檔案被刪/損毀/回捲、notify 失敗、別人先觀測到 —— 這幾種
    #        失效方向都被翻成「重複推播」而不是「漏掉」。上限 2 則。
    #    ⚠️ 但**不是每一種**。第二輪驗證員找到兩條仍會漏的路徑,已知未修:
    #      (a) notify() 的 Telegram 失敗會退 ntfy 並回 True ⇒ 閂照樣扣上,
    #          而 Carson 未必訂閱 ntfy(ntfy_topic 在 design_system.json 確實有設)。
    #          要修得讓 notify() 回傳管道名,閂只在 telegram 成功時才扣。
    #      (b) 「每個寫入者都是哨兵」被 claim_lock() 擋掉一半:搶不到鎖的 alpha_cron
    #          在 track_score 之前就 return。實測每日寫入 4~9 筆、最大間隔 9.3 小時,
    #          不是 */20。所以採樣是 3/天 → 4~9/天。
    #    不要把上面那段讀成「保證不會漏」——它不是。
    #
    #    預設值的準則:**該欄位漏掉之後還會不會再有機會**。
    #      顧問旗標一次性 → 找不到閂就當 0 → 倒向推播(端點仍 403 時完全靜默,
    #        因為條件是 cc == 200 而不是 cc != pc)。
    #      score/level/submitted 週期性,天天結算 → 找不到 notified 就取最後一行
    #        (靜默 seed),倒向安靜。發假警報等於訓練人忽略這個管道。
    #    這兩條是**每次都走的常駐 fallback,不是一次性 migration** —— 一次性的
    #    fallback 在正常運作下永遠不會被執行 = 永遠沒被測過,而它偏偏只在出事那天上場。
    #
    #    整段包在 try/except 裡:本函式在每批挖礦開頭被呼叫,推播失敗絕不能讓
    #    挖礦線掛掉,也絕不能阻止這筆記錄落盤。
    # 🔴 sentinel=False 是給 --dry 這類「不真的推播」的呼叫端用的。
    #    61c69a13 的地雷:brain_daily_pick --dry 把 B.notify 換成回傳 True 的 stub,
    #    而 _sentinel 裡的 notify() 是裸的全域查找 ⇒ monkeypatch 生效 ⇒
    #    ok 為 True ⇒ 閂被假扣上並寫進**正式的** score_history.jsonl,
    #    而一則推播都沒發生。閂是單向的,寫進去就再也不會重開 ⇒
    #    顧問端點翻 200 那天只要有人跑過一次 --dry,那則通知永久消失。
    #    ⇒ 不推播的呼叫端一律傳 sentinel=False,不要靠換掉 notify 來「不推播」。
    if sentinel:
        try:
            _sentinel(rec, errs)
        except Exception as e:  # noqa: BLE001
            errs.append(f"sentinel {e}")
            # 🔴 例外時這筆記錄**不可以**成為下一輪的 base:它帶著新值卻沒宣告過。
            #    少了這一行,一次例外 = 一次真實變動永久消失(驗證員沙箱 C5 實測)。
            rec["notify_failed"] = True
    with SCORE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def fetch_yearly(s, aid, tries=20):
    """取逐年統計。回傳 [{year, sharpe, fitness, turnover, returns}] 或 None。

    端點是**非同步**的：回 200 但 body 可能是空的，要照 Retry-After 輪詢
    （與 /check 同一個模式）。
    """
    for _ in range(tries):
        r = s.get(f"{API}/alphas/{aid}/recordsets/yearly-stats", timeout=40)
        if not r.ok:
            return None
        if r.text.strip():
            try:
                d = r.json()
            except Exception:  # noqa: BLE001
                return None
            cols = [p["name"] for p in (d.get("schema") or {}).get("properties", [])]
            out = []
            for row in d.get("records", []):
                m = dict(zip(cols, row))
                out.append({k: m.get(k) for k in
                            ("year", "sharpe", "fitness", "turnover", "returns", "stage")})
            return out
        time.sleep(float(r.headers.get("Retry-After") or 4))
    return None


def year_quality(rows):
    """把逐年表壓成「近年撐不撐得住」的判準。

    動機（2026-08-27）：第一條提交的 alpha 總 Sharpe 2.25 很漂亮，但逐年是
        2019:1.45  2020:3.29  2021:3.38  2022:2.06  2023:**0.87**
    ——總分幾乎全靠 2020~2021 撐，最近一年已經跌破門檻。
    顧問報酬看的是 alpha 在**未來真實市場**的表現，不是歷史回測平均，
    所以「近年還撐得住」比「總分高」更值得押。
    """
    if not rows:
        return None
    ys = sorted((r for r in rows if r.get("sharpe") is not None),
                key=lambda r: str(r.get("year")))
    if not ys:
        return None
    sh = [r["sharpe"] for r in ys]
    recent = sh[-2:] if len(sh) >= 2 else sh
    return {
        "years": len(sh),
        "worst_year_sharpe": min(sh),
        "recent2_min_sharpe": min(recent),      # 近兩年最差的一年
        "last_year_sharpe": sh[-1],
        "neg_years": sum(1 for x in sh if x < 0),
        # 穩定：每年都站在門檻之上,不是靠某兩年拉抬
        "all_years_pass": all(x >= 1.25 for x in sh),
        "recent_ok": min(recent) >= 1.25,
    }


def flatten(detail):
    """攤平 checks。

    🔴 2026-08-27 修正（Carson 質疑「你怎麼知道你沒過」時揪出來的）：
    原本 `all_pass = not failed`，但 **SELF_CORRELATION 的狀態是 PENDING 不是 FAIL**
    —— 只要其他項都過就會被判定「全過」並發通知，即使那項根本還沒算。
    那會讓 Carson 收到過度樂觀的「可以提交了」，點進去卻發現不能提交。

    所以拆成兩個旗標：
      · evaluable_pass — 所有**已評估**的項目都過（值得通知，但要標明未知項）
      · all_pass       — 連 SELF_CORRELATION 都明確 PASS（真正的乾淨全過）
    通知走 evaluable_pass，但訊息裡一定要寫出 pending 項目，不准粉飾。
    """
    is_ = detail.get("is") or {}
    ck = {c.get("name"): c for c in (is_.get("checks") or [])}
    failed = [n for n, c in ck.items() if c.get("result") == "FAIL"]
    pending = [n for n, c in ck.items() if c.get("result") == "PENDING"]
    return {"sharpe": is_.get("sharpe"), "fitness": is_.get("fitness"),
            "turnover": is_.get("turnover"), "returns": is_.get("returns"),
            "drawdown": is_.get("drawdown"),
            "sub_sharpe": (ck.get("LOW_SUB_UNIVERSE_SHARPE") or {}).get("value"),
            "self_corr": (ck.get("SELF_CORRELATION") or {}).get("result"),
            "failed": failed, "pending": pending,
            "evaluable_pass": not failed,
            "all_pass": (not failed) and (not pending)}


# ────────────────────── 跨程序單一實例鎖 ──────────────────────
# 平台併發上限 2 是**帳號層級**的：開兩個挖礦程序不會變快,只會互相 429。
# 而現行排程有三個入口都會啟動挖礦:
#   · `0 */2 * * *` brain_alpha_cron —— **無條件**啟動,不看有沒有人在跑
#   · `*/20` brain_miner_watchdog —— 會先查,但查的是程序名不是鎖
#   · 我在 session 裡手動起的長批:`--run 4000` 一跑好幾天,
#     兩小時一次的 cron 必然疊上來。帳本裡已經有 16 次 429。
#
# 判準照 memory `yt-make-video-duplicate-deadlock` 的教訓:
# **「超時=死亡」不能只看時間戳,要配活性證明**。這裡用 PID 存活 + 指令列比對,
# 而不是「鎖檔超過 N 分鐘就算過期」——長批本來就會跑很久,純看時間會把活的判死。
LOCKFILE = ROOT / "miner.lock"

# 🔴 2026-09-01：挖礦程序的指令列特徵。**這份是唯一真相**，
# brain_miner_watchdog.py 直接 import 這個常數（原本兩邊各抄一份，
# 而 `brain_alpha_cron` 兩邊都漏了 —— 見下方事故記錄）。
# 新增挖礦階段時只改這裡。
MINER_PATTERNS = ("field_miner", "second_order", "brain_auto",
                  "universe_sweep", "hybrid_miner", "brain_alpha_cron")


def _pid_alive_miner(pid: int) -> bool:
    """那個 PID 還活著、而且真的是挖礦程序嗎？

    只看 PID 存活不夠：PID 會被作業系統回收給無關的程式。
    所以連指令列一起比對 —— 這就是「活性證明」。
    """
    try:
        out = subprocess.run(
            ["wmic", "process", "where", f"ProcessId={int(pid)}", "get", "commandline"],
            capture_output=True, text=True, timeout=30).stdout
    except Exception:  # noqa: BLE001
        return True          # 查不出來就當它活著,寧可少跑一批也不要兩個互撞
    return any(k in out for k in MINER_PATTERNS)


def claim_lock() -> bool:
    """搶到鎖回 True；已經有人在挖回 False。"""
    try:
        if LOCKFILE.exists():
            old = LOCKFILE.read_text(encoding="utf-8").strip().split(",")[0]
            # 同一個 PID 再要一次要給它 —— brain_alpha_cron 先搶鎖，
            # 再用 runpy 在**同一個程序**裡跑 field_miner/brain_auto，
            # 那支又會呼叫一次 claim_lock。不做這個判斷會自己鎖死自己
            # （而且是安靜地什麼都不跑，只印一行「正在挖礦」）。
            if old == str(os.getpid()):
                return True
            if old.isdigit() and _pid_alive_miner(int(old)):
                print(f"[lock] PID {old} 正在挖礦（併發上限 2 是帳號層級，"
                      f"再開一個只會互相 429）→ 這一輪不跑。")
                return False
            print(f"[lock] 舊鎖 PID {old} 已不是挖礦程序 → 接手")
        LOCKFILE.write_text(f"{os.getpid()},{time.time():.0f}", encoding="utf-8")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[lock] 鎖操作失敗（照跑）：{e}", file=sys.stderr)
        return True


def release_lock() -> None:
    try:
        if LOCKFILE.exists() and LOCKFILE.read_text(encoding="utf-8").startswith(str(os.getpid())):
            LOCKFILE.unlink()
    except Exception:  # noqa: BLE001
        pass


# ────────────────────── 主流程 ──────────────────────

def cmd_run(n, workers=2):
    """跑 n 條候選。

    🔴 2026-08-27：原本是序列 for 迴圈 —— 一次只跑一條，而平台**實測允許 2 條併發**
    （第 3 條直接回 429，已逐條實測確認；社群傳的「≤5」不適用免費帳號）。
    等於我一直在用一半的速度跑。改成 2 個 worker，吞吐直接翻倍。

    每條跑完立刻落檔（append 有鎖），中途掛掉不會整批丟失。
    """
    import threading

    # 跨程序單一實例：三個入口都會啟動挖礦（2 小時 cron 無條件跑、20 分守門、
    # 我手動起的長批），而併發上限 2 是**帳號層級**——疊起來只會互相 429。
    if not claim_lock():
        return

    led = load_ledger(); st = load_state()
    todo = [(l, e, s) for l, e, s in candidates() if _key(e, s) not in led][:n]
    if not todo:
        print("候選都跑完了。"); release_lock(); return
    print(f"待跑 {len(todo)} 條（{workers} 個 worker 併發，平台硬上限 2）")
    s = auth()
    sc = track_score(s, src="alpha_cron")  # 每批開頭記一筆積分快照,用斜率反推一條值幾分
    print(f"積分快照：level={sc.get('level')} 已提交={sc.get('submitted_total')} "
          f"comp={sc.get('competitions')}")
    winners = []
    lock = threading.Lock()
    idx = {"i": 0}
    # 🔴 2026-09-01：熔斷 + 告警。平台會整段時間收不下任何模擬
    #   （實測兩次：ET 08-30 13:00~20:00、ET 08-31 17:08~ 都是 6~7 小時全滅，
    #    然後自己好起來）。而在此之前這件事**完全沒有訊號**：
    #    每條各自退避 300 秒然後印一行 ✗，看起來像「這個欄位不行」，
    #    實際上是整條線停擺 6 小時。同一個病：監控只看已發生的事。
    #   ALERT_AT 條連續沒送出去 → 推播一次；ABORT_AT 條 → 這批直接收工，
    #   不要再燒好幾小時的牆鐘（cron 兩小時後會自己再來一次）。
    ALERT_AT, ABORT_AT = 8, 30
    infra = {"streak": 0, "alerted": False, "abort": False}

    def work():
        while True:
            with lock:
                if idx["i"] >= len(todo) or infra["abort"]:
                    return
                i = idx["i"]; idx["i"] += 1
            label, expr, settings = todo[i]
            res, err = simulate(s, expr, settings)
            rec = {"key": _key(expr, settings), "label": label, "expr": expr,
                   "settings_decay": settings.get("decay"), "nz": settings.get("neutralization")}
            if err:
                rec.update(ok=False, error=err)
                line = f"[{i+1}/{len(todo)}] {label}  ✗ {err[:90]}"
                if _is_infra(rec):
                    with lock:
                        infra["streak"] += 1
                        if infra["streak"] == ALERT_AT and not infra["alerted"]:
                            infra["alerted"] = True
                            notify("🔴 BRAIN 模擬送不出去",
                                   f"連續 {ALERT_AT} 條模擬**根本沒送出平台**"
                                   f"（{err[:60]}）。\n\n"
                                   f"這不是欄位沒訊號，是整條搜尋線停擺。\n"
                                   f"實測過兩次這種全滅，各持續 6~7 小時後自己好。\n"
                                   f"再連續 {ABORT_AT} 條就收工，兩小時後 cron 自己重試。")
                        if infra["streak"] >= ABORT_AT:
                            infra["abort"] = True
                            print(f"[熔斷] 連續 {infra['streak']} 條沒送出去，這批收工。",
                                  flush=True)
            else:
                with lock:
                    if infra["alerted"]:
                        notify("✅ BRAIN 模擬恢復了",
                               f"連續失敗 {infra['streak']} 條之後又能送出模擬了。")
                        infra["alerted"] = False
                    infra["streak"] = 0
                ev = flatten(res["detail"])
                rec.update(ok=True, alpha_id=res["id"], result=ev)
                tag = ("★全過" if ev["all_pass"] else
                       ("☆已評估項全過(pending:" + ",".join(ev["pending"]) + ")"
                        if ev["evaluable_pass"] else ",".join(ev["failed"])))
                # 只對「有希望的」多打一次 API 取逐年 —— 每條都取太貴
                yq = None
                if (ev.get("sharpe") or 0) >= 1.25 and (ev.get("fitness") or 0) >= 1.0:
                    yq = year_quality(fetch_yearly(s, res["id"]))
                    rec["year_quality"] = yq
                line = (f"[{i+1}/{len(todo)}] {label}  sh={ev['sharpe']} fit={ev['fitness']} "
                        f"to={ev['turnover']}  {tag}")
                if yq:
                    line += (f"  近2年最差={yq['recent2_min_sharpe']} "
                             f"最差年={yq['worst_year_sharpe']}"
                             + ("  ✅逐年皆達標" if yq["all_years_pass"] else ""))
                if ev["evaluable_pass"]:
                    with lock:
                        if res["id"] not in st["notified"]:
                            winners.append((label, res["id"], ev))
                            st["notified"].append(res["id"]); save_state(st)
            with lock:
                append(rec); print(line, flush=True)

    ths = [threading.Thread(target=work, daemon=True) for _ in range(max(1, workers))]
    for t in ths: t.start()
    for t in ths: t.join()

    if winners:
        lines = []
        for l, aid, e in winners:
            pend = ("尚未評估：" + ",".join(e["pending"])) if e["pending"] else "全部項目皆已通過"
            lines.append(f"{l}\n  alpha={aid}\n  sharpe={e['sharpe']}  fitness={e['fitness']}  "
                         f"turnover={e['turnover']}\n  ⚠️ {pend}")
        any_pending = any(e["pending"] for _, _, e in winners)
        head = ("所有已評估的檢查都通過了。\n"
                "⚠️ 但 SELF_CORRELATION 要到你按 Check Submission 才會算 —— "
                "有可能在那一步被擋下來。\n\n" if any_pending
                else "全部檢查通過（含 SELF_CORRELATION）。\n\n")
        body = (head + "\n\n".join(lines) +
                "\n\n到 platform.worldquantbrain.com → Alphas → Unsubmitted → "
                "先按 Check Submission，全綠才按 Submit Alpha")
        ok = notify(f"🎯 BRAIN：{len(winners)} 條待你確認", body)
        print(f"\n★★ {len(winners)} 條已評估項全過，已推播（送出={ok}）★★")
    else:
        print("\n本輪無候選通過全部已評估項目。")
    release_lock()


def _base_key(expr: str) -> str:
    """從表達式抽出「資料欄位」當相關性分群的 key。

    2026-08-28 事故：同一個欄位換外層變換（ts_rank ↔ ts_quantile）產生的兩條
    alpha，self-correlation **0.9653**（門檻 0.7）→ 第二條交不出去。
    所以決定「能不能同時提交」的不是分數，是**底層資料欄位是否相同**。
    """
    import re
    m = re.findall(r"ts_backfill\(([^,]+),", expr)
    if m:
        return m[0].strip()
    m = re.findall(r"group_backfill\(([^,]+),", expr)
    if m:
        return m[0].strip()
    return re.sub(r"[^a-z_/0-9]", "", expr)[:40]


def write_successful():
    """把達標的 alpha 寫成人看的清單 `successful_alphas.md`。

    分三級，因為「達標」有三種意義，混在一起會誤導：
      🟢 可提交   —— 全部 checks 皆 PASS（SELF_CORRELATION 也過）
      🟡 待確認   —— 已評估項全過，但 SELF_CORRELATION 仍 PENDING
                    （要按 Check Submission 才算得出來，有可能在那步被擋）
      🔵 雙門檻過 —— Sharpe>=1.25 且 fitness>=1.0，但其他 check 未過
                    （這是離終點最近的一群，值得繼續改）
    """
    led = load_ledger()
    ok = [r for r in led.values() if r.get("ok") and r.get("result")]
    def g(r, k):
        return r["result"].get(k) or 0
    green = [r for r in ok if r["result"].get("all_pass")]
    yellow = [r for r in ok if r["result"].get("evaluable_pass") and not r["result"].get("all_pass")]
    blue = [r for r in ok if g(r, "sharpe") >= 1.25 and g(r, "fitness") >= 1.0
            and not r["result"].get("evaluable_pass")]
    for grp in (green, yellow, blue):
        grp.sort(key=lambda r: -g(r, "fitness"))

    # 依 base 去重：同一個資料欄位只留最好的一條。
    # 理由（2026-08-28 實測事故）：同 base 不同外層變換 → self-correlation 0.9653，
    # 第二條**交不出去**。所以清單要按「獨立 base」列，不是按分數列前 N 名。
    from collections import defaultdict
    def dedup(grp):
        by = defaultdict(list)
        for r in grp:
            by[_base_key(r["expr"])].append(r)
        out = []
        for k, v in by.items():
            v.sort(key=lambda r: -(r["result"].get("fitness") or 0))
            best = v[0]; best["_variants"] = len(v); best["_base"] = k
            out.append(best)
        yq = lambda r: (r.get("year_quality") or {}).get("last_year_sharpe")  # noqa: E731
        out.sort(key=lambda r: -(yq(r) if yq(r) is not None else -9))
        return out
    green, yellow, blue = dedup(green), dedup(yellow), dedup(blue)

    L = ["# 達標 Alpha 清單（**依獨立 base 去重**）", "",
         f"> 自動產生。帳本 {len(led)} 條，成功模擬 {len(ok)} 條。",
         "> 門檻：`Sharpe>=1.25`、`fitness>=1.0`、`turnover 0.01~0.7`、"
         "`sub-universe sharpe`（相對值）、`concentrated weight`、`self-correlation<0.7`。",
         "",
         "> 🔴 **同一個資料欄位只列一條。** 2026-08-28 實測：同 base 換外層變換的兩條，"
         "self-correlation **0.9653**，第二條被擋。決定能不能同時提交的是**底層欄位**，不是分數。",
         "> 排序依「最後一年 Sharpe」——官方分數會每週依樣本外表現更新，近年撐得住才會持續加分。", ""]
    for tag, name, grp, note in (
        ("🟢", "可提交（全部 checks 通過）", green, "到平台 Alphas → Unsubmitted → Submit Alpha"),
        ("🟡", "待確認（SELF_CORRELATION 尚未評估）", yellow, "先按 Check Submission，全綠才提交"),
        ("🔵", "雙門檻已過、卡其他檢查", blue, "離終點最近，優先改這幾條"),
    ):
        L += [f"## {tag} {name} — {len(grp)} 條", "", f"_{note}_", ""]
        if not grp:
            L += ["（無）", ""]
            continue
        for r in grp:
            v = r["result"]
            y = r.get("year_quality") or {}
            L += [f"### `{r.get('_base', '?')}`　— {r['label']}", "",
                  "```", r["expr"], "```", "",
                  f"- Sharpe **{v.get('sharpe')}** / Fitness **{v.get('fitness')}** / "
                  f"Turnover {(v.get('turnover') or 0):.1%}",
                  f"- **最後一年 Sharpe：{y.get('last_year_sharpe', '?')}**"
                  f"（最差年 {y.get('worst_year_sharpe', '?')}）",
                  f"- alpha id：`{r.get('alpha_id')}`",
                  f"- 同 base 的變體共 {r.get('_variants', 1)} 條（**只能交這一條**，其餘會撞 self-correlation）",
                  f"- 未過：{', '.join(v.get('failed') or []) or '無'}"
                  + (f"　未評估：{', '.join(v.get('pending') or [])}" if v.get("pending") else ""),
                  ""]
    (ROOT / "successful_alphas.md").write_text("\n".join(L), encoding="utf-8")
    return len(green), len(yellow), len(blue)


def cmd_report():
    led = load_ledger()
    ok = [r for r in led.values() if r.get("ok")]
    bad = [r for r in led.values() if not r.get("ok")]
    ok.sort(key=lambda r: (r["result"].get("fitness") or -99), reverse=True)
    print(f"帳本 {len(led)} 條：成功 {len(ok)}、失敗 {len(bad)}")
    print(f"\n{'label':<30}{'sharpe':>8}{'fitness':>9}{'turnover':>10}  未過")
    print("-" * 88)
    for r in ok[:25]:
        v = r["result"]
        print(f"{'★' if v.get('all_pass') else ' '}{r['label']:<29}"
              f"{(v.get('sharpe') or 0):>8.2f}{(v.get('fitness') or 0):>9.2f}"
              f"{(v.get('turnover') or 0):>10.1%}  {','.join(v.get('failed') or []) or '全過'}")
    w = [r for r in ok if r["result"].get("all_pass")]
    print(f"\n全數通過：{len(w)} 條")
    for r in w:
        print(f"  ★ {r['label']}  alpha={r.get('alpha_id')}\n    {r['expr']}")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    a = sys.argv[1:]
    if "--report" in a:
        cmd_report()
    elif "--run" in a:
        i = a.index("--run")
        cmd_run(int(a[i + 1]) if len(a) > i + 1 else 20)
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
