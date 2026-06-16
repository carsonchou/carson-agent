#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ntfy_command.py — 【手機遠端指令】老闆在 ntfy app 打字下令，雲端讀取+執行+回報。

出國只用手機就能指揮工作室：在 ntfy app 對『指令頻道』發訊息（如「補產5支」「暫停」「上架」
「門檻75」「整理」「重新評分」「大檢查」「狀態」），本檔每 N 分鐘輪詢一次、解析、執行，
再把結果推回『健康頻道』給老闆看。
指令頻道名要保密（誰知道誰能下令）→ 放 design_system 的 "ntfy_cmd_topic" 或環境變數 NTFY_CMD_TOPIC。
已執行的訊息以 id 去重（ntfy_cmd_seen.json），不重複執行。
用法：python scripts/ntfy_command.py   （排程每 10 分鐘跑）
"""
from __future__ import annotations
import json, os, re, subprocess, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STUDIO = ROOT / "STUDIO"
DESIGN = STUDIO / "design_system.json"
DIRECTIVES = STUDIO / "boss_directives.json"
SEEN = STUDIO / "ntfy_cmd_seen.json"
PY = sys.executable

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(s, m): pass
try:
    from notify import push
except Exception:  # noqa: BLE001
    def push(t, b, tag="robot"): return False


def _cmd_topic():
    v = os.environ.get("NTFY_CMD_TOPIC", "").strip()
    if v:
        return v
    try:
        return (json.loads(DESIGN.read_text(encoding="utf-8")).get("ntfy_cmd_topic") or "").strip()
    except Exception:
        return ""


def _seen():
    try:
        return set(json.loads(SEEN.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_seen(s):
    try:
        SEEN.write_text(json.dumps(sorted(s)[-300:], ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _run(args, timeout=900):
    try:
        r = subprocess.run([PY] + args, cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        tail = "\n".join((r.stdout or "").strip().splitlines()[-3:])
        return tail or "(完成)"
    except Exception as e:  # noqa: BLE001
        return f"執行失敗：{str(e)[:80]}"


def _set_paused(val):
    try:
        d = json.loads(DIRECTIVES.read_text(encoding="utf-8")) if DIRECTIVES.exists() else {}
    except Exception:
        d = {}
    d["paused"] = val
    DIRECTIVES.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return "已暫停全自動（補產/上架今天先停）" if val else "已恢復全自動"


def _status():
    try:
        q = json.loads((STUDIO / "quality_scores.json").read_text(encoding="utf-8"))
        s = q.get("summary", {})
        return (f"倉庫未發布 {s.get('pending','?')}（pass {s.get('pass','?')}）、已發布 {s.get('published','?')}、"
                f"門檻 {q.get('min_score','?')}（更新 {q.get('updated','?')}）")
    except Exception:
        return "（暫無評分資料）"


HELP = ("📱 手機指令台（打字即執行）：\n"
        "狀態／報告｜暫停｜恢復｜補產N｜上架｜門檻N｜整理｜重新評分｜大檢查｜"
        "決策｜回顧｜情報｜爆款偵測｜寄生｜熱點｜實驗系列｜爆款獵手｜"
        "排程囤片N天｜跨平台｜每日產量N｜退件最低｜幫助")


def _set_headcount(n):
    p = STUDIO / "headcount.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        d = {}
    d["②"] = int(n)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"每日 Shorts 產量設為 {n} 支（下次 06:07 起生效）"


def _latest_report():
    try:
        from pathlib import Path as _P
        reps = sorted((STUDIO / "REPORTS").glob("*_大檢查.md"), reverse=True)
        if reps:
            return "\n".join(reps[0].read_text(encoding="utf-8").splitlines()[:10])
    except Exception:
        pass
    return _status()


def _reject_lowest():
    """退件目前未發布裡分數最低那支(免在手機選 slug)。"""
    try:
        q = json.loads((STUDIO / "quality_scores.json").read_text(encoding="utf-8"))
        pend = [p for p in q.get("pending", []) if p.get("score") is not None]
        if not pend:
            return "未發布區沒有可退件的片。"
        worst = min(pend, key=lambda x: x["score"])
        out = _run(["scripts/quality_score.py", "--reject", worst["slug"], "--remake"], timeout=900)
        return f"已退件最低分 {worst['score']} 並重做：{worst['title'][:24]}\n{out}"
    except Exception as e:  # noqa: BLE001
        return f"退件失敗：{str(e)[:60]}"


def handle(text):
    """把一句指令對應到動作，執行並回傳結果字串；認不出回 None。"""
    t = text.strip()
    m = re.search(r"(\d+)", t)
    num = int(m.group(1)) if m else None
    # 說明
    if any(k in t for k in ("幫助", "help", "指令", "功能", "怎麼用")):
        return HELP
    # 狀態 / 報告
    if any(k in t for k in ("狀態", "現況", "status")):
        return _status()
    if any(k in t for k in ("報告", "匯報", "大檢查報告", "體檢報告")):
        return _latest_report()
    # 開關
    if any(k in t for k in ("暫停", "停一下", "停止", "stop", "pause")):
        return _set_paused(True)
    if any(k in t for k in ("恢復", "繼續", "開工", "resume")):
        return _set_paused(False)
    # 設定
    if any(k in t for k in ("門檻", "標準", "threshold")) and num:
        return "設門檻：" + _run(["scripts/quality_score.py", "--set-min", str(num)])
    if any(k in t for k in ("每日產量", "每天產", "產量", "員額")) and num:
        return _set_headcount(num)
    # 產製 / 發布
    if any(k in t for k in ("補產", "產片", "做片", "囤片", "生產")):
        n = num or 4
        return f"補產 {n} 支：" + _run(["scripts/produce_batch.py", "--shorts", str(n),
                                       "--long", "0", "--target", "999", "--manual"])
    if any(k in t for k in ("上架", "發布", "發片", "上片")):
        return "上架：" + _run(["scripts/daily_publish.py", "--max", "6", "--privacy", "public"], timeout=600)
    if any(k in t for k in ("排程囤片", "排程", "囤排程", "斷網保險")):
        days = num or 7
        return f"排程囤片 {days} 天：" + _run(["scripts/schedule_publish.py", "--days", str(days),
                                            "--per-day", "1", "--start", "1", "--hour", "20", "--max", str(days)], timeout=600)
    # 倉庫 / 品質
    if any(k in t for k in ("整理", "去重", "tidy")):
        return "整理倉庫：" + _run(["scripts/quality_score.py", "--tidy"])
    if any(k in t for k in ("重新評分", "評分", "重評", "打分")):
        return "重新評分：" + _run(["scripts/quality_score.py"])
    if any(k in t for k in ("退件", "退最低", "退爛片")):
        return _reject_lowest()
    if any(k in t for k in ("大檢查", "體檢", "健檢")):
        return "大檢查：" + _run(["scripts/daily_check.py"])
    # 各部門 / 成長引擎
    if any(k in t for k in ("決策", "做決定")):
        return "決策：" + _run(["scripts/decision_dept.py"])
    if any(k in t for k in ("回顧", "檢討")):
        return "回顧：" + _run(["scripts/retro_dept.py"])
    if any(k in t for k in ("情報", "競品")):
        return "競品情報：" + _run(["scripts/intel_dept.py", "--no-learn"])
    if any(k in t for k in ("爆款偵測", "outlier", "異常爆款")):
        return "爆款偵測：" + _run(["scripts/outlier_scan.py", "--top", "20"])
    if any(k in t for k in ("寄生",)):
        return "寄生選題：" + _run(["scripts/parasite_titles.py", "--count", "6"])
    if any(k in t for k in ("熱點", "搶首發")):
        return "熱點搶首發：" + _run(["scripts/hotspot_dept.py", "--max", "5"])
    if any(k in t for k in ("實驗系列", "實驗格式")):
        return "實驗系列：" + _run(["scripts/experiment_series.py", "--count", "6"])
    if any(k in t for k in ("爆款獵手", "獵手", "學贏點")):
        return "爆款獵手：" + _run(["scripts/breakout_hunter.py"])
    if any(k in t for k in ("跨平台", "分發", "tiktok", "ig", "多平台")):
        _run(["scripts/multipost_dept.py", "--max", "50"], timeout=300)
        return "跨平台分發：" + _run(["scripts/multipost_upload.py", "--max", "8"], timeout=600)
    return None  # 認不出


def main() -> int:
    topic = _cmd_topic()
    if not topic:
        print("[info] 未設 ntfy_cmd_topic，遠端指令未啟用。"); return 0
    import requests
    try:
        r = requests.get(f"https://ntfy.sh/{topic}/json", params={"poll": "1", "since": "15m"}, timeout=25)
        msgs = [json.loads(ln) for ln in r.text.splitlines() if ln.strip()]
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 讀指令失敗：{e}", file=sys.stderr); return 0
    seen = _seen()
    did = 0
    for msg in msgs:
        if msg.get("event") != "message":
            continue
        mid = msg.get("id", "")
        body = (msg.get("message") or "").strip()
        if not mid or mid in seen or not body:
            continue
        seen.add(mid)
        result = handle(body)
        if result is None:
            push("🤖 沒聽懂指令", f"你說：{body}\n可用：補產N/上架/暫停/恢復/門檻N/整理/重新評分/大檢查/狀態", tag="question")
        else:
            push(f"🤖 已執行：{body[:20]}", result[:500], tag="white_check_mark")
            log_ops("遠端指令", f"{body[:20]} → 已執行")
            did += 1
    _save_seen(seen)
    print(f"[ok] 遠端指令：處理 {did} 則。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
