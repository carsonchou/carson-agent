#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""promo_dept.py — 【⑥ 宣傳部】產跨平台導流文案（草稿，不自動發）。

為最近上架的影片，用 Claude 產 FB / IG / Threads / Dcard 版文案（含 Pionex 連結＋風險聲明），
存成草稿給老闆人工貼。誠實：無社群自動發文 API，且為避免 spam/封號，只產草稿不自動發。
輸出：STUDIO/REPORTS/{date}_宣傳文案.md
"""
from __future__ import annotations
import json, os, re, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace"); sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
STUDIO = ROOT / "STUDIO"; REPORTS = STUDIO / "REPORTS"; LEDGER = STUDIO / "uploaded_ledger.json"
OUT = ROOT / "output"; CFG = ROOT / "channel_config.json"
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-haiku-4-5-20251001"
try:
    from ops import log_ops
except Exception:
    def log_ops(d, m): pass


def tw_today():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def aff_link():
    try:
        c = json.loads(CFG.read_text(encoding="utf-8"))
        return (c.get("affiliate", {}) or {}).get("pionex_url", "https://accounts.pionex.com/zh-TW/signUp?r=08NAcfvcWna")
    except Exception:
        return "https://accounts.pionex.com/zh-TW/signUp?r=08NAcfvcWna"


def recent_videos(n=2):
    led = {}
    try:
        led = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    except Exception:
        pass
    items = []
    for slug, vid in (led.items() if isinstance(led, dict) else []):
        title = slug
        md = OUT / f"{slug}.md"
        if md.exists():
            m = re.search(r"^#\s*🎬?\s*(.+)$", md.read_text(encoding="utf-8"), re.M)
            if m:
                title = m.group(1).strip()
        url = f"https://youtu.be/{vid}"
        mtime = (OUT / f"{slug}.mp4").stat().st_mtime if (OUT / f"{slug}.mp4").exists() else 0
        items.append({"slug": slug, "title": title, "url": url, "mtime": mtime})
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items[:n]


def gen_copy(vid):
    if not API_KEY:
        return None
    import requests
    prompt = f"""為這支 YouTube 影片寫跨平台導流文案（繁中），影片標題：「{vid['title']}」，連結：{vid['url']}
頻道=量化阿森(量化/自動交易教學)。誠信鐵則：不保證收益、不喊單、不編造損益。
請輸出 4 個版本（純文字，標清平台）：
1. Facebook（2-3 句＋1問句互動＋hashtag）
2. Instagram（短、emoji、hashtag）
3. Threads（口語、鉤子）
4. Dcard/PTT（理性分享口吻，重點條列）
每版結尾自然帶一句：想用工具實作可參考 Pionex（{aff_link()}），並附「投資有風險，內容為教學非投資建議」。"""
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                          json={"model": MODEL, "max_tokens": 1200, "messages": [{"role": "user", "content": prompt}]}, timeout=90)
        r.raise_for_status()
        return r.json()["content"][0]["text"]
    except Exception as e:
        print(f"[warn] 文案生成失敗：{e}", file=sys.stderr); return None


def main() -> int:
    vids = recent_videos(2)
    date = tw_today(); REPORTS.mkdir(parents=True, exist_ok=True)
    L = [f"# ⑥ 宣傳文案（草稿）｜{date}", "",
         "> 跨平台導流文案草稿。誠實：無社群自動發文 API，為避免 spam/封號**只產草稿、不自動發**，請人工貼。", ""]
    if not vids:
        L.append("（尚無已上架影片）")
    for v in vids:
        L += [f"## 🎬 {v['title']}", f"連結：{v['url']}", ""]
        copy = gen_copy(v)
        L.append(copy if copy else "（文案生成失敗或無 ANTHROPIC_API_KEY，請稍後重跑）")
        L.append("")
    (REPORTS / f"{date}_宣傳文案.md").write_text("\n".join(L), encoding="utf-8")
    log_ops("宣傳部", f"產出 {len(vids)} 支影片的跨平台文案草稿")
    print(f"[ok] 宣傳文案草稿完成：{len(vids)} 支影片。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
