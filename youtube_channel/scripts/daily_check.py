#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daily_check.py — 【每日大檢查】整套系統自動體檢，揪出問題寫成報告。

每天排程跑一次（不花 API、純讀檔/編譯/查主機）。檢查：
  1) 腳本完整性：py_compile 全部 scripts/*.py（抓語法錯，防壞代碼上線）
  2) 今日排程：cron.log 有沒有今天的 製作/上架 紀錄
  3) 發布：ledger 數、可發布候選、今日上架幾支
  4) 倉庫評分：未發布/pass/退件、門檻、有沒有卡住的低分片
  5) 主機健康：磁碟/記憶體/負載
  6) 錯誤掃描：今日 cron.log 的 Traceback/FATAL/⚠️ 次數
  7) 金鑰/服務：ANTHROPIC_API_KEY、YouTube/Analytics token 在不在
輸出 STUDIO/REPORTS/{date}_大檢查.md（決策中心「每日匯報」分頁可看）＋ ops 摘要。
用法：python scripts/daily_check.py
"""
from __future__ import annotations
import glob, json, os, py_compile, re, shutil, subprocess, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
STUDIO = ROOT / "STUDIO"
OUT = ROOT / "output"
REPORTS = STUDIO / "REPORTS"
LOG = ROOT / "logs" / "cron.log"
LEDGER = STUDIO / "uploaded_ledger.json"
QSCORES = STUDIO / "quality_scores.json"
TW = timezone(timedelta(hours=8))

try:
    sys.path.insert(0, str(SCRIPTS))
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(s, m): pass


def today():
    return datetime.now(TW).strftime("%Y-%m-%d")


def md():
    return datetime.now(TW).strftime("%m-%d")


def _load(p, d):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d
    except Exception:
        return d


def _logtext():
    try:
        return LOG.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def check_scripts():
    bad = []
    for f in sorted(SCRIPTS.glob("*.py")):
        try:
            py_compile.compile(str(f), doraise=True)
        except Exception as e:  # noqa: BLE001
            bad.append(f"{f.name}: {str(e)[:60]}")
    if bad:
        return ("❌", f"{len(bad)} 支腳本語法錯", bad)
    n = len(list(SCRIPTS.glob("*.py")))
    return ("✅", f"全部 {n} 支腳本語法 OK", [])


def check_cron():
    txt = _logtext()
    tag = md()
    today_lines = [l for l in txt.splitlines() if f"[{tag}" in l or f" {tag} " in l]
    produced = any(("補產" in l or "produce" in l.lower()) for l in today_lines)
    published = any(("上架" in l or "發布" in l) for l in today_lines)
    detail = f"今日 cron 紀錄 {len(today_lines)} 行；製作{'✓' if produced else '✗'}、上架/發布{'✓' if published else '✗'}"
    ok = "✅" if (produced or published) else "⚠️"
    return (ok, detail, [] if today_lines else ["今日 cron.log 無任何紀錄（cron 沒跑？）"])


def check_publish():
    led = _load(LEDGER, {})
    mp4 = [Path(p).stem for p in glob.glob(str(OUT / "*.mp4"))]
    cand = [s for s in mp4 if s not in led]
    txt = _logtext()
    pub_today = len([l for l in txt.splitlines() if f"[{md()}" in l and ("上架" in l or "即時發布" in l)])
    issues = []
    if not cand and not led:
        issues.append("無候選也無已發布（產線可能沒在跑）")
    return ("✅" if cand or led else "⚠️",
            f"已發布 {len(led)}、可發布候選 {len(cand)}、今日上架相關紀錄 {pub_today} 筆", issues)


def check_library():
    q = _load(QSCORES, {})
    if not q:
        return ("⚠️", "尚無 quality_scores.json（評分還沒跑）", [])
    s = q.get("summary", {})
    mn = q.get("min_score", "?")
    rej = s.get("reject", 0)
    issues = []
    if rej and rej >= 5:
        issues.append(f"{rej} 支未發布卡在低於門檻 {mn}，建議 tidy 或調門檻")
    return ("✅" if rej < 5 else "⚠️",
            f"未發布 {s.get('pending',0)}（pass {s.get('pass',0)}／退件 {rej}）、已發布 {s.get('published',0)}、門檻 {mn}", issues)


def check_host():
    issues = []
    try:
        du = shutil.disk_usage("/")
        free_gb = du.free / 1e9
        used_pct = du.used / du.total * 100
        disk = f"磁碟用 {used_pct:.0f}%（剩 {free_gb:.0f}GB）"
        if used_pct > 90:
            issues.append(f"磁碟快滿（{used_pct:.0f}%）")
    except Exception:
        disk = "磁碟 ?"
    try:
        load1 = os.getloadavg()[0]
        ncpu = os.cpu_count() or 1
        loadinfo = f"負載 {load1:.2f}/{ncpu}核"
        if load1 > ncpu * 2:
            issues.append(f"負載偏高 {load1:.2f}")
    except Exception:
        loadinfo = "負載 ?"
    return ("✅" if not issues else "⚠️", f"{disk}、{loadinfo}", issues)


def check_errors():
    txt = _logtext()
    today_lines = [l for l in txt.splitlines() if f"[{md()}" in l]
    pat = re.compile(r"Traceback|FATAL|\[err|\[ERROR|❌|Error:|Exception")
    errs = [l for l in today_lines if pat.search(l)]
    return ("✅" if not errs else "⚠️", f"今日錯誤/警示 {len(errs)} 筆", errs[-5:])


def check_keys():
    issues = []
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        issues.append("ANTHROPIC_API_KEY 未設（產線會停）")
    for name, p in [("YouTube token", STUDIO.parent / "token_manage.json"),
                    ("Analytics token", STUDIO.parent / "token_analytics.json")]:
        if not p.exists():
            issues.append(f"{name} 不存在（{p.name}）")
    return ("✅" if not issues else "⚠️", "金鑰/憑證" + ("齊全" if not issues else "有缺"), issues)


def main() -> int:
    checks = [
        ("腳本完整性", check_scripts), ("今日排程", check_cron), ("發布", check_publish),
        ("倉庫評分", check_library), ("主機健康", check_host), ("錯誤掃描", check_errors),
        ("金鑰/服務", check_keys),
    ]
    rows, all_issues = [], []
    worst = "✅"
    for name, fn in checks:
        try:
            icon, detail, issues = fn()
        except Exception as e:  # noqa: BLE001
            icon, detail, issues = "❌", f"檢查本身出錯：{str(e)[:50]}", []
        rows.append((icon, name, detail, issues))
        all_issues += [f"[{name}] {x}" for x in issues]
        if icon == "❌":
            worst = "❌"
        elif icon == "⚠️" and worst != "❌":
            worst = "⚠️"

    verdict = {"✅": "✅ 全系統健康", "⚠️": "⚠️ 有幾項要注意", "❌": "❌ 有嚴重問題，需處理"}[worst]
    L = [f"# 🩺 每日大檢查｜{today()}", "", f"## 總評：{verdict}", ""]
    if all_issues:
        L += ["### ⚠️ 待處理"] + [f"- {x}" for x in all_issues] + [""]
    L += ["### 逐項", "", "| | 項目 | 結果 |", "|---|---|---|"]
    for icon, name, detail, _ in rows:
        L.append(f"| {icon} | {name} | {detail} |")
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{today()}_大檢查.md").write_text("\n".join(L), encoding="utf-8")
    log_ops("每日大檢查", f"{verdict}｜待處理 {len(all_issues)} 項")
    print(f"[{'ok' if worst != '❌' else 'FAIL'}] 每日大檢查：{verdict}，待處理 {len(all_issues)} 項 → {today()}_大檢查.md")
    for x in all_issues:
        print("  - " + x)
    # 推播到老闆手機/信箱（出國也能瞄一眼健康狀況）
    try:
        from notify import push
        body = verdict + (("\n" + "\n".join("• " + x for x in all_issues)) if all_issues else "\n一切順，放心玩。")
        push(f"量化阿森 體檢 {today()} {worst}", body, tag=("warning" if worst != "✅" else "white_check_mark"))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
