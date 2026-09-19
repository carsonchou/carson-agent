#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""thumbnail_dept.py — 【⑮ 縮圖／CTR 部】縮圖覆蓋率 + 點擊優化建議。

檢查已上架影片的縮圖狀態（有無自訂高解析縮圖），對表現/覆蓋不足者用 Claude 給
A/B 標題與縮圖文案建議。誠實：真 CTR 需 YouTube Analytics 權限（目前 token 為 force-ssl，
無 analytics scope）→ 不假裝有 CTR 數字，改給「覆蓋率 + 點擊優化建議」。
輸出：STUDIO/REPORTS/{date}_縮圖CTR.md
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace"); sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"; REPORTS = STUDIO / "REPORTS"; LEDGER = STUDIO / "uploaded_ledger.json"


def _load_env():
    """直跑時把專案根 .env 併進 os.environ(cron 由 local_cron 載;直跑沒有→llm.complete 拿不到
    OPENROUTER key→A/B 建議鉤子靜默失敗)。同 make_thumbnails.py/quality_score.py 的作法。"""
    envf = ROOT / ".env"
    if envf.exists():
        for ln in envf.read_text(encoding="utf-8", errors="replace").splitlines():
            s = ln.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()
try:
    from ops import log_ops
except Exception:
    def log_ops(d, m): pass


def tw_today():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def main() -> int:
    try:
        from decision_dept import yt_service
        yt = yt_service()
    except Exception as e:
        print(f"[FATAL] 無法連 YouTube：{e}", file=sys.stderr); return 2
    led = {}
    try:
        led = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    except Exception:
        pass
    ids = list(led.values()) if isinstance(led, dict) else []
    rows = []
    for i in range(0, len(ids), 50):
        try:
            r = yt.videos().list(part="snippet,statistics", id=",".join(ids[i:i+50])).execute()
            for it in r.get("items", []):
                th = it["snippet"].get("thumbnails", {})
                has_hi = "maxres" in th or "standard" in th  # 高解析≈有自訂縮圖（粗略判斷）
                rows.append({"title": it["snippet"]["title"][:50],
                             "views": int(it.get("statistics", {}).get("viewCount", 0)),
                             "has_hi": has_hi})
        except Exception as e:
            print(f"[warn] 取影片失敗：{e}", file=sys.stderr)
    rows.sort(key=lambda x: x["views"], reverse=True)
    missing = [r for r in rows if not r["has_hi"]]
    cover = (len(rows) - len(missing)) / len(rows) * 100 if rows else 0

    # 對前段低觀看者給 A/B 建議（走共用 llm.py 路由：OpenRouter 等任一供應商 key 存在才嘗試，
    # 全失敗才留空——根因：舊版直打 api.anthropic.com + 讀 ANTHROPIC_API_KEY，工作室早改
    # OpenRouter，Anthropic key 已失效，導致這支的 LLM 建議鉤子一直靜默失敗）
    suggestions = ""
    has_any_key = any(os.environ.get(k, "").strip() for k in
                      ("OPENROUTER_API_KEY", "GROQ_API_KEY", "DEEPSEEK_API_KEY",
                       "GEMINI_API_KEY", "ANTHROPIC_API_KEY"))
    if has_any_key and rows:
        worst = rows[-5:]
        prompt = "你是 YouTube 縮圖/標題優化顧問（量化交易頻道，繁中）。針對以下表現較弱的影片，各給 1 組更高點擊的『新標題 + 縮圖主視覺文案(≤6字大字)』建議。誠信：不誇大不保證。只輸出條列：\n" + \
                 "\n".join(f"- {w['title']}（{w['views']} 觀看）" for w in worst)
        try:
            import llm  # 共用路由：主供應商(OpenRouter)→失敗退回 fallback，換模型只改 env
            suggestions = llm.complete(prompt, max_tokens=900)
        except Exception as e:
            suggestions = f"（建議生成失敗：{e}）"

    # 真實 CTR（若已跑 auth_analytics.py 拿到 Analytics 權限）
    ctr_line = "> 誠實：真 CTR 需 YouTube Analytics 權限（目前未授權），故以『縮圖覆蓋率 + 點擊優化建議』替代，不假裝有點閱率數字。"
    try:
        import yt_analytics as ya
        if ya.available():
            summ = ya.channel_summary(28)
            ic = ya.impressions_ctr(28)
            if summ is not None:
                parts = [f"平均觀看 {summ['avg_pct']:.1f}%", f"觀看 {summ['views']}", f"新增訂閱 {summ['subs_gained']}"]
                if ic is not None:
                    parts.insert(0, f"曝光 {ic['impressions']:,}、CTR {ic['ctr']:.2f}%")
                else:
                    parts.append("（曝光CTR需更多流量才有值）")
                ctr_line = "> ✅ 已接 YouTube Analytics（近28天）：" + "、".join(parts) + "。"
    except Exception:
        pass

    date = tw_today(); REPORTS.mkdir(parents=True, exist_ok=True)
    L = [f"# ⑮ 縮圖／CTR 報告｜{date}", "",
         ctr_line, "",
         "## 一、縮圖覆蓋率",
         f"- 已上架 {len(rows)} 支，疑似缺自訂高解析縮圖 {len(missing)} 支，覆蓋率約 {cover:.0f}%",
         "- 待補縮圖（建議用 make_thumbnails.py / set_thumbnails.py 補上）："]
    for m in missing[:12]:
        L.append(f"    - {m['title']}")
    if not missing:
        L.append("    -（看起來都有縮圖，讚）")
    L += ["", "## 二、A/B 標題＋縮圖文案建議（針對較弱影片）", suggestions or "（需任一 LLM 供應商 key 才生成）"]
    (REPORTS / f"{date}_縮圖CTR.md").write_text("\n".join(L), encoding="utf-8")
    log_ops("縮圖CTR", f"覆蓋率{cover:.0f}% 待補{len(missing)}支")
    print(f"[ok] 縮圖/CTR 報告完成：覆蓋率 {cover:.0f}%，待補 {len(missing)} 支。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
