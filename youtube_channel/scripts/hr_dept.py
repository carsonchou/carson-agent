#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hr_dept.py — 【⑬ 人事部】部門監察官 + 編制管理。

職責（誠實：盯的是「其他部門本身的健康」，不是影片）：
  1) 出勤：各部門今天有沒有按排程跑（讀 REPORTS 時間戳 / output mtime / production_orders）
  2) 健康：哪個部門一直出錯／連續失敗（讀 ops_log 異常）
  3) 考核：產量、過審率、員額編制（讀 metrics_history / headcount）
  4) 編制建議：哪個「規劃中」該開、哪個員額偏低該擴編

輸出：STUDIO/REPORTS/{date}_人事監察.md ＋ STUDIO/hr_status.json（GUI 可讀）
員額存於 STUDIO/headcount.json（GUI 人事部分頁 ➕招募/➖ 調整；①②員額＝每日產量）。
"""
from __future__ import annotations

import json
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
OPS = STUDIO / "ops_log.txt"
HEADCOUNT = STUDIO / "headcount.json"
HISTORY = STUDIO / "metrics_history.json"
HR_STATUS = STUDIO / "hr_status.json"
DIRECTIVES = STUDIO / "boss_directives.json"
LEDGER = STUDIO / "uploaded_ledger.json"

# 部門清單（與 control_center.DEPTS 對齊，16 部門）：tag, 名稱, 預設員額, 出勤判斷依據
DEPTS = [
    ("①", "影片部門（長片）", 3, "out_L"),
    ("②", "Shorts 部門", 4, "out_S"),
    ("③", "創作靈感部門", 2, "orders"),
    ("④", "頻道整理部門", 2, "rep_頻道整理"),
    ("⑤", "流量部門（SEO）", 2, "embed"),
    ("⑥", "宣傳部門", 2, "rep_宣傳文案"),
    ("⑦", "數據分析部門", 2, "api"),
    ("⑧", "社群留言部門", 2, "rep_留言回覆草稿"),
    ("⑨", "審核部門（發布閘門）", 3, "rep_自動上架"),
    ("⑩", "總監管部門", 1, "rep_營運匯報"),
    ("⑪", "決策部門（大腦）", 2, "rep_決策"),
    ("⑫", "回顧檢討部門（自省）", 1, "rep_回顧檢討"),
    ("⑬", "人事部（監察＋編制）", 2, "self"),
    ("⑭", "財務／變現部", 2, "rep_財務"),
    ("⑮", "縮圖／CTR 部", 2, "rep_縮圖CTR"),
    ("⑯", "競品情報部", 2, "rep_競品情報"),
]
DEFAULT_HEAD = {t: h for t, h, *_ in [(d[0], d[2]) for d in DEPTS]}

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(dept, msg):
        try:
            OPS.parent.mkdir(parents=True, exist_ok=True)
            with OPS.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now().strftime('%H:%M')} [{dept}] {msg}\n")
        except Exception:
            pass


def tw_today():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def _load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else default
    except Exception:
        return default


def load_headcount():
    hc = dict(DEFAULT_HEAD)
    saved = _load(HEADCOUNT, {})
    if isinstance(saved, dict):
        for k, v in saved.items():
            if k in hc and isinstance(v, int) and v >= 0:
                hc[k] = v
    return hc


def _rep(date, suffix):
    return (REPORTS / f"{date}_{suffix}.md").exists()


def _out_today(prefix, date):
    n = 0
    for p in OUT.glob(f"{prefix}*.mp4"):
        try:
            if datetime.fromtimestamp(p.stat().st_mtime, timezone(timedelta(hours=8))).strftime("%Y-%m-%d") == date:
                n += 1
        except Exception:
            pass
    return n


def attendance(basis, date):
    """回傳 (出勤?, 說明)。todo/embed/api 類不算缺勤（本就沒獨立排程）。"""
    if basis == "out_L":
        n = _out_today("L_", date); return (n > 0, f"今日產長片 {n} 支")
    if basis == "out_S":
        n = _out_today("S_", date); return (n > 0, f"今日產 Shorts {n} 支")
    if basis == "orders":
        ok = (STUDIO / "production_orders.json").exists(); return (ok, "題庫指令已就緒" if ok else "無題庫指令")
    if basis.startswith("rep_"):
        s = basis[4:]
        if _rep(date, s):
            return (True, f"今日{s}報表已產")
        if _ran_recently(s):  # 排程在人事之後的部門：近30h跑過也算出勤
            return (True, f"{s}近期有產（排程稍後/昨日）")
        return (False, f"今日{s}報表未產")
    if basis == "self":
        return (True, "監察中")
    if basis == "embed":
        return (True, "併入腳本產出（無獨立排程）")
    if basis == "api":
        return (True, "唯讀數據源")
    return (None, "規劃中・尚未自動化")  # todo


def health():
    errs = []
    try:
        for ln in OPS.read_text(encoding="utf-8").splitlines()[-100:]:
            if any(k in ln for k in ("⚠️", "FAIL", "失敗", "錯誤", "FATAL")):
                errs.append(ln.strip())
    except Exception:
        pass
    return errs


def _ran_recently(suffix, hours=30):
    """REPORTS 中任一 *_{suffix}.md 在 hours 內被改過 → 視為近期有跑（避開排程先後誤判）。"""
    import time
    cutoff = time.time() - hours * 3600
    try:
        for p in REPORTS.glob(f"*_{suffix}.md"):
            if p.stat().st_mtime >= cutoff:
                return True
    except Exception:
        pass
    return False


def _out_count_today(prefix, date):
    n = 0
    for p in OUT.glob(f"{prefix}*.mp4"):
        try:
            if datetime.fromtimestamp(p.stat().st_mtime, timezone(timedelta(hours=8))).strftime("%Y-%m-%d") == date:
                n += 1
        except Exception:
            pass
    return n


def kpi_grade(date, hc):
    """依《部門職掌定義書》KPI 對各部門評等。回傳 {tag: (grade, note)}。
    grade：✅達標 / ⚠️待加強 / 🔴未達 / —（不適用或數據不足，誠實不假裝）。"""
    paused = _load(DIRECTIVES, {}).get("paused", False)
    g = {}

    def via_report(tag, suffix, label):
        g[tag] = ("✅達標", f"{label}近期有產出") if _ran_recently(suffix) else ("⚠️待加強", f"{label}近30h未見")

    # ①② 產量達標（06:07 已跑，今日數有效）
    for tag, pref in (("①", "L_"), ("②", "S_")):
        target = hc.get(tag, 0)
        n = _out_count_today(pref, date)
        if target == 0:
            g[tag] = ("—", "編制 0，無產量要求")
        elif paused:
            g[tag] = ("—", "全自動暫停中")
        elif n >= target:
            g[tag] = ("✅達標", f"產 {n}/{target} 支")
        elif n > 0:
            g[tag] = ("⚠️待加強", f"產 {n}/{target} 支（未滿編制）")
        else:
            g[tag] = ("🔴未達", f"今日 0/{target} 支")
    # ③ 題庫新鮮度
    try:
        upd = _load(STUDIO / "production_orders.json", {}).get("updated", "")
        g["③"] = ("✅達標", "題庫已更新") if upd == date or _ran_recently("決策") else ("⚠️待加強", "題庫未更新")
    except Exception:
        g["③"] = ("⚠️待加強", "題庫狀態未知")
    # ⑤ SEO：併入腳本，①②有產出即達標
    g["⑤"] = ("✅達標", "SEO 隨腳本產出") if (_out_count_today("S_", date) + _out_count_today("L_", date)) > 0 else ("—", "今日尚無新片")
    # ⑦ 數據：Analytics 是否接通
    g["⑦"] = ("✅達標", "Analytics 已接通") if (STUDIO.parent / "token_analytics.json").exists() else ("⚠️待加強", "僅基本統計，未接 Analytics")
    # ⑨ 審核：過審率（對今日產出且未上架者）
    led = _load(LEDGER, {}); up = set(led) if isinstance(led, dict) else set()
    today_slugs = [p.stem for pref in ("S_", "L_") for p in OUT.glob(f"{pref}*.mp4")
                   if datetime.fromtimestamp(p.stat().st_mtime, timezone(timedelta(hours=8))).strftime("%Y-%m-%d") == date]
    targets = [s for s in today_slugs if s not in up]
    if targets:
        passed = 0
        try:
            from audit_video import audit
            for s in targets:
                try:
                    ok, _ = audit(s)
                except Exception:
                    ok = False
                passed += 1 if ok else 0
        except Exception:
            passed = -1
        if passed < 0:
            g["⑨"] = ("—", "審核模組異常")
        else:
            rate = passed / len(targets) * 100
            g["⑨"] = (("✅達標" if rate == 100 else ("⚠️待加強" if rate >= 80 else "🔴未達")), f"過審率 {rate:.0f}%（{passed}/{len(targets)}）")
    else:
        g["⑨"] = ("—", "今日無待審新片")
    # 報表型部門（用近30h，避開排程先後）
    via_report("④", "頻道整理", "歸類")
    via_report("⑥", "宣傳文案", "文案")
    via_report("⑧", "留言回覆草稿", "回覆")
    via_report("⑩", "營運匯報", "匯報")
    via_report("⑪", "決策", "決策")
    via_report("⑫", "回顧檢討", "自省")
    via_report("⑮", "縮圖CTR", "縮圖分析")
    via_report("⑯", "競品情報", "競品掃描")
    g["⑬"] = ("✅達標", "監察執行中")
    # ⑭ 財務：有報表 + summary
    fin = _load(STUDIO / "finance.json", {})
    net = (fin.get("summary") or {}).get("net") if isinstance(fin, dict) else None
    if _ran_recently("財務"):
        g["⑭"] = ("✅達標", f"損益已結（淨 NT${net:.0f}）" if isinstance(net, (int, float)) else "損益已結")
    else:
        g["⑭"] = ("⚠️待加強", "近30h未結損益")
    return g


def main() -> int:
    date = tw_today()
    log_ops("人事部", "開始部門監察…")
    hc = load_headcount()
    errs = health()
    kpi = kpi_grade(date, hc)

    rows, absent, unbuilt = [], [], []
    for tag, name, _dh, basis in DEPTS:
        ok, note = attendance(basis, date)
        rows.append((tag, name, hc.get(tag, 0), ok, note))
        if ok is False:
            absent.append(f"{tag}{name}")
        if ok is None:
            unbuilt.append(f"{tag}{name}")

    total = sum(hc.values())
    base = sum(DEFAULT_HEAD.values())

    # 報告
    REPORTS.mkdir(parents=True, exist_ok=True)
    L = [f"# ⑬ 人事監察報告｜{date}", "",
         f"> 員額總計 {total} 人（初始 {base}，擴編 {'+' if total - base >= 0 else ''}{total - base}）；監察 {len(DEPTS)} 部門", "",
         "## 一、出勤、編制與 KPI 考核（對照《部門職掌定義書》）"]
    L.append("| 部門 | 員額 | 出勤 | KPI 考核 | 考核說明 |")
    L.append("|---|---|---|---|---|")
    for tag, name, h, ok, note in rows:
        mark = "✅" if ok else ("🕒缺勤" if ok is False else "—")
        grade, gnote = kpi.get(tag, ("—", ""))
        L.append(f"| {tag} {name} | {h} | {mark} | {grade} | {gnote} |")
    # 考核彙總
    weak = [f"{t}（{kpi[t][1]}）" for t in [d[0] for d in DEPTS] if kpi.get(t, ('',''))[0] in ("⚠️待加強", "🔴未達")]
    L += ["", "### KPI 考核彙總"]
    if weak:
        L.append(f"- ⚠️ 待加強／未達 {len(weak)} 項：{ '、'.join(weak) }")
        L.append("  → 已標記，⑫回顧檢討會據此優化、⑪決策據此調整。")
    else:
        L.append("- ✅ 全部門 KPI 達標（或不適用）。")
    L += ["", "## 二、健康"]
    if errs:
        L.append(f"- ⚠ 近期異常 {len(errs)} 條：")
        for e in errs[-6:]:
            L.append(f"    - {e[:80]}")
    else:
        L.append("- ✅ 近期無異常日誌")
    L += ["", "## 三、編制建議"]
    if absent:
        L.append(f"- 今日缺勤（請排查是否中斷）：{ '、'.join(absent) }")
    if unbuilt:
        L.append(f"- 尚未自動化、可考慮擴編開發：{ '、'.join(unbuilt) }")
    if hc.get("②", 0) < 4:
        L.append("- ②Shorts 員額偏低（衝量主力建議 ≥4）→ 可在決策中心人事部 ➕招募。")
    L.append("- 提醒：①／② 員額＝每日產量（加員額＝加產能）；其餘為容量編制。")
    (REPORTS / f"{date}_人事監察.md").write_text("\n".join(L), encoding="utf-8")

    # 給 GUI 的精簡狀態
    weak_tags = [t for t in [d[0] for d in DEPTS] if kpi.get(t, ('', ''))[0] in ("⚠️待加強", "🔴未達")]
    HR_STATUS.write_text(json.dumps({
        "date": date, "total_head": total, "base_head": base,
        "absent": absent, "unbuilt": unbuilt, "errors": len(errs), "kpi_weak": weak_tags,
        "rows": [{"tag": t, "name": n, "head": h, "attend": ok, "note": note,
                  "kpi": kpi.get(t, ("—", ""))[0], "kpi_note": kpi.get(t, ("—", ""))[1]}
                 for t, n, h, ok, note in rows],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    log_ops("人事部", f"監察完成 員額{total}人 缺勤{len(absent)} 異常{len(errs)} → {date}_人事監察.md")
    print(f"[ok] 人事監察完成：員額 {total} 人，缺勤 {len(absent)}，異常 {len(errs)}。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
