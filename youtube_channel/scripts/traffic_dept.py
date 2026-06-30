#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""traffic_dept.py — 【⑤ 流量部門（數據選題）】從 Analytics 找會爆的題材方向。

每天 05:35 跑（decision_dept 05:37 前），分析：
  1) 近 28 天頻道彙總（觀看/留存/訂閱）
  2) 各影片表現 → 找出高觀看/高留存/高帶訂閱的題材格局
  3) 用 Claude 萃取「下一批該做什麼」的選題建議，補充到 production_orders.json

無 Analytics token（token_analytics.json）→ 降級只做 YouTube Data API 的統計分析。
無 Anthropic key → 只輸出原始數據報告，不做 AI 萃取。
所有 API 失敗都 soft（不影響後續排程）。

輸出：
  STUDIO/traffic_data.json          → decision_dept 讀取（流量訊號）
  STUDIO/REPORTS/{date}_流量選題.md → 每日匯報分頁可看
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
LEDGER = STUDIO / "uploaded_ledger.json"
ORDERS = STUDIO / "production_orders.json"
TRAFFIC = STUDIO / "traffic_data.json"
TOKEN = ROOT / "token_manage.json"
TW = timezone(timedelta(hours=8))

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = "claude-haiku-4-5-20251001"  # 流量分析用快速模型省成本

try:
    from ops import log_ops
except Exception:  # noqa: BLE001
    def log_ops(d, m): pass

try:
    import yt_analytics
    _HAS_ANALYTICS = True
except Exception:
    _HAS_ANALYTICS = False


def tw_today():
    return datetime.now(TW).strftime("%Y-%m-%d")


def _load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8")) if Path(p).exists() else default
    except Exception:
        return default


# ── YouTube Data API：從 ledger 抓各影片的標題+觀看數（補 Analytics 沒有標題的缺）──
def _yt_video_titles(video_ids: list[str]) -> dict:
    """回傳 {videoId: title}，無 token 則回 {}。"""
    if not TOKEN.exists() or not video_ids:
        return {}
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        creds = Credentials.from_authorized_user_file(str(TOKEN),
            ["https://www.googleapis.com/auth/youtube.force-ssl"])
        if not creds.valid and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        yt = build("youtube", "v3", credentials=creds)
        out = {}
        for i in range(0, len(video_ids), 50):
            chunk = video_ids[i:i + 50]
            try:
                resp = yt.videos().list(part="snippet", id=",".join(chunk)).execute()
                for it in resp.get("items", []):
                    out[it["id"]] = it["snippet"]["title"]
            except Exception:
                pass
        return out
    except Exception:
        return {}


# ── 題材分類：從標題抽出頻道主題關鍵字群 ──
TOPIC_PATTERNS = [
    ("網格交易", r"網格|grid"),
    ("定投DCA", r"定投|dca|定期定額"),
    ("回測", r"回測|backtest"),
    ("風控/心法", r"風控|停損|部位|破產|心法|紀律"),
    ("Pionex/工具", r"pionex|派網|機器人|bot"),
    ("市場觀念", r"避坑|韭菜|陷阱|槓桿|趨勢|震盪"),
    ("爆款格式", r"我用\$|真實|實測|被動收入|A vs B|vs"),
]


def _classify(title: str) -> str:
    t = (title or "").lower()
    for cat, pat in TOPIC_PATTERNS:
        if re.search(pat, t, re.I):
            return cat
    return "其他"


def collect_analytics() -> dict:
    """從 yt_analytics 拉近期數據，回傳結構化 dict。"""
    result = {"channel": None, "top_videos": [], "by_category": {}}
    if not (_HAS_ANALYTICS and yt_analytics.available()):
        return result

    result["channel"] = yt_analytics.channel_summary(days=28)

    video_stats = yt_analytics.video_stats(days=60, limit=50)
    if not video_stats:
        return result

    # 取 ledger 建 videoId→slug 對照
    ledger = _load(LEDGER, {})
    slug_to_vid = {v: k for k, v in ledger.items()}
    vid_to_slug = {v: k for k, v in slug_to_vid.items()}

    # 抓標題
    all_vids = list(video_stats.keys())
    titles = _yt_video_titles(all_vids)

    rows = []
    for vid, s in video_stats.items():
        rows.append({
            "video_id": vid,
            "slug": vid_to_slug.get(vid, ""),
            "title": titles.get(vid, "（未知標題）"),
            "views": s.get("views") or 0,
            "retention": round(s.get("retention") or 0, 1),
            "avg_dur": round(s.get("avg_dur") or 0, 1),
            "subs": s.get("subs") or 0,
        })

    rows.sort(key=lambda x: x["views"], reverse=True)
    result["top_videos"] = rows[:20]

    # 依題材分類彙總
    cat_stats: dict[str, dict] = {}
    for r in rows:
        cat = _classify(r["title"])
        if cat not in cat_stats:
            cat_stats[cat] = {"count": 0, "total_views": 0, "total_subs": 0, "avg_ret": []}
        cat_stats[cat]["count"] += 1
        cat_stats[cat]["total_views"] += r["views"]
        cat_stats[cat]["total_subs"] += r["subs"]
        if r["retention"]:
            cat_stats[cat]["avg_ret"].append(r["retention"])

    for cat, d in cat_stats.items():
        ret_list = d.pop("avg_ret")
        d["avg_retention"] = round(sum(ret_list) / len(ret_list), 1) if ret_list else 0
        d["avg_views"] = round(d["total_views"] / d["count"]) if d["count"] else 0
    result["by_category"] = cat_stats

    return result


def ai_extract(data: dict) -> str:
    """用 Claude 從數據萃取選題建議（無 key 時回 ''）。"""
    if not API_KEY:
        return ""

    # 準備精簡數據摘要傳給 Claude
    ch = data.get("channel") or {}
    top5 = data.get("top_videos", [])[:5]
    cats = data.get("by_category", {})
    cat_lines = "\n".join(
        f"  - {c}：平均 {v['avg_views']} 觀看, 留存 {v['avg_retention']}%, 帶訂閱 {v['total_subs']}"
        for c, v in sorted(cats.items(), key=lambda x: -x[1]["avg_views"])
    ) or "  （無分類數據）"
    top5_lines = "\n".join(
        f"  - 「{r['title'][:30]}」 {r['views']} 觀看, 留存 {r['retention']}%"
        for r in top5
    ) or "  （無數據）"

    prompt = f"""你是量化阿森 YouTube 頻道（網格交易/定投/Pionex/量化）的流量分析師。

近 28 天頻道數據：
  觀看：{ch.get('views', '無')}，訂閱增：{ch.get('subs_gained', '無')}，平均留存：{ch.get('avg_pct', '無')}%

近 60 天各題材表現（平均觀看/留存/帶訂閱）：
{cat_lines}

近 60 天 TOP5 影片：
{top5_lines}

請根據以上數據，用**繁體中文**輸出：
1) 流量最強的 3 個題材方向（標題角度）
2) 下一批建議多做的格式/主題（3 條具體建議，可直接寫成腳本標題）
3) 建議避開的方向（觀看低、留存差的）

格式簡潔，每條一行，直接可貼入 production_orders。"""

    try:
        import requests
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": API_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": MODEL, "max_tokens": 600,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"].strip()
    except Exception as e:
        log_ops("流量部門", f"Claude 萃取失敗：{e}")
        return ""


def update_orders(suggestions: str) -> None:
    """把 AI 建議的關鍵詞增補到 production_orders.json（避免蓋掉 decision 已寫的）。"""
    if not suggestions:
        return
    orders = _load(ORDERS, {})
    existing = set(orders.get("preferred_keywords", []))

    # 從建議文字抽出量化/網格/定投等具體詞
    kw_pat = re.compile(
        r"(網格|定投|DCA|回測|風控|Pionex|派網|機器人|被動收入|"
        r"套利|槓桿|ETF|止損|資金費率|複利|實測|A vs B)", re.I
    )
    found = kw_pat.findall(suggestions)
    new_kw = [k for k in dict.fromkeys(found) if k not in existing]
    if new_kw:
        orders.setdefault("preferred_keywords", [])
        orders["preferred_keywords"] = list(existing) + new_kw
        orders["traffic_updated"] = tw_today()
        ORDERS.parent.mkdir(parents=True, exist_ok=True)
        ORDERS.write_text(json.dumps(orders, ensure_ascii=False, indent=2), encoding="utf-8")
        log_ops("流量部門", f"更新 production_orders 關鍵詞：{new_kw}")


def write_report(data: dict, suggestions: str) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    today = tw_today()
    ch = data.get("channel") or {}
    cats = data.get("by_category", {})
    top5 = data.get("top_videos", [])[:5]

    if cats:
        cat_md = "\n".join(
            f"| {c} | {v['count']} | {v['avg_views']:,} | {v['avg_retention']}% | {v['total_subs']} |"
            for c, v in sorted(cats.items(), key=lambda x: -x[1]["avg_views"])
        )
        cat_section = (
            "\n## 📊 題材分類表現（近 60 天）\n"
            "| 題材 | 影片數 | 平均觀看 | 平均留存 | 帶訂閱 |\n"
            "|------|--------|----------|----------|--------|\n"
            + cat_md
        )
    else:
        cat_section = "\n## 📊 題材分類\n（需 token_analytics.json 才有數據）"

    if top5:
        top_md = "\n".join(
            f"{i+1}. 「{r['title'][:35]}」 — {r['views']:,} 觀看，留存 {r['retention']}%"
            for i, r in enumerate(top5)
        )
        top_section = f"\n## 🏆 近期 TOP 5 影片\n{top_md}"
    else:
        top_section = "\n## 🏆 近期 TOP 5 影片\n（無數據）"

    ch_section = ""
    if ch:
        ch_section = (
            f"\n## 📈 頻道近 28 天\n"
            f"- 總觀看：{ch.get('views', 0):,}\n"
            f"- 訂閱增：{ch.get('subs_gained', 0)}\n"
            f"- 平均留存：{ch.get('avg_pct', 0):.1f}%\n"
            f"- 平均觀看秒：{ch.get('avg_dur', 0):.0f}s"
        )

    ai_section = f"\n## 🤖 AI 選題建議\n{suggestions}" if suggestions else \
        "\n## 🤖 AI 選題建議\n（無 ANTHROPIC_API_KEY 或 Analytics token，略過）"

    md = (
        f"# 流量部門｜數據選題 {today}\n"
        f"_{datetime.now(TW).strftime('%H:%M')} 自動產出_\n"
        + ch_section + cat_section + top_section + ai_section
    )
    path = REPORTS / f"{today}_流量選題.md"
    path.write_text(md, encoding="utf-8")
    log_ops("流量部門", f"報告寫入 {path.name}")


def main() -> int:
    log_ops("流量部門", "開始數據選題分析")
    try:
        data = collect_analytics()
        suggestions = ai_extract(data)
        update_orders(suggestions)

        # 存 traffic_data.json 供 decision_dept 讀取
        STUDIO.mkdir(parents=True, exist_ok=True)
        TRAFFIC.write_text(
            json.dumps({
                "date": tw_today(),
                "channel": data.get("channel"),
                "by_category": data.get("by_category"),
                "top5": data.get("top_videos", [])[:5],
                "suggestions": suggestions,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        write_report(data, suggestions)
        log_ops("流量部門", "完成")
    except Exception as e:
        log_ops("流量部門", f"FATAL: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
