#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""train_depts.py — 【📚 部門進修】每週日 04:30 自動執行。

讓 AI 員工「週末充電」：
  1) 彙整本週產量/觀看/錯誤/指令 → 產出週績效摘要
  2) 用 Claude 分析本週執行品質 → 更新各部門作業要點（boss_directives 的【部門進修】條目）
  3) 清理過期/衝突指令（保留最新 N 條）
  4) 為 decision_dept 預備「本週學到什麼」備忘

誠實前提：
  - 訓練只是「更新指令字串」，AI 部門下次執行即套用新指令（不存在模型微調）。
  - 無 Anthropic key → 只跑規則式清理，仍有效（去除 30 天前舊指令）。

輸出：
  STUDIO/boss_directives.json          → 加入【部門進修】更新條目
  STUDIO/REPORTS/{date}_部門進修.md    → 週績效 + 更新清單
"""
from __future__ import annotations

import json
import os
import re
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
OUT = ROOT / "output"
LOGS = ROOT / "logs"
LEDGER = STUDIO / "uploaded_ledger.json"
ORDERS = STUDIO / "production_orders.json"
DIRECTIVES = STUDIO / "boss_directives.json"
HISTORY = STUDIO / "metrics_history.json"
TW = timezone(timedelta(hours=8))

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-haiku-4-5-20251001"
TRAIN_TAG = "【部門進修】"
MAX_TRAIN_ITEMS = 5   # 保留最新 N 條進修指令，避免無限膨脹
DIRECTIVE_MAX_AGE_DAYS = 30   # 超過 N 天的非固定指令自動清理


def tw_today():
    return datetime.now(TW).strftime("%Y-%m-%d")


def tw_now():
    return datetime.now(TW)


def _load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else default
    except Exception:
        return default


try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(d, m): pass


# ── 週績效彙整 ──
def collect_week_stats() -> dict:
    """彙整本週（近 7 天）的生產/上架/錯誤統計。"""
    now = tw_now()
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    stats = {
        "period": f"{week_start} ～ {tw_today()}",
        "produced": 0, "published": 0,
        "errors": 0, "fatal": 0,
        "active_days": 0,
    }

    # 從 mp4 數量算已產
    if OUT.exists():
        for p in OUT.glob("*.mp4"):
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime, TW)
                if mtime >= (now - timedelta(days=7)):
                    stats["produced"] += 1
            except Exception:
                pass

    # 從 ledger 算已上架（近 7 天有 publish_time 的）
    ledger = _load(LEDGER, {})
    stats["published"] = len(ledger)  # 累計，非週數（週數據需 Analytics，用累計代替）

    # 從 cron.log 算錯誤/活躍天數
    cron_log = LOGS / "cron.log"
    if cron_log.exists():
        try:
            lines = cron_log.read_text(encoding="utf-8", errors="replace").splitlines()
            active_dates = set()
            for ln in lines[-500:]:  # 只看最近 500 行
                if any(k in ln for k in ("Traceback", "FATAL", "Error", "⚠️")):
                    stats["errors"] += 1
                if "FATAL" in ln:
                    stats["fatal"] += 1
                # 從行首提取日期（格式 [MM-DD ...）
                m = re.search(r"\[(\d{2}-\d{2})", ln)
                if m:
                    active_dates.add(m.group(1))
            stats["active_days"] = len(active_dates)
        except Exception:
            pass

    return stats


# ── 規則式指令清理 ──
def clean_directives(d: dict) -> tuple[dict, list[str]]:
    """清理過期/重複的進修指令，回傳 (更新後 dict, 清理記錄)。"""
    items = d.get("directives", [])
    if not isinstance(items, list):
        return d, []

    cleaned = []
    now = tw_now()
    cutoff = now - timedelta(days=DIRECTIVE_MAX_AGE_DAYS)
    log = []

    # 保留：固定指令（不含日期標記） + 近 N 天的進修條目
    train_kept = []
    other = []
    for it in items:
        text = it if isinstance(it, str) else str(it)
        if TRAIN_TAG in text:
            # 進修條目找時間戳
            m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
            if m:
                try:
                    ts = datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=TW)
                    if ts >= cutoff:
                        train_kept.append(text)
                    else:
                        log.append(f"清理過期進修指令（{m.group(1)}）")
                except Exception:
                    train_kept.append(text)
            else:
                train_kept.append(text)
        else:
            other.append(text)

    # 只保留最新 MAX_TRAIN_ITEMS 條進修
    if len(train_kept) > MAX_TRAIN_ITEMS:
        removed = len(train_kept) - MAX_TRAIN_ITEMS
        train_kept = train_kept[-MAX_TRAIN_ITEMS:]
        log.append(f"裁剪舊進修指令 {removed} 條（超過上限 {MAX_TRAIN_ITEMS}）")

    d["directives"] = other + train_kept
    return d, log


# ── AI 分析 + 新進修指令 ──
def ai_train(stats: dict) -> str:
    """用 Claude 根據本週數據產出進修建議。"""
    if not API_KEY:
        return ""

    # 讀最近決策報告摘要
    recent_reports = []
    if REPORTS.exists():
        for p in sorted(REPORTS.glob("*_決策.md"), reverse=True)[:3]:
            try:
                txt = p.read_text(encoding="utf-8")
                m = re.search(r"\*\*戰略判斷\*\*：(.+)", txt)
                if m:
                    recent_reports.append(f"{p.stem[:10]}：{m.group(1).strip()}")
            except Exception:
                pass

    reports_txt = "\n".join(f"  - {r}" for r in recent_reports) or "  （無近期決策報告）"
    orders = _load(ORDERS, {})
    preferred = orders.get("preferred_keywords", [])[:5]

    prompt = f"""你是量化阿森頻道（網格/定投/Pionex/量化）的AI部門進修教練。

本週（{stats['period']}）執行數據：
  - 產片數：{stats['produced']}
  - 累計已上架：{stats['published']}
  - cron 活躍天數：{stats['active_days']}/7
  - 日誌錯誤次數：{stats['errors']}（其中 FATAL：{stats['fatal']}）

近期 decision_dept 戰略方向：
{reports_txt}

當前優先關鍵詞：{', '.join(preferred) if preferred else '無'}

請用**繁體中文**輸出：
1) 本週執行評分（優/良/待改進）和一句話說明
2) 下週各部門應特別注意的 2-3 條具體改善要點（可操作的，不是口號）
3) 是否需要調整任何排程或腳本參數？

格式：條列式，每條不超過 60 字，直接可加入指令系統。"""

    try:
        import requests
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": MODEL, "max_tokens": 500,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"].strip()
    except Exception as e:
        log_ops("部門進修", f"Claude 分析失敗：{e}")
        return ""


def update_directives(new_item: str, clean_log: list[str]) -> None:
    """把新的進修指令和清理記錄寫入 boss_directives.json。"""
    d = _load(DIRECTIVES, {"directives": [], "format_override": "auto",
                           "privacy": "public", "paused": False})
    d, _ = clean_directives(d)  # 先清理
    if new_item:
        entry = f"{TRAIN_TAG}{tw_today()}：{new_item[:300]}"
        d["directives"].append(entry)
    DIRECTIVES.parent.mkdir(parents=True, exist_ok=True)
    DIRECTIVES.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    if new_item:
        log_ops("部門進修", "更新 boss_directives 進修條目")


def write_report(stats: dict, ai_txt: str, clean_log: list[str]) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    today = tw_today()

    ai_section = f"\n## 🤖 AI 進修分析\n{ai_txt}" if ai_txt else \
        "\n## 🤖 AI 進修分析\n（無 ANTHROPIC_API_KEY，略過 AI 分析，已完成規則式清理）"

    clean_section = ""
    if clean_log:
        clean_section = "\n## 🧹 指令清理記錄\n" + "\n".join(f"- {l}" for l in clean_log)

    md = (
        f"# 部門進修週報 {today}\n"
        f"_{datetime.now(TW).strftime('%H:%M')} 週日自動產出_\n\n"
        f"## 📊 本週執行績效\n"
        f"- 週期：{stats['period']}\n"
        f"- 產片數：{stats['produced']} 支\n"
        f"- 累計已上架：{stats['published']} 支\n"
        f"- Cron 活躍天數：{stats['active_days']}/7 天\n"
        f"- 日誌錯誤：{stats['errors']} 次（FATAL：{stats['fatal']}）\n"
        + ai_section
        + clean_section
    )
    path = REPORTS / f"{today}_部門進修.md"
    path.write_text(md, encoding="utf-8")
    log_ops("部門進修", f"週報寫入 {path.name}")


def main() -> int:
    log_ops("部門進修", "週日進修開始")
    try:
        stats = collect_week_stats()
        log_ops("部門進修", f"本週數據：產 {stats['produced']} 支，活躍 {stats['active_days']} 天")

        ai_txt = ai_train(stats)

        # 清理舊指令
        d = _load(DIRECTIVES, {"directives": [], "format_override": "auto",
                               "privacy": "public", "paused": False})
        _, clean_log = clean_directives(d)

        update_directives(ai_txt, clean_log)
        write_report(stats, ai_txt, clean_log)
        log_ops("部門進修", "完成")
    except Exception as e:
        log_ops("部門進修", f"FATAL: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
