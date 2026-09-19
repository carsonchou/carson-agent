#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daily_check.py — 【每日大檢查】整套系統自動體檢，揪出問題寫成報告。

每天排程跑一次（不花 API、純讀檔/編譯/查主機）。檢查：
  1) 腳本完整性：py_compile 全部 scripts/*.py（抓語法錯，防壞代碼上線）
  2) 今日排程：排程日誌(local_cron.log + STUDIO/ops_log.txt)有沒有今天的 製作/上架 紀錄
  3) 發布：ledger 數、可發布候選、今日上架幾支
  4) 倉庫評分：未發布/pass/退件、門檻、有沒有卡住的低分片
  5) 主機健康：磁碟/記憶體/負載
  6) 錯誤掃描：今日排程日誌的 Traceback/FATAL/⚠️ 次數
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
# 🔴 2026-07-30 這份健檢一直在說謊,根因兩個,都在這裡:
#   ①路徑錯:LOG 原本只指 logs/cron.log——**那是雲端 crontab 時代的檔,搬本機後根本不存在**
#     (工作室已改 local_cron.py,見 memory yt-studio-local-migration)。讀不到 → 空字串 →
#     報「今日 cron.log 無任何紀錄(cron 沒跑?)」+「今日上架相關紀錄 0 筆」。
#     但實測今天確實發了 3 支(00:03/09:16/11:01),排程器 PID 也活著 → **純假警報**。
#   ②日期格式不相容:local_cron.log 寫 `[2026-07-30 11:35:11]`(帶年),
#     而比對用的是 `[07-30`(md() 給 %m-%d)→ 就算改對路徑也照樣抓不到。
#     (只修①不修②=修了一半還是假警報,這是「修在沒人走的路上」的變體。)
# 假警報比沒有報告更糟:它會訓練人忽略這份報告,真問題就藏在裡面
#   (同 memory yt-analytics-lag-false-alarm:工具會說謊,而謊會被每個未來 session 繼承)。
LOGS = (
    ROOT / "logs" / "local_cron.log",   # 現行本機排程器(job 啟動/完成)
    ROOT / "logs" / "cron.log",         # 雲端時代遺留,通常不存在;留著以防哪天回雲端
    STUDIO / "ops_log.txt",             # 各部門紀錄——「上架N支/即時發布」真的寫在這
)
LOG = LOGS[0]        # 保留單數名稱給既有引用(若有)
_LOG_TAIL_BYTES = 2_000_000   # 只讀尾段:日誌會長大,健檢不需要讀完整檔
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
    """把所有真實日誌來源串起來(讀不到的略過)。只讀尾段,避免日誌變大後拖慢健檢。"""
    parts = []
    for p in LOGS:
        try:
            if not p.exists():
                continue
            with open(p, "rb") as fh:
                sz = p.stat().st_size
                if sz > _LOG_TAIL_BYTES:
                    fh.seek(sz - _LOG_TAIL_BYTES)
                parts.append(fh.read().decode("utf-8", errors="replace"))
        except Exception:  # noqa: BLE001  某個來源壞掉不該讓整份健檢掛掉
            continue
    return "\n".join(parts)


def _is_today(line: str) -> bool:
    """這行是不是今天的。**同時接受兩種日期格式**:
    ops_log.txt 是 `[07-30 09:16:45]`,local_cron.log 是 `[2026-07-30 11:35:11]`。
    只認一種就會漏掉另一個來源(這正是本檔假警報的第二個根因)。
    """
    n = datetime.now(TW)
    return (f"[{n.strftime('%m-%d')}" in line
            or f"[{n.strftime('%Y-%m-%d')}" in line
            or f" {n.strftime('%m-%d')} " in line)


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
    today_lines = [l for l in txt.splitlines() if _is_today(l)]
    produced = any(("補產" in l or "produce" in l.lower()) for l in today_lines)
    published = any(("上架" in l or "發布" in l) for l in today_lines)
    detail = (f"今日排程紀錄 {len(today_lines)} 行；"
              f"製作{'✓' if produced else '✗'}、上架/發布{'✓' if published else '✗'}")
    ok = "✅" if (produced or published) else "⚠️"
    _src = "、".join(p.name for p in LOGS if p.exists()) or "無"
    return (ok, detail,
            [] if today_lines else [f"今日排程日誌無任何紀錄（cron 沒跑？來源：{_src}）"])


def check_publish():
    led = _load(LEDGER, {})
    # 🔴 2026-07-30 「可發布候選」原本是 `glob("*.mp4") 扣掉帳本`,結果報 **474**,
    # 而發布端真正發得出去的只有 **42**——差 11 倍。灌水來源:
    #   ①`_ytcta` 跨平台衍生檔(output 下 371 個,沒有自己的腳本,永遠發不出去)
    #   ②publish_skip.json 的永久跳過名單(77 支:捏數事故片/禁用洗版骨架/重複題)
    #   ③品質未達門檻、審核未過、誠信溯源閘擋下的
    # 一個灌水 11 倍的數字放在健檢報告上,比不放更糟(會讓人以為庫存很厚)。
    #
    # 修法刻意**不再實作一次排除規則**——那會變成第四份(produce_batch.queue_size、
    # quality_score.all_slugs、daily_publish.find_candidates 各有一份,而歷史事故都是
    # 「多份實作漏一處」)。這裡直接呼叫發布端的權威函式,報的就是它會發的那個數。
    # find_candidates 只讀檔+讀 JSON,不打任何 API(符合本健檢「不花 API」的前提),
    # 但會 print 一堆明細 → 用 redirect_stdout 吞掉,別汙染報告輸出。
    cand = None
    try:
        import contextlib
        import io as _io
        sys.path.insert(0, str(SCRIPTS))
        import daily_publish as _dp
        _buf = _io.StringIO()
        with contextlib.redirect_stdout(_buf):
            cand = _dp.find_candidates(_dp.load_ledger())
    except Exception as e:  # noqa: BLE001
        cand = None
        _fallback_note = str(e)[:40]
    if cand is None:
        # 退回舊算法但**明確標示這是粗估**,不要讓人以為是可發數(至少排掉衍生檔)
        mp4 = [Path(p).stem for p in glob.glob(str(OUT / "*.mp4"))]
        rough = [s for s in mp4 if s not in led and "_ytcta" not in s]
        return ("⚠️", f"已發布 {len(led)}、未發布成片（粗估，非可發數）{len(rough)}"
                      f"、今日上架相關紀錄 ?（候選查詢失敗）",
                ["可發候選查詢失敗，數字僅為粗估"])
    txt = _logtext()
    pub_today = len([l for l in txt.splitlines() if _is_today(l) and ("上架" in l or "即時發布" in l)])
    issues = []
    if not cand and not led:
        issues.append("無候選也無已發布（產線可能沒在跑）")
    if led and not cand:
        issues.append("可發候選為 0（庫存見底或全被閘門擋下，明天可能無片可發）")
    return ("✅" if cand or led else "⚠️",
            f"已發布 {len(led)}、**可發布候選 {len(cand)}**（過完所有閘門的真實可發數）"
            f"、今日上架相關紀錄 {pub_today} 筆", issues)


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
    today_lines = [l for l in txt.splitlines() if _is_today(l)]
    pat = re.compile(r"Traceback|FATAL|\[err|\[ERROR|❌|Error:|Exception")
    errs = [l for l in today_lines if pat.search(l)]
    return ("✅" if not errs else "⚠️", f"今日錯誤/警示 {len(errs)} 筆", errs[-5:])


def check_keys():
    issues = []
    # 🔴 2026-07-30 這裡曾經給出**假綠燈**,而且假在「產線正停著」的那一項上:
    #   ①只讀 os.environ,沒載 .env → 由 local_cron 跑(有載 .env)看得到 OPENROUTER_API_KEY,
    #     手動裸跑就看不到 → **同一份健檢,結論隨呼叫方式改變**。
    #   ②邏輯是「**有任何一家的 key** 就算沒問題」。實測當天:OPENROUTER_API_KEY 不在環境裡、
    #     但 ANTHROPIC_API_KEY 在 → 判定「金鑰齊全 ✅」、餘額檢查整段跳過。
    #     而那天三家全死(OpenRouter 餘額 -$0.20;Anthropic 也回 400「credit balance is too low」)。
    #   **「key 存在」不等於「能用」——沒錢的 key 和沒有 key 一樣停產。**
    # 修法:先載 .env(結論不再隨呼叫方式變),再檢查**實際被設定的供應商鏈**
    # (LLM_PROVIDER / LLM_FALLBACK),而不是「有沒有任何 key」;鏈上有 OpenRouter 就查餘額。
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:  # noqa: BLE001  沒有 dotenv 也不該讓健檢掛掉
        pass
    _primary = (os.environ.get("LLM_PROVIDER", "openrouter") or "").strip().lower()
    _fallback = (os.environ.get("LLM_FALLBACK", "") or "").strip().lower()
    _chain = [p for p in (_primary, _fallback) if p]
    _envmap = {"openrouter": "OPENROUTER_API_KEY", "groq": "GROQ_API_KEY",
               "deepseek": "DEEPSEEK_API_KEY", "gemini": "GEMINI_API_KEY",
               "anthropic": "ANTHROPIC_API_KEY"}
    _missing = [p for p in _chain if not os.environ.get(_envmap.get(p, ""), "").strip()]
    if _missing:
        issues.append(f"供應商鏈缺 key：{'、'.join(_missing)}"
                      f"（LLM_PROVIDER={_primary or '未設'}／LLM_FALLBACK={_fallback or '未設'}）")
    ork = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not _chain:
        issues.append("未設定任何 LLM 供應商（LLM_PROVIDER/LLM_FALLBACK 都空，產線會停）")
    elif ork and "openrouter" in _chain:
        try:
            import requests
            r = requests.get("https://openrouter.ai/api/v1/credits",
                             headers={"Authorization": f"Bearer {ork}"}, timeout=15)
            if r.status_code == 200:
                j = r.json().get("data", {}) or {}
                remain = float(j.get("total_credits") or 0) - float(j.get("total_usage") or 0)
                if remain <= 0.5:
                    issues.append(f"OpenRouter 餘額僅 ${remain:.2f}（即將停產，快儲值）")
            elif r.status_code in (401, 403):
                issues.append("OpenRouter key 失效（401/403，產線會停）")
        except Exception as e:  # noqa: BLE001
            issues.append(f"OpenRouter 餘額查不到：{str(e)[:40]}")
    for name, p in [("YouTube token", STUDIO.parent / "token_manage.json"),
                    ("Analytics token", STUDIO.parent / "token_analytics.json")]:
        if not p.exists():
            issues.append(f"{name} 不存在（{p.name}）")
    # Analytics token 實際能否 refresh(被撤銷時檔案還在但 refresh 會失敗→數據靜默斷線)
    try:
        import yt_analytics
        if yt_analytics.available() and yt_analytics._service() is None:
            issues.append("Analytics token 無法 refresh（可能被撤銷，成效數據會斷）")
    except Exception:  # noqa: BLE001
        pass
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
