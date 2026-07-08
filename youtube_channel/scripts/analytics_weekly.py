#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""analytics_weekly.py — 每週抓 YouTube 完播率,對比「最近7天新片 vs 整體」,推 ntfy + 寫報告。
讓內容方向持續數據驅動:看校正後新片完播有沒有往上、哪些題材完播高。
需 token_manage.json 含 yt-analytics.readonly scope。"""
from __future__ import annotations
import json, sys, os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(ROOT / "scripts"))
    from ops import log_ops
except Exception:
    def log_ops(d, m): pass

NTFY = os.environ.get("ANALYTICS_NTFY", "https://ntfy.sh/carsonyt2026")
REPORTS = ROOT / "STUDIO" / "REPORTS"


def main() -> int:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_file(str(ROOT / "token_manage.json"))
    ya = build("youtubeAnalytics", "v2", credentials=creds)
    yt = build("youtube", "v3", credentials=creds)
    end = (date.today() - timedelta(days=1)).isoformat()
    start = (date.today() - timedelta(days=29)).isoformat()

    def q(**kw):
        return ya.reports().query(ids="channel==MINE", **kw).execute()

    # ① 整體 28 天
    o = q(startDate=start, endDate=end,
          metrics="views,averageViewPercentage,averageViewDuration,subscribersGained")
    orow = (o.get("rows") or [[0, 0, 0, 0]])[0]
    views, pct, dur, subs = orow[0], round(orow[1], 1), round(orow[2]), orow[3]

    # ② per-video 完播(28天有觀看的片)
    v = q(startDate=start, endDate=end, dimensions="video",
          metrics="views,averageViewPercentage", sort="-views", maxResults=40)
    vrows = v.get("rows", [])
    pctmap = {r[0]: (min(100.0, r[1]) if r[1] is not None else r[1]) for r in vrows}  # loop重播Shorts原生>100%,夾回避免污染均值

    # ③ 最近 7 天發布的片(看新方向效果)
    up = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    recent_ids, titles = [], {}
    cut = datetime.now(timezone.utc) - timedelta(days=7)
    r = yt.playlistItems().list(part="contentDetails,snippet", playlistId=up, maxResults=50).execute()
    for it in r["items"]:
        vid = it["contentDetails"]["videoId"]
        pub = datetime.fromisoformat(it["contentDetails"].get("videoPublishedAt", it["snippet"]["publishedAt"]).replace("Z", "+00:00"))
        titles[vid] = it["snippet"]["title"]
        if pub >= cut:
            recent_ids.append(vid)
    new_pcts = [pctmap[i] for i in recent_ids if i in pctmap]
    new_avg = round(sum(new_pcts) / len(new_pcts), 1) if new_pcts else None

    # 補抓 top/bottom 片標題
    need = [r[0] for r in vrows[:40] if r[0] not in titles]
    for i in range(0, len(need), 50):
        vr = yt.videos().list(part="snippet", id=",".join(need[i:i+50])).execute()
        for it in vr["items"]:
            titles[it["id"]] = it["snippet"]["title"]
    top = sorted([(round(r[1]), titles.get(r[0], r[0])) for r in vrows if pctmap.get(r[0], 0)], reverse=True)[:5]
    low = sorted([(round(r[1]), titles.get(r[0], r[0])) for r in vrows], key=lambda x: x[0])[:4]

    # ③b 額外回寫機器可讀 completion_signals.json（供決策閉環）
    COMPLETION = ROOT / "STUDIO" / "completion_signals.json"
    try:
        high_topics = [t[:40] for _, t in top if t][:5]
        low_topics = [t[:40] for _, t in low if t][:4]
        csig = {
            "generated": date.today().isoformat(),
            "overall_avg_pct": pct,
            "new_avg_pct": new_avg,
            "new_vs_overall_delta": round(new_avg - pct, 1) if new_avg is not None else None,
            "high_completion_topics": high_topics,
            "low_completion_topics": low_topics,
        }
        COMPLETION.parent.mkdir(parents=True, exist_ok=True)
        COMPLETION.write_text(json.dumps(csig, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as _ce:
        print(f"[warn] completion_signals.json 寫入失敗：{_ce}", file=sys.stderr)

    # ④ 報告
    today = date.today().isoformat()
    lines = [f"# 每週完播率追蹤｜{today}", "",
             f"## 整體（近28天）", f"- 觀看 {views}　平均觀看 {dur}s　新增訂閱 {subs}",
             f"- **完播率 {pct}%**（健康線 50-60；目標往上）", ""]
    arrow = ""
    if new_avg is not None:
        delta = round(new_avg - pct, 1)
        arrow = f"📈+{delta}" if delta > 0 else f"📉{delta}"
        lines += [f"## 最近7天新片（看新方向效果）",
                  f"- 新片平均完播率 **{new_avg}%**（vs 整體 {pct}%，{arrow}）", ""]
    lines += ["## 完播率最高（>100%=觀眾重看loop，越黏越爆）"] + [f"- {p}% ｜ {t[:46]}" for p, t in top]
    lines += ["", "## 完播率最低（流量殺手，避開這類）"] + [f"- {p}% ｜ {t[:46]}" for p, t in low]
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"completion_{today.replace('-', '')}.md").write_text("\n".join(lines), encoding="utf-8")

    # ⑤ 推 ntfy
    summary = f"完播率 {pct}%"
    if new_avg is not None:
        summary += f"｜新片 {new_avg}% {arrow}"
    summary += f"｜最高:{top[0][1][:18] if top else '-'}({top[0][0] if top else 0}%)"
    try:
        import requests
        requests.post(NTFY, data=summary.encode("utf-8"),
                      headers={"Title": "YT 每週完播率", "Tags": "bar_chart"}, timeout=15)
    except Exception:
        pass
    print("[ok]", summary)
    log_ops("完播率追蹤", summary)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] {e}", file=sys.stderr)
        raise SystemExit(1)
